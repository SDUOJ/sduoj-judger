"""Bounded consumers; no HTTP server and no per-request subprocess launch."""
import asyncio
from collections import Counter
import json
import logging
import os
import secrets
import signal
import time
import traceback

from ide_intelligence.config import load_config
from ide_intelligence.shared_pool import SharedLanguagePool
from ide_intelligence.session_store import SessionMissing
from .protocol import Job, key, encode, RESULT, RESULT_ACK, HEARTBEAT, ROUTE, IDENTIFIER
from .sessions import ExecutionSessions
from .redis_client import create_redis

LOG = logging.getLogger(__name__)


def fault_trace(error):
    # Frame locations only: exception messages/source lines may contain user
    # text or connection credentials and must not enter shared operator logs.
    return encode([[os.path.basename(frame.filename), frame.name, frame.lineno]
                   for frame in traceback.extract_tb(error.__traceback__)[-8:]])


class Worker:
    def __init__(self, role, language=None, redis=None, *, worker_id=None, concurrency=None):
        self.role, self.language = role, language
        self.id = worker_id or os.getenv('SDUOJ_IDE_WORKER_ID', os.getenv('HOSTNAME', 'worker'))
        if not IDENTIFIER.fullmatch(self.id):
            raise ValueError('Invalid worker id')
        self.epoch = secrets.token_hex(16)
        self.concurrency = concurrency or int(os.getenv('SDUOJ_IDE_CONCURRENCY', '2'))
        if not 1 <= self.concurrency <= 32:
            raise ValueError('Invalid concurrency')
        self.redis = redis or create_redis(os.environ['SDUOJ_IDE_REDIS_URL'],
            decode_responses=True, socket_connect_timeout=2, max_connections=64)
        self.sessions = ExecutionSessions(self.redis)
        self.counters = Counter()
        self.closed = asyncio.Event()
        self.ready = asyncio.Event()
        self.tasks = set()
        self.queue = key('q', role, self.id, self.epoch)
        self.control_queue = key('q', role, self.id, self.epoch, 'control')
        self.pool = None
        self.debug = None

    def registration(self):
        return {'workerId': self.id, 'workerEpoch': self.epoch, 'role': self.role,
                'language': self.language, 'queue': self.queue, 'controlQueue': self.control_queue,
                'concurrency': self.concurrency, 'counters': dict(self.counters),
                'metrics': self.pool.metrics_snapshot() if self.pool else
                           self.debug.metrics() if self.debug else {},
                'updatedAt': int(time.time() * 1000)}

    async def announce(self):
        ok = await self.redis.eval(HEARTBEAT, 3, key('node', self.id), key('worker', self.id),
            key('registry', self.role, self.language or 'all'), self.epoch,
            encode(self.registration()), self.id, int(time.time() * 1000))
        if not ok:
            raise RuntimeError('Worker lease lost')

    async def heartbeat(self):
        try:
            while not self.closed.is_set():
                await self.announce()
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOG.error('Worker heartbeat failed; stop admission category=%s', type(error).__name__)
            self.closed.set()

    async def reply(self, job, data=None, status=200, error=None, processing=None):
        value = {'requestId': job.request_id, 'sessionId': job.value['sessionId'],
                 'sessionEpoch': job.value['sessionEpoch'], 'workerId': self.id,
                 'workerEpoch': self.epoch, 'httpStatus': status, 'data': data, 'error': error}
        keys = [key('result', job.request_id), key('reply', job.value['replyTo'])]
        if processing:
            keys.append(processing)
        await self.redis.eval(RESULT_ACK if processing else RESULT, len(keys), *keys,
                              encode(value), 120, job.request_id)

    async def initialize(self):
        if not await self.redis.set(key('node', self.id), self.epoch, nx=True, ex=12):
            raise RuntimeError('Worker id is already running')
        if self.role == 'lsp':
            config = load_config()
            count = int(os.getenv('SDUOJ_IDE_LSP_PROCESSES', '1'))
            if not 1 <= count <= 16:
                raise ValueError('Invalid process count')
            from ide_intelligence.resource_settings import integer
            max_documents = integer('SDUOJ_IDE_' + self.language.upper() + '_MAX_DOCUMENTS',
                                    int(os.getenv('SDUOJ_IDE_MAX_DOCUMENTS', '64')))
            self.pool = SharedLanguagePool(config, max_concurrency=self.concurrency,
                max_starting=1, max_waiters=self.concurrency * 2,
                language_concurrency={self.language: self.concurrency},
                language_processes={self.language: count},
                language_max_documents=max_documents)
            # This container exclusively owns its configured language slots.
            self.pool.processes = {self.language: count}
            self.pool.max_processes = count
        else:
            from .debug import DebugExecution
            self.debug = DebugExecution(self)
            await self.debug.start()

    async def execute_lsp(self, job):
        value = job.value
        meta = await self.sessions.metadata(value['sessionId'], value['ownerId'], value['sessionEpoch'])
        operation = value['operation']
        if meta['kind'] != 'lsp' or meta['language'] != self.language:
            raise SessionMissing()
        if value.get('workerEpoch') and value['workerEpoch'] != self.epoch:
            raise SessionMissing()
        route = encode({'workerId': self.id, 'workerEpoch': self.epoch, 'queue': self.queue})
        owned = await self.redis.eval(ROUTE, 2, key('session', value['sessionId']),
            key('route', value['sessionId']), value['ownerId'], value['sessionEpoch'], self.id,
            route, key('worker') + ':')
        if not owned:
            return {'revision': meta['revision'], 'status': 'degraded', 'items': []}
        if operation == 'close':
            await self.pool.release(value['sessionId'])
            return {'closed': True}
        if operation not in {'completion', 'signatureHelp', 'definition', 'diagnostics'}:
            raise ValueError('Unsupported LSP operation')
        if operation in {'completion', 'signatureHelp'}:
            latest = await self.redis.get(key('latest', value['sessionId'], operation))
            if latest != job.request_id:
                self.counters['superseded'] += 1
                return None
        session = await self.sessions.get(value['sessionId'], int(value['ownerId']))
        request = value['body']
        if session.revision != request.get('revision'):
            return {'revision': session.revision, 'status': 'stale'}
        budget = min(value['deadlineAt'] - int(time.time() * 1000), 10000)
        if budget <= 0:
            return None
        return await self.pool.execute(self.sessions, session, operation, request, budget)

    async def process(self, request_id, processing=None):
        job = None
        async def respond(data=None, **kwargs):
            if processing:
                kwargs['processing'] = processing
            await self.reply(job, data, **kwargs)

        try:
            if processing:
                await self.redis.expire(processing, 2100)
            raw = await self.redis.get(key('job', request_id))
            if not raw:
                self.counters['expired'] += 1
                if processing:
                    await self.redis.lrem(processing, 1, request_id)
                return
            job = Job.parse(raw)
            if job.request_id != request_id:
                raise ValueError('Incorrect request id')
            if processing and await self.redis.exists(key('result', request_id)):
                # A duplicate queue entry cannot execute a debugger command twice.
                await self.redis.lrem(processing, 1, request_id)
                return
            if job.request_id != request_id or job.expired:
                self.counters['expired'] += 1
                if self.debug:
                    await self.debug.reject_unstarted(job, 'DEBUG_TASK_EXPIRED')
                    await respond(status=504, error='DEBUG_TASK_EXPIRED')
                else:
                    await respond()
                return
            if job.value['role'] != self.role:
                raise ValueError('Incorrect worker role')
            # Stop/pause have separate consumers and never acquire LSP/run permits.
            data = await (self.execute_lsp(job) if self.pool else self.debug.execute(job))
            await respond(data)
            self.counters['completed'] += 1
        except SessionMissing:
            if job:
                await respond(status=410, error='IDE_SESSION_EXPIRED')
        except asyncio.CancelledError:
            if processing:
                try:
                    await asyncio.wait_for(self.interrupt(request_id, job, processing), 5)
                except Exception as error:
                    # Keep the processing entry if Redis cannot confirm a
                    # terminal result. Never replay non-idempotent commands.
                    LOG.error('Debug interruption receipt unconfirmed category=%s', type(error).__name__)
            raise
        except Exception as error:
            self.counters['failed'] += 1
            if job:
                code = getattr(error, 'code', None)
                if self.pool and not code:
                    # Optional analysis fails quietly; no host traceback/source leaks.
                    await respond({'revision': job.value['body'].get('revision'),
                        'status': 'degraded', 'isIncomplete': True, 'items': [],
                        'diagnostics': [], 'locations': [], 'signatures': []})
                else:
                    await respond(status=getattr(error, 'status', 503),
                                     error=code or 'DEBUG_UNAVAILABLE')
            LOG.warning('IDE job failed: role=%s language=%s category=%s',
                        self.role, self.language, type(error).__name__)

    async def interrupt(self, request_id, job, processing):
        if job is None:
            raw = await self.redis.get(key('job', request_id))
            if not raw:
                # No executable job remains; the processing id is expired.
                await self.redis.lrem(processing, 1, request_id)
                return
            job = Job.parse(raw)
        if job.request_id != request_id or job.value['role'] != 'debug':
            raise ValueError('Incorrect interrupted job')
        await self.debug.interrupt(job)
        await self.reply(job, status=503, error='DEBUG_COMMAND_INTERRUPTED', processing=processing)

    async def drain_processing(self):
        # BLMOVE can commit at Redis just as its awaiting consumer is cancelled,
        # before Python receives the id. Recover those claims after consumers
        # stop, without executing or replaying their debugger operations.
        for queue in (self.queue, self.control_queue):
            processing = queue + ':processing'
            for request_id in dict.fromkeys(await self.redis.lrange(processing, 0, 63)):
                await self.interrupt(request_id, None, processing)

    async def consume(self, control=False):
        queue = self.control_queue if control else self.queue
        while not self.closed.is_set():
            phase = 'claim'
            try:
                if self.role == 'debug':
                    processing = queue + ':processing'
                    request_id = await self.redis.blmove(queue, processing, 2, 'LEFT', 'RIGHT')
                else:
                    processing = None
                    result = await self.redis.blpop([queue, key('q', 'lsp', self.language)], timeout=2)
                    request_id = result[1] if result else None
                if request_id:
                    phase = 'process'
                    await self.process(request_id, processing)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOG.error('Redis consumer unavailable; stop admission role=%s language=%s phase=%s category=%s trace=%s',
                          self.role, self.language, phase, type(error).__name__, fault_trace(error))
                self.closed.set()

    async def maintain(self):
        try:
            while not self.closed.is_set():
                await asyncio.sleep(10)
                if self.pool:
                    await self.pool.sweep(self.sessions)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOG.error('Worker maintenance failed; stop admission category=%s', type(error).__name__)
            self.closed.set()

    async def run(self, *, manage_signals=True):
        try:
            await self.initialize()
            loop = asyncio.get_running_loop()
            if manage_signals:
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, self.closed.set)
            await self.announce()
            coroutines = [self.heartbeat(), self.maintain()]
            coroutines += [self.consume() for _ in range(self.concurrency)]
            if self.role == 'debug':
                coroutines += [self.consume(control=True) for _ in range(2)]
            self.tasks = {asyncio.create_task(coro) for coro in coroutines}
            self.ready.set()
            LOG.info('IDE worker ready role=%s language=%s id=%s', self.role, self.language, self.id)
            await self.closed.wait()
        finally:
            self.ready.clear()
            # Runtime closes its full sandbox trees before releasing its reservation.
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            if self.debug:
                try:
                    await asyncio.wait_for(self.drain_processing(), 10)
                except Exception as error:
                    LOG.error('Debug processing drain unconfirmed category=%s trace=%s',
                              type(error).__name__, fault_trace(error))
                await self.debug.close()
            if self.pool:
                await self.pool.close()
            await self.redis.eval("""
                if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end
                redis.call('DEL',KEYS[1],KEYS[2])
                redis.call('ZREM',KEYS[3],ARGV[2])
                return 1
                """, 3, key('node', self.id), key('worker', self.id),
                key('registry', self.role, self.language or 'all'), self.epoch, self.id)
            await self.redis.close()
