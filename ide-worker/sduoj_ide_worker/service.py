"""One registered service/container, four bounded LSP pools and one Debug runtime."""
import asyncio
import json
import logging
import os
import signal

from .nacos import Nacos, fingerprint
from .protocol import IDENTIFIER
from .worker import Worker

LOG = logging.getLogger(__name__)


class Service:
    def __init__(self, nacos=None, worker_factory=Worker):
        self.id = os.getenv('SDUOJ_IDE_WORKER_ID', os.getenv('HOSTNAME', 'worker'))
        if not IDENTIFIER.fullmatch(self.id) or len(self.id) > 70:
            raise ValueError('Invalid unified worker id')
        self.port = int(os.getenv('SDUOJ_IDE_HEALTH_PORT', '9086'))
        self.nacos = nacos or Nacos()
        self.closed = asyncio.Event()
        self.ready = False
        self.reason = 'starting'
        self.children = [worker_factory('lsp', language, worker_id=self.id + '-' + language,
            concurrency=int(os.getenv('SDUOJ_IDE_' + language.upper() + '_CONCURRENCY',
                                      '1' if language == 'java' else '2')))
            for language in ('c', 'cpp', 'java', 'python')]
        self.children.append(worker_factory('debug', worker_id=self.id + '-debug',
            concurrency=int(os.getenv('SDUOJ_IDE_DEBUG_CONCURRENCY', '2'))))

    def health(self):
        return {'ready': self.ready, 'reason': self.reason, 'workerId': self.id,
                'components': [child.registration() for child in self.children]}

    async def http(self, reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            line = request.split(b'\r\n', 1)[0]
            valid = line in (b'GET /health HTTP/1.1', b'GET /ready HTTP/1.1')
            status = 200 if valid and self.ready else 503 if valid else 404
            body = json.dumps(self.health() if valid else {}).encode()
            writer.write(('HTTP/1.1 %d %s\r\nContent-Type: application/json\r\n'
                'Content-Length: %d\r\nConnection: close\r\n\r\n' %
                (status, 'OK' if status == 200 else 'Unavailable', len(body))).encode() + body)
            await asyncio.wait_for(writer.drain(), 2)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError, ConnectionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def control_plane(self):
        failures = 0
        try:
            elapsed = 0
            while not self.closed.is_set():
                await asyncio.sleep(5)
                try:
                    await self.nacos.beat()
                    elapsed += 5
                    if elapsed >= 30:
                        raw = await self.nacos.configuration()
                        elapsed = 0
                        if fingerprint(raw) != os.environ['SDUOJ_IDE_NACOS_HASH']:
                            self.reason = 'configuration_changed_restart_required'
                            self.closed.set()
                            return
                except Exception as error:
                    failures += 1
                    self.ready = False
                    self.reason = 'discovery_retrying'
                    LOG.warning('Nacos heartbeat retry count=%s category=%s', failures,
                                type(error).__name__)
                    if failures >= 3:
                        raise
                    continue
                failures = 0
                self.ready, self.reason = True, 'ready'
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOG.error('IDE control plane unavailable category=%s', type(error).__name__)
            self.reason = 'control_plane_unavailable'
            self.closed.set()

    async def run(self, *, manage_signals=True):
        tasks, auxiliaries = [], []
        registered = False
        server = None
        try:
            if manage_signals:
                for sig in (signal.SIGTERM, signal.SIGINT):
                    asyncio.get_running_loop().add_signal_handler(sig, self.closed.set)
            server = await asyncio.start_server(self.http, '0.0.0.0', self.port, limit=4096)
            tasks = [asyncio.create_task(child.run(manage_signals=False)) for child in self.children]
            ready = asyncio.ensure_future(asyncio.gather(
                *(child.ready.wait() for child in self.children)))
            stopped = asyncio.create_task(self.closed.wait())
            auxiliaries.extend([ready, stopped])
            done, _ = await asyncio.wait([ready, stopped, *tasks],
                                         timeout=30, return_when=asyncio.FIRST_COMPLETED)
            if ready not in done or any(task in done for task in tasks) or self.closed.is_set():
                for task in tasks:
                    if task in done:
                        task.result()
                raise RuntimeError('Unified worker components did not become ready')
            # No discovery entry before all components have acquired their leases.
            await self.nacos.register(self.id, self.port)
            registered = True
            await self.nacos.beat()
            self.ready, self.reason = True, 'ready'
            control = asyncio.create_task(self.control_plane())
            auxiliaries.append(control)
            done, _ = await asyncio.wait([stopped, control, *tasks],
                                         return_when=asyncio.FIRST_COMPLETED)
            if stopped not in done and control not in done:
                self.reason = 'component_failed'
                raise RuntimeError('Unified worker component stopped')
        finally:
            self.ready = False
            self.closed.set()
            for child in self.children:
                child.closed.set()
            # Deregister first, then drain/kill sandbox trees, then release leases.
            # Also try deletion after an uncertain registration HTTP response.
            try:
                if registered or self.nacos.instance:
                    await self.nacos.deregister()
            except Exception as error:
                LOG.error('Nacos deregistration unconfirmed category=%s', type(error).__name__)
            for task in auxiliaries:
                task.cancel()
            await asyncio.gather(*auxiliaries, return_exceptions=True)
            await asyncio.gather(*tasks, return_exceptions=True)
            if server:
                server.close()
                await server.wait_closed()
            await self.nacos.close()
