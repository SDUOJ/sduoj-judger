"""Redis command adapter around the existing bounded native debug runtime."""
import asyncio
from contextvars import ContextVar
from dataclasses import replace
import json
import os
import time
from pathlib import Path

from ide_debug.authorization import SessionAuthorizer
from ide_debug.cgroups import preflight
from ide_debug.config import Policy
from ide_debug.models import Create, Command, Control, Cancel
from ide_debug.node_lock import node_lock
from ide_debug.profiles import DebugError, Profile, load_manifest, digest
from ide_debug.resolver import Resolver
from ide_debug.runtime import Runtime
from .protocol import key, encode, CANCEL_CREATE

ALLOCATION = ContextVar('gateway_debug_allocation', default=None)


class DebugStore:
    def __init__(self, redis, policy, worker):
        self.redis, self.policy, self.worker = redis, policy, worker

    async def claim_node(self, incarnation):
        # Reservations intentionally survive a crash. A restarted node must
        # prove its old cgroup empty before an operator releases the reservation.
        script = """
        if redis.call('HEXISTS',KEYS[1],ARGV[1]) == 1 then return 0 end
        local total = {hard=0,budget=0,resident=0,active=0}
        for _,raw in ipairs(redis.call('HVALS',KEYS[1])) do
          local p = cjson.decode(raw)
          for name,_ in pairs(total) do total[name] = total[name] + p[name] end
        end
        local proposed = cjson.decode(ARGV[2])
        for name,_ in pairs(total) do
          if total[name] + proposed[name] > tonumber(proposed['global_' .. name]) then return 0 end
        end
        redis.call('HSET',KEYS[1],ARGV[1],ARGV[2])
        return 1
        """
        import os
        p = self.policy
        value = {'incarnation': incarnation, 'hard': p.hard, 'budget': p.budget,
                 'resident': p.resident, 'active': p.active,
                 'global_hard': int(os.getenv('SDUOJ_DEBUG_GLOBAL_HARD', str(64 * 1024**3))),
                 'global_budget': int(os.getenv('SDUOJ_DEBUG_GLOBAL_BUDGET', str(56 * 1024**3))),
                 'global_resident': 1024, 'global_active': 32}
        return bool(await self.redis.eval(script, 1, key('debug', 'reservations'), p.node, encode(value)))

    async def renew_node(self, incarnation):
        raw = await self.redis.hget(key('debug', 'reservations'), self.policy.node)
        return (bool(raw) and json.loads(raw)['incarnation'] == incarnation
                and await self.redis.get(key('node', self.worker.id)) == self.worker.epoch)

    async def release_node(self, incarnation):
        return await self.redis.eval("""
        local raw=redis.call('HGET',KEYS[1],ARGV[1])
        if raw and cjson.decode(raw).incarnation==ARGV[2] then return redis.call('HDEL',KEYS[1],ARGV[1]) end
        return 0
        """, 1, key('debug', 'reservations'), self.policy.node, incarnation)

    async def claim_user(self, user, session, ttl):
        value = await self.redis.eval("""
        local old=redis.call('GET',KEYS[1])
        if old and old~=ARGV[1] then return old end
        redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2])
        return ''
        """, 1, key('debug', 'user', user), session, ttl)
        return value or None

    async def release_user(self, user, session):
        await self.redis.eval("if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                              1, key('debug', 'user', user), session)

    async def open_receipt(self, user, command):
        raw = await self.redis.get(key('debug', 'receipt', user, command))
        return json.loads(raw) if raw else None

    async def save_open_receipt(self, user, command, fingerprint, session):
        await self.redis.set(key('debug', 'receipt', user, command),
            encode({'hash': fingerprint, 'sessionId': session}), ex=2100)

    async def save(self, session):
        await self.redis.set(key('debug', 'state', session.id), encode(session.snapshot()), ex=2100)

    async def save_spec(self, session, spec):
        await self.redis.set(key('debug', 'spec', session.id), encode(spec), ex=2100)

    async def terminal(self, session):
        pipe = self.redis.pipeline(transaction=True)
        pipe.delete(key('debug', 'spec', session.id))
        pipe.set(key('debug', 'state', session.id), encode(session.snapshot()), ex=300)
        pipe.expire(key('session', session.id), 300)
        pipe.expire(key('debug', 'commands', session.id), 300)
        pipe.set(key('debug', 'cleanup', session.id), encode({
            'sessionEpoch': session.epoch, 'clean': True}), ex=2100)
        diagnostics = getattr(session.sandbox, 'guardian_diagnostics', None)
        if diagnostics:
            # Operator-only evidence; Gateway never exposes this namespace.
            pipe.set(key('debug', 'private', session.id), encode(diagnostics()), ex=300)
        await pipe.execute()
        await self.release_user(session.user, session.id)

    async def get(self, session, user):
        raw = await self.redis.get(key('debug', 'state', session))
        if not raw:
            raise DebugError('DEBUG_SESSION_LOST', 410)
        value = json.loads(raw)
        if value['userId'] != user:
            raise DebugError('DEBUG_SESSION_NOT_FOUND', 404)
        return value


class DebugExecution:
    def __init__(self, worker):
        self.worker = worker
        self.policy = Policy.environment()
        if not os.getenv('AUTOLAB_DEBUG_NODE'):
            self.policy = replace(self.policy, node='debug-'+digest(worker.id)[:24])
        self.runtime = None
        self.runtime_started = False
        self.resolver = None
        self.mirror_task = None
        self.lock = None
        self.cursors = {}
        self.mirrored_states = {}

    async def start(self):
        if not self.policy.enabled:
            raise RuntimeError('Debug worker is disabled')
        self.manifest = load_manifest(self.policy.manifest)
        self.lock = node_lock(self.policy.state_dir)
        self.lock.__enter__()
        preflight(self.policy)
        state = Path(self.policy.state_dir)
        if any(path.name != '.agent.lock' for path in state.iterdir()):
            raise RuntimeError('Debug state needs orphan recovery')
        self.resolver = Resolver()
        self.runtime = Runtime(self.policy, DebugStore(self.worker.redis, self.policy, self.worker),
            self.manifest, authorizer=SessionAuthorizer(self.resolver), identity_factory=lambda: ALLOCATION.get())
        await self.runtime.start()
        self.runtime_started = True
        self.mirror_task = asyncio.create_task(self.mirror())

    def metrics(self):
        value = self.runtime.view_metrics() if self.runtime else {}
        value['templateIds'] = [name for name, profile in self.manifest.items() if profile.get('verified')]
        value['languages'] = sorted({profile['language'] for profile in self.manifest.values() if profile.get('verified')})
        return value

    async def flush_events(self):
        for session in list(self.runtime.sessions.values()):
            signature = (session.cursor, session.version, bool(session.ticket or session.actor.locked()))
            if self.mirrored_states.get(session.id) == signature:
                continue
            cursor = self.cursors.get(session.id, 0)
            events = [event for event in session.events if event['cursor'] > cursor]
            # One bounded batch per session; Redis never receives one write per output byte.
            pipe = self.worker.redis.pipeline(transaction=True)
            pipe.set(key('debug', 'state', session.id), encode(session.snapshot()), ex=2100)
            if events:
                pipe.rpush(key('debug', 'events', session.id), *(encode(event) for event in events))
                pipe.ltrim(key('debug', 'events', session.id), -256, -1)
                pipe.set(key('debug', 'event-cursor', session.id), events[-1]['cursor'], ex=2100)
                pipe.expire(key('debug', 'events', session.id), 2100)
            # Releasing actor.lock is also observable state. It has no new LSP/
            # debugger event, so publish the idle snapshot without replaying any
            # command or advancing its event cursor.
            pipe.publish(key('debug', 'events-wake'), session.id)
            await pipe.execute()
            if events:
                self.cursors[session.id] = events[-1]['cursor']
            self.mirrored_states[session.id] = signature
        self.cursors = {sid: cursor for sid, cursor in self.cursors.items()
                        if sid in self.runtime.sessions}
        self.mirrored_states = {sid: state for sid, state in self.mirrored_states.items()
                                if sid in self.runtime.sessions}

    async def mirror(self):
        try:
            while True:
                await self.flush_events()
                await asyncio.sleep(.05)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Losing the bus cannot leave execution running without ownership.
            self.worker.closed.set()

    async def reject_unstarted(self, job, code, claimed=False):
        value = job.value
        if value.get('operation') != 'create':
            return
        await self.worker.redis.eval(CANCEL_CREATE, 3,
            key('session', value['sessionId']), key('debug', 'user', value['ownerId']),
            key('debug', 'open', value['ownerId'], value.get('body', {}).get('commandId', 'invalid')),
            value['ownerId'], value['sessionEpoch'], code, job.request_id if claimed else '')

    async def interrupt(self, job):
        value = job.value
        code = 'DEBUG_COMMAND_INTERRUPTED'
        if value.get('operation') == 'create':
            if value['sessionId'] not in self.runtime.sessions:
                await self.reject_unstarted(job, code, claimed=True)
        elif value.get('operation') == 'command':
            body = value.get('body', {})
            command_id = body.get('commandId')
            if not isinstance(command_id, str):
                return
            # Change only this request's unfinished claim. Accepted commands
            # and different payloads retain their original receipt.
            await self.worker.redis.eval("""
            local raw=redis.call('HGET',KEYS[1],ARGV[1])
            if not raw then return 0 end
            local prior=cjson.decode(raw)
            if prior.status~='claimed' or prior.hash~=ARGV[2] then return 0 end
            redis.call('HSET',KEYS[1],ARGV[1],ARGV[3])
            return 1
            """, 1, key('debug', 'commands', value['sessionId']), command_id, digest(body),
                encode({'hash': digest(body), 'status': 'rejected', 'error': code, 'httpStatus': 503}))

    async def execute(self, job):
        value = job.value
        if value.get('workerEpoch') != self.worker.epoch:
            raise DebugError('DEBUG_SESSION_LOST', 410)
        meta = await self.worker.sessions.metadata(value['sessionId'], value['ownerId'], value['sessionEpoch'])
        if meta['kind'] != 'debug':
            raise DebugError('DEBUG_SESSION_NOT_FOUND', 404)
        actor = value.get('actor')
        if not actor or str(actor.get('userId')) != value['ownerId']:
            raise DebugError('DEBUG_SESSION_NOT_FOUND', 404)
        operation, body, user = value['operation'], value['body'], int(value['ownerId'])
        if operation == 'create':
            try:
                request = Create(**body)
            except ValueError as error:
                await self.reject_unstarted(job, 'DEBUG_INVALID_REQUEST')
                raise DebugError('DEBUG_INVALID_REQUEST', 400) from error
            try:
                resolved = await self.resolver.resolve(request, actor)
                if resolved != meta['resolved']:
                    raise DebugError('DEBUG_CONTEXT_CHANGED', 403)
                Profile.resolve(self.manifest, resolved['template'], request.language,
                                resolved.get('parameters', {}))
            except Exception:
                await self.reject_unstarted(job, 'DEBUG_CREATE_REJECTED')
                raise
            if job.expired:
                await self.reject_unstarted(job, 'DEBUG_TASK_EXPIRED')
                raise DebugError('DEBUG_TASK_EXPIRED', 504)
            if request.restoreOnly:
                token = ALLOCATION.set((value['sessionId'], value['sessionEpoch']))
                try:
                    return await self.runtime.create(user, request, resolved['template'],
                        prefix=resolved['sourcePrefix'], parameters=resolved.get('parameters', {}), actor=actor)
                finally:
                    ALLOCATION.reset(token)
            phase = await self.worker.redis.eval("""
            local raw=redis.call('GET',KEYS[1])
            if not raw then return 'missing' end
            local meta=cjson.decode(raw)
            if meta.ownerId~=ARGV[1] or meta.sessionEpoch~=ARGV[2] then return 'missing' end
            if meta.createPhase~='reserved' then return meta.createPhase or 'uncertain' end
            meta.createPhase='claimed'
            meta.createRequestId=ARGV[3]
            redis.call('SET',KEYS[1],cjson.encode(meta),'KEEPTTL')
            return 'execute'
            """, 1, key('session', value['sessionId']), value['ownerId'], value['sessionEpoch'], job.request_id)
            if phase == 'active':
                return (await self.runtime.lookup(value['sessionId'], user)).snapshot()
            if phase != 'execute':
                raise DebugError('DEBUG_STATUS_UNCERTAIN', 409)
            token = ALLOCATION.set((value['sessionId'], value['sessionEpoch']))
            try:
                result = await self.runtime.create(user, request, resolved['template'],
                    prefix=resolved['sourcePrefix'], parameters=resolved.get('parameters', {}), actor=actor)
                await self.worker.redis.eval("""
                local raw=redis.call('GET',KEYS[1])
                if not raw then return 0 end
                local meta=cjson.decode(raw)
                if meta.createRequestId~=ARGV[1] then return 0 end
                meta.createPhase='active'
                redis.call('SET',KEYS[1],cjson.encode(meta),'KEEPTTL')
                return 1
                """, 1, key('session', value['sessionId']), job.request_id)
                return result
            except Exception:
                if value['sessionId'] not in self.runtime.sessions:
                    await self.reject_unstarted(job, 'DEBUG_CREATE_REJECTED', claimed=True)
                raise
            finally:
                ALLOCATION.reset(token)
        session = await self.runtime.lookup(value['sessionId'], user)
        if operation == 'command':
            request = Command(**body)
            await self.runtime.authorizer.check(session, actor, fresh=request.operation in
                {'continue', 'next', 'stepIn', 'stepOut', 'stdin'})
            # This ledger outlives the runtime's bounded last-64-command view.
            # Claim-before-execute deliberately favors an explicit uncertain
            # result over accidentally repeating a non-idempotent debugger step.
            claimed = await self.worker.redis.eval("""
            local prior=redis.call('HGET',KEYS[1],ARGV[1])
            if prior then return prior end
            if redis.call('HLEN',KEYS[1])>=4096 then return '!full' end
            redis.call('HSET',KEYS[1],ARGV[1],ARGV[2])
            redis.call('EXPIRE',KEYS[1],2100)
            return ''
            """, 1, key('debug', 'commands', session.id), request.commandId,
                encode({'hash': digest(body), 'status': 'claimed'}))
            if claimed:
                if claimed == '!full':
                    raise DebugError('DEBUG_COMMAND_LIMIT', 429)
                receipt = json.loads(claimed)
                if receipt['hash'] != digest(body):
                    raise DebugError('DEBUG_COMMAND_ID_CONFLICT')
                if receipt['status'] == 'claimed':
                    raise DebugError('DEBUG_STATUS_UNCERTAIN', 409)
                if receipt['status'] == 'rejected':
                    raise DebugError(receipt['error'], receipt['httpStatus'])
                return session.snapshot()
            try:
                result = await self.runtime.command(session.id, user, request)
            except DebugError as error:
                await self.worker.redis.hset(key('debug', 'commands', session.id), request.commandId,
                    encode({'hash': digest(body), 'status': 'rejected', 'error': error.code, 'httpStatus': error.status}))
                raise
            await self.worker.redis.hset(key('debug', 'commands', session.id), request.commandId,
                encode({'hash': digest(body), 'status': 'accepted'}))
            return result
        if operation in {'stop', 'pause'}:
            request = Control(**body)
            if operation == 'pause':
                await self.runtime.authorizer.check(session, actor)
            return await self.runtime.control(session.id, user, request.sessionEpoch, operation)
        if operation == 'cancel':
            request = Cancel(**body)
            return await self.runtime.cancel(session.id, user, request.sessionEpoch, request.ticketId)
        raise DebugError('DEBUG_UNSUPPORTED_COMMAND', 400)

    async def close(self):
        if self.mirror_task:
            self.mirror_task.cancel()
            await asyncio.gather(self.mirror_task, return_exceptions=True)
        if self.runtime and self.runtime_started:
            await self.runtime.close()
            await self.flush_events()
        if self.resolver:
            await self.resolver.close()
        if self.lock:
            self.lock.__exit__(None, None, None)
