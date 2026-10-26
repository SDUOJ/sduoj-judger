"""Event-driven bounded admission, session actors and immutable hard deadlines."""

import asyncio
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
import json
import math
import secrets
import time
from weakref import WeakValueDictionary
from .config import Policy, PAGE_SIZE, host_available
from .launcher import Sandbox
from .profiles import DebugError, Profile, digest
from .authorization import specification_hash
from .judge_compile import COMPILE_CODES

TERMINAL = {"terminated", "failed", "expired", "lost"}
RESUME = {"continue", "next", "stepIn", "stepOut"}
READ = {"threads", "stackTrace", "scopes", "variables"}


def validate_arguments(op, arguments):
    keys = {
        "continue": {"threadId"},
        "next": {"threadId"},
        "stepIn": {"threadId"},
        "stepOut": {"threadId"},
        "threads": set(),
        "stackTrace": {"threadId"},
        "scopes": {"frameId"},
        "variables": {"variablesReference", "start", "count"},
        "setBreakpoints": {"lines"},
        "stdin": {"text"},
        "watch": {"frameId", "expressions"},
    }
    if op not in keys or set(arguments) - keys[op]:
        raise DebugError("DEBUG_INVALID_ARGUMENTS", 400)
    result = dict(arguments)
    for key, value in result.items():
        if key == "expressions":
            from .watch import valid_path

            if (
                not isinstance(value, list)
                or not 1 <= len(value) <= 16
                or any(not valid_path(v) for v in value)
            ):
                raise DebugError("DEBUG_INVALID_WATCH", 400)
        elif key == "lines":
            if (
                not isinstance(value, list)
                or len(value) > 128
                or any(type(n) is not int or not 1 <= n <= 100000 for n in value)
            ):
                raise DebugError("DEBUG_INVALID_BREAKPOINTS", 400)
        elif key == "text":
            if (
                not isinstance(value, str)
                or len(value.encode()) > 65536
                or "\x00" in value
            ):
                raise DebugError("DEBUG_INVALID_INPUT", 400)
        elif type(value) is not int or not 0 <= value <= 2**53 - 1:
            raise DebugError("DEBUG_INVALID_ARGUMENTS", 400)
    if (
        op in ("scopes", "watch")
        and "frameId" not in result
        or op == "variables"
        and "variablesReference" not in result
    ):
        raise DebugError("DEBUG_INVALID_ARGUMENTS", 400)
    if (
        op == "setBreakpoints"
        and "lines" not in result
        or op == "stdin"
        and "text" not in result
    ):
        raise DebugError("DEBUG_INVALID_ARGUMENTS", 400)
    if op == "watch" and "expressions" not in result:
        raise DebugError("DEBUG_INVALID_WATCH", 400)
    if op == "variables":
        if not 1 <= result.get("count", 100) <= 100 or result.get("start", 0) > 100000:
            raise DebugError("DEBUG_INVALID_PAGE", 400)
        result.setdefault("count", 100)
    return result


@dataclass
class Session:
    id: str
    epoch: str
    user: int
    profile: Profile
    spec: dict
    create_hash: str
    create_command: str
    node: str
    idle_at: float
    state: str = "queued"
    version: int = 0
    stop: str = ""
    thread_id: int = 1
    started: float = 0
    started_wall: float = 0
    hard_at: float = math.inf
    grant: int = 0
    frozen: bool = False
    sandbox: object = None
    ticket: object = None
    events: deque = field(default_factory=deque)
    commands: OrderedDict = field(default_factory=OrderedDict)
    cursor: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    actor: asyncio.Lock = field(default_factory=asyncio.Lock)
    closing: bool = False
    cleanup_task: object = None
    output_bytes: int = 0
    stats: dict = field(default_factory=dict)
    reason: str = ""
    compiled: bool = False
    source_digest: str = ""
    scope: dict = field(default_factory=dict)
    execution_task: object = None
    run_until: float = math.inf
    run_watchdog: object = None
    run_generation: int = 0
    io_tasks: set = field(default_factory=set)
    open_hash: str = ""
    authorization_actor: dict = field(default_factory=dict)
    authorization_hash: str = ""
    authorization_identity: str = ""
    authorization_until: float = 0
    authorization_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def snapshot(self):
        now, wall = time.monotonic(), time.time()
        return {
            "sessionId": self.id,
            "sessionEpoch": self.epoch,
            "userId": self.user,
            "owner": self.node,
            "state": self.state,
            "stateVersion": self.version,
            "stopId": self.stop,
            "threadId": self.thread_id,
            "language": self.profile.language,
            "sourceName": self.profile.source,
            "sourceHash": self.create_hash,
            "sourceDigest": self.source_digest,
            "problemCode": self.scope.get("problemCode"),
            "context": self.scope.get("context"),
            "breakpoints": [
                n - self.spec.get("lineOffset", 0)
                for n in self.spec.get("breakpoints", [])
            ],
            "runLimitSeconds": self.profile.run_seconds,
            "sourceLineOffset": self.spec.get("lineOffset", 0),
            "templateId": self.profile.template_id,
            "templateHash": self.profile.template_hash,
            "artifactDigest": self.profile.artifact_digest,
            "startedAt": int(self.started_wall * 1000) if self.started else None,
            "hardExpiresAt": (
                int((self.started_wall + self.hard_at - self.started) * 1000)
                if self.started
                else None
            ),
            "idleExpiresAt": int((wall + max(0, self.idle_at - now)) * 1000),
            "ticket": self.ticket.view() if self.ticket else None,
            "cursor": self.cursor,
            "reason": self.reason,
            "resources": dict(self.stats),
            "busy": bool(self.ticket or self.actor.locked()),
            "commands": [
                {k: v for k, v in c.items() if k != "hash"}
                for c in list(self.commands.values())[-64:]
            ],
        }

    def emit(self, kind, body):
        if kind == "output":
            text = str(body.get("output", ""))
            remaining = max(0, 196608 - self.output_bytes)
            self.output_bytes += len(text.encode())
            if not remaining:
                return
            body = {
                "output": text.encode()[:remaining].decode(errors="replace"),
                "category": body.get("category", "stdout"),
                "truncated": self.output_bytes > 196608,
            }
        self.cursor += 1
        self.events.append({"cursor": self.cursor, "type": kind, "data": body})
        # authoritative snapshot always survives output eviction.
        while (
            len(self.events) > 256
            or sum(len(json.dumps(e)) for e in self.events) > 262144
        ):
            self.events.popleft()
        self.changed.set()


@dataclass
class Ticket:
    id: str
    session: Session
    command: str
    operation: str
    arguments: dict
    deadline: float
    queued: float
    reason: str = "resources"
    skips: int = 0
    released: bool = False

    def view(self):
        return {
            "ticketId": self.id,
            "commandId": self.command,
            "operation": self.operation,
            "queueReason": self.reason,
            "queueExpiresAt": int(
                (time.time() + max(0, self.deadline - time.monotonic())) * 1000
            ),
        }


class Runtime:
    def __init__(
        self, policy, store, manifest, factory=Sandbox, available=host_available,
        authorizer=None, identity_factory=None,
    ):
        self.policy, self.store, self.manifest, self.factory = (
            policy,
            store,
            manifest,
            factory,
        )
        self.available = available
        self.authorizer = authorizer
        self.identity_factory = identity_factory or (lambda: (secrets.token_hex(16), secrets.token_hex(16)))
        self.sessions, self.users = {}, {}
        self.user_locks = WeakValueDictionary()
        self.pollers, self.cleanup_tasks = {}, set()
        self.queue = deque()
        self.running = set()
        self.active = Counter()
        self.starting = Counter()
        self.metrics = Counter()
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        self.closed = False
        self.admitting = True
        self.incarnation = policy.node + "-" + secrets.token_hex(16)
        self.last_heartbeat = time.monotonic()

    async def start(self):
        if not await self.store.claim_node(self.incarnation):
            raise RuntimeError("Only one debug runtime may own this global budget")
        self.scheduler = asyncio.create_task(self.schedule(), name="debug-scheduler")
        self.reaper = asyncio.create_task(self.maintenance(), name="debug-maintenance")

    def view_metrics(self):
        live = [s for s in self.sessions.values() if s.grant]
        return {
            "counters": dict(self.metrics),
            "resident": len(live),
            "active": len(self.running),
            "queued": len(self.queue),
            "grantedBytes": sum(s.grant for s in live)
            + len(live) * self.policy.guardian_memory,
            "guardianReservedBytes": len(live) * self.policy.guardian_memory,
            "observedLeafBytes": sum(s.stats.get("memory", 0) for s in live),
            "observedLeafPids": sum(s.stats.get("pids", 0) for s in live),
            "admissionBudgetBytes": self.policy.budget - self.policy.reserve,
            "hardBytes": self.policy.hard,
            "admitting": self.admitting,
            "perLanguageActive": dict(self.active),
            "perLanguage": {
                lang: {
                    key[len(lang) + 1 :]: value
                    for key, value in self.metrics.items()
                    if key.startswith(lang + "_")
                }
                for lang in ("c", "cpp", "java", "python")
            },
        }

    def observe(self, language, stage, seconds):
        key = language + "_" + stage
        self.metrics[key + "_count"] += 1
        self.metrics[key + "_ms_total"] += int(seconds * 1000)
        for bound in (100, 300, 500, 1000, 5000, 15000, 120000):
            if seconds * 1000 <= bound:
                self.metrics[key + "_le_" + str(bound)] += 1

    async def create(self, user, body, template, prefix="", parameters=None, actor=None):
        lock = self.user_locks.get(user)
        if lock is None:
            lock = asyncio.Lock()
            self.user_locks[user] = lock
        # Finish ownership transfer even when the requesting HTTP client disconnects.
        task = asyncio.create_task(
            self.open_session(lock, user, body, template, prefix, parameters, actor)
        )
        self.cleanup_tasks.add(task)
        task.add_done_callback(self.cleanup_tasks.discard)
        return await asyncio.shield(task)

    async def open_session(self, lock, user, body, template, prefix, parameters, actor=None):
        profile = Profile.resolve(self.manifest, template, body.language, parameters)
        source = digest(
            {
                "code": prefix + body.code,
                "context": body.context.dict(),
                "problem": body.problemCode,
                "template": profile.template_hash,
                "artifact": profile.artifact_digest,
            }
        )
        request_hash = digest(body.dict())
        async with lock:
            if body.restoreOnly:
                if not body.resumeSessionId or not body.resumeSessionEpoch:
                    raise DebugError("DEBUG_RESUME_UNAVAILABLE", 410)
                session = await self.lookup(body.resumeSessionId, user)
                if (
                    session.epoch != body.resumeSessionEpoch
                    or session.source_digest != source
                    or session.state in TERMINAL
                    or session.closing
                    or time.monotonic() >= min(session.idle_at, session.hard_at)
                ):
                    raise DebugError("DEBUG_RESUME_UNAVAILABLE", 410)
                if self.authorizer:
                    await self.authorizer.check(session, actor, fresh=True)
                session.idle_at = min(
                    session.hard_at, time.monotonic() + self.policy.idle
                )
                if session.sandbox:
                    await session.sandbox.guard("touch")
                await self.store.save(session)
                return session.snapshot()
            receipt = await self.store.open_receipt(user, body.commandId)
            if receipt:
                if receipt["hash"] != request_hash:
                    raise DebugError("DEBUG_COMMAND_ID_CONFLICT")
                return (await self.lookup(receipt["sessionId"], user)).snapshot()
            previous_id = self.users.get(user)
            previous = self.sessions.get(previous_id)
            if previous and previous.create_command == body.commandId:
                if previous.open_hash != request_hash:
                    raise DebugError("DEBUG_COMMAND_ID_CONFLICT")
                return previous.snapshot()
            if previous and body.replaceExisting:
                await self.terminate(previous, "DEBUG_REPLACED")
                if previous.grant or previous.state != "terminated":
                    raise DebugError("DEBUG_CLEANUP_UNCONFIRMED", 503)
            result = await self._create(user, body, template, prefix, parameters, actor)
            self.sessions[result["sessionId"]].open_hash = request_hash
            await self.store.save_open_receipt(
                user, body.commandId, request_hash, result["sessionId"]
            )
            return result

    async def _create(self, user, body, template, prefix="", parameters=None, actor=None):
        profile = Profile.resolve(self.manifest, template, body.language, parameters)
        offset = prefix.count("\n")
        spec = {
            "code": prefix + body.code,
            "input": body.input,
            "lineOffset": offset,
            "breakpoints": sorted(set(n + offset for n in body.breakpoints)),
        }
        fingerprint = digest(
            {
                "spec": spec,
                "template": profile.template_hash,
                "language": profile.language,
                "context": body.context.dict(),
                "problem": body.problemCode,
                "artifact": profile.artifact_digest,
                "runOptions": profile.java_options,
            }
        )
        async with self.lock:
            if not self.admitting or self.closed:
                raise DebugError("DEBUG_UNAVAILABLE", 503)
            old = self.users.get(user)
            if old:
                # Replays are matched by commandId in open_session. Equal source
                # does not authorize returning a different gateway allocation.
                raise DebugError("DEBUG_USER_ALREADY_HAS_SESSION")
            if len(self.queue) >= self.policy.queue:
                raise DebugError("DEBUG_QUEUE_FULL", 429)
            session_id, session_epoch = self.identity_factory()
            other = await self.store.claim_user(
                user,
                session_id,
                math.ceil(self.policy.lifetime + self.policy.wait + 60),
            )
            if other:
                # Do not reconstruct heap or start another program on owner loss.
                value = await self.store.get(other, user)
                raise DebugError(
                    (
                        "DEBUG_SESSION_OWNED_ELSEWHERE"
                        if value.get("owner") != self.policy.node
                        else "DEBUG_SESSION_LOST"
                    ),
                    409,
                )
            now = time.monotonic()
            session = Session(
                session_id,
                session_epoch,
                user,
                profile,
                spec,
                fingerprint,
                body.commandId,
                self.policy.node,
                now + self.policy.idle,
            )
            self.sessions[session.id], self.users[user] = session, session.id
            session.source_digest = digest(
                {
                    "code": prefix + body.code,
                    "context": body.context.dict(),
                    "problem": body.problemCode,
                    "template": profile.template_hash,
                    "artifact": profile.artifact_digest,
                }
            )
            session.scope = {
                "problemCode": body.problemCode,
                "context": body.context.dict(),
            }
            session.authorization_actor = dict(actor or {})
            session.authorization_hash = specification_hash(template, prefix, parameters)
            session.commands[body.commandId] = {
                "commandId": body.commandId,
                "hash": fingerprint,
                "status": "queued",
                "operation": "start",
            }
            try:
                await self.store.save_spec(session, spec)
                await self.store.save(session)
                # Publish the runnable ticket only after persistence succeeds.
                # There must be no await between enqueue and returning: otherwise
                # a failed save can discard ownership of an already live jail.
                self.enqueue(session, body.commandId, "start", {})
            except BaseException:
                self.sessions.pop(session.id, None)
                self.users.pop(user, None)
                self.queue = deque(t for t in self.queue if t.session is not session)
                await self.store.release_user(user, session.id)
                raise
            return session.snapshot()

    async def live_input(self, session, command_id, args):
        command = session.commands[command_id]
        try:
            result = await session.sandbox.request("stdin", args)
            command.update(status="completed", result=result)
            if not session.closing:
                session.idle_at = min(
                    session.hard_at, time.monotonic() + self.policy.idle
                )
                await session.sandbox.guard("touch")
                session.emit("command", command.copy())
                self.trim_commands(session)
                await self.store.save(session)
        except asyncio.CancelledError:
            command.update(status="unknown", error="DEBUG_COMMAND_INTERRUPTED")
            raise
        except Exception:
            command.update(status="unknown", error="DEBUG_OPERATION_FAILED")
            if not session.closing:
                await self.terminate(session, "DEBUG_OPERATION_FAILED")

    def enqueue(self, session, command, operation, arguments):
        if len(self.queue) >= self.policy.queue:
            raise DebugError("DEBUG_QUEUE_FULL", 429)
        now = time.monotonic()
        ticket = Ticket(
            secrets.token_hex(16),
            session,
            command,
            operation,
            arguments,
            min(now + self.policy.wait, session.idle_at, session.hard_at),
            now,
        )
        session.ticket = ticket
        self.queue.append(ticket)
        session.emit("queued", ticket.view())
        self.metrics["queued_total"] += 1
        self.wake.set()

    async def lookup(self, session_id, user):
        session = self.sessions.get(session_id)
        if session:
            if session.user != user:
                raise DebugError("DEBUG_SESSION_NOT_FOUND", 404)
            return session
        remote = await self.store.get(session_id, user)
        raise DebugError(
            (
                "DEBUG_SESSION_LOST"
                if remote["owner"] == self.policy.node
                else "DEBUG_SESSION_OWNED_ELSEWHERE"
            ),
            410,
        )

    async def command(self, session_id, user, body):
        session = await self.lookup(session_id, user)
        args = validate_arguments(body.operation, body.arguments)
        if body.operation == "setBreakpoints":
            args["lines"] = [
                n + session.spec.get("lineOffset", 0) for n in args["lines"]
            ]
        fingerprint = digest(body.dict())
        async with self.lock:
            if body.sessionEpoch != session.epoch:
                raise DebugError("DEBUG_EPOCH_MISMATCH")
            previous = session.commands.get(body.commandId)
            if previous:
                if previous["hash"] != fingerprint:
                    raise DebugError("DEBUG_COMMAND_ID_CONFLICT")
                self.metrics["deduplicated_total"] += 1
                return session.snapshot()
            if session.state in TERMINAL or session.closing:
                raise DebugError("DEBUG_SESSION_ENDED", 410)
            if time.monotonic() >= min(session.idle_at, session.hard_at):
                raise DebugError("DEBUG_SESSION_EXPIRED", 410)
            if (
                body.operation == "stdin"
                and session.state == "running"
                and session.sandbox
                and not session.frozen
            ):
                session.commands[body.commandId] = {
                    "commandId": body.commandId,
                    "hash": fingerprint,
                    "status": "dispatched",
                    "operation": "stdin",
                }
                task = asyncio.create_task(
                    self.live_input(session, body.commandId, args)
                )
                session.io_tasks.add(task)
                task.add_done_callback(session.io_tasks.discard)
                return session.snapshot()
            if body.expectedStateVersion != session.version:
                raise DebugError("DEBUG_STATE_CONFLICT")
            if session.ticket or session.actor.locked():
                raise DebugError("DEBUG_COMMAND_IN_FLIGHT")
            if session.state != "stopped" or not session.frozen:
                raise DebugError("DEBUG_NOT_STOPPED")
            if body.stopId != session.stop:
                raise DebugError("DEBUG_STALE_STOP")
            if not self.admitting:
                raise DebugError("DEBUG_UNAVAILABLE", 503)
            if len(self.queue) >= self.policy.queue:
                raise DebugError("DEBUG_QUEUE_FULL", 429)
            session.version += 1
            session.idle_at = min(session.hard_at, time.monotonic() + self.policy.idle)
            if session.sandbox:
                await session.sandbox.guard("touch")
            session.commands[body.commandId] = {
                "commandId": body.commandId,
                "hash": fingerprint,
                "status": "queued",
                "operation": body.operation,
            }
            self.trim_commands(session)
            self.enqueue(session, body.commandId, body.operation, args)
            await self.store.save(session)
            return session.snapshot()

    @staticmethod
    def trim_commands(session):
        while len(session.commands) > 64:
            session.commands.popitem(last=False)
        # Keep dedup hashes/status for 64 commands, but cap retained result bytes.
        size = 0
        for command in reversed(list(session.commands.values())):
            size += len(json.dumps(command))
            if size > 262144:
                command.pop("result", None)

    def resources(self, ticket):
        session, p = ticket.session, ticket.session.profile
        start = ticket.operation == "start"
        target = p.startup if start else max(session.grant, p.hard)
        delta = max(0, target - session.grant) + (
            self.policy.guardian_memory if start else 0
        )
        live = [s for s in self.sessions.values() if s.grant]
        if len(self.running) >= self.policy.active or self.active[p.language] >= min(
            [p.active]
            + [s.profile.active for s in live if s.profile.language == p.language]
        ):
            return False, "execution"
        if start and (
            len(live) >= self.policy.resident
            or self.starting[p.language]
            >= min(
                [p.starting]
                + [s.profile.starting for s in live if s.profile.language == p.language]
            )
        ):
            return False, (
                "resident" if len(live) >= self.policy.resident else "cold_start"
            )
        if (
            sum(s.grant + self.policy.guardian_memory for s in live)
            + delta
            + self.policy.reserve
            > self.policy.budget
        ):
            return False, "memory"
        if (
            sum(s.profile.pids + 4 for s in live) + (p.pids + 4 if start else 0)
            > self.policy.pid_budget
        ):
            return False, "pids"
        if self.available() < self.policy.host_floor + delta:
            return False, "host_memory"
        return True, ""

    async def schedule(self):
        try:
            while not self.closed:
                await self.wake.wait()
                self.wake.clear()
                now = time.monotonic()
                # Existing scenes first; within a class retain age order. Every
                # fourth dispatch considers starts first to avoid starvation.
                ordered = sorted(
                    list(self.queue),
                    key=lambda t: (
                        (t.operation == "start", t.queued)
                        if self.metrics["dispatched_total"] % 4
                        else (t.queued,)
                    ),
                )
                for ticket in ordered:
                    session = ticket.session
                    if ticket not in self.queue:
                        continue
                    if (
                        ticket.deadline <= now
                        or session.state in TERMINAL
                        or session.closing
                    ):
                        self.queue.remove(ticket)
                        session.ticket = None
                        result = session.commands[ticket.command]
                        result.update(
                            status="failed", error="DEBUG_RESOURCE_WAIT_TIMEOUT"
                        )
                        session.emit("command", result.copy())
                        self.metrics["queue_timeout_total"] += 1
                        await self.store.save(session)
                        if ticket.operation == "start":
                            await self.terminate(session, "DEBUG_RESOURCE_WAIT_TIMEOUT")
                        continue
                    if not self.admitting:
                        continue
                    allowed, reason = self.resources(ticket)
                    if not allowed:
                        ticket.reason = reason
                        ticket.skips += 1
                        # After enough skips/age, accumulate memory instead of
                        # dispatching younger growth requests forever.
                        if (
                            ticket.skips >= 16
                            and now - ticket.queued >= 10
                            and reason == "memory"
                        ):
                            break
                        continue
                    self.queue.remove(ticket)
                    session.ticket = None
                    session.grant = (
                        session.profile.startup
                        if ticket.operation == "start"
                        else max(session.grant, session.profile.hard)
                    )
                    self.active[session.profile.language] += 1
                    if ticket.operation == "start":
                        self.starting[session.profile.language] += 1
                    self.metrics["dispatched_total"] += 1
                    self.metrics["queue_wait_ms_total"] += int(
                        (now - ticket.queued) * 1000
                    )
                    self.observe(session.profile.language, "queue", now - ticket.queued)
                    task = asyncio.create_task(
                        self.execute(ticket), name="debug-" + ticket.operation
                    )
                    session.execution_task = task
                    self.running.add(task)
                    task.add_done_callback(
                        lambda done, item=ticket: (
                            self.release_execution(item),
                            self.running.discard(done),
                            self.wake.set(),
                        )
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            self.admitting = False
            self.metrics["scheduler_failure_total"] += 1
            self.wake.set()

    def adapter_event(self, session, kind, body):
        if session.closing or session.state in TERMINAL:
            return
        if kind in ("compiled", "stopped", "running"):
            session.compiled = True
        elif kind in ("failed", "guardianLost", "terminated") and not session.compiled:
            # A compiler/jail crash or cgroup kill before completion must be a
            # visible compile-stage failure, not an unexplained normal finish.
            kind = "compileError"
            body = {"code": "DEBUG_COMPILE_SANDBOX_FAILED", "output": ""}
        if kind == "stopped":
            self.guard_run(session, False)
            session.run_until = math.inf
            if session.run_watchdog:
                session.run_watchdog.cancel()
                session.run_watchdog = None
            session.state = "stopped"
            session.stop = secrets.token_hex(12)
            session.thread_id = body.get("threadId", session.thread_id)
            session.version += 1
            session.stopped.set()
            body = dict(body, stopId=session.stop)
        elif kind == "running":
            if session.run_until == math.inf:
                self.arm_run(session)
            session.state = "running"
            session.stop = ""
            session.frozen = False
            session.version += 1
            session.stopped.clear()
        elif kind in (
            "terminated",
            "compileError",
            "failed",
            "guardianLost",
            "guardianCpuLimit",
            "runTimeout",
        ):
            session.stopped.set()
            # A single close owner handles every terminal callback.
            if not session.closing:
                session.closing = True
                reason = (
                    "DEBUG_RUN_TIMEOUT"
                    if kind == "runTimeout" or time.monotonic() >= session.run_until
                    else "DEBUG_" + kind.upper()
                )
                if kind == "compileError":
                    reason = body.get("code")
                    if not isinstance(reason, str) or reason not in COMPILE_CODES:
                        reason = "DEBUG_COMPILE_FAILED"
                elif kind == "guardianCpuLimit":
                    reason = "DEBUG_GUARDIAN_CPU_LIMIT"
                task = asyncio.create_task(
                    self.terminate(session, reason, already_closing=True)
                )
                self.cleanup_tasks.add(task)
                task.add_done_callback(self.cleanup_tasks.discard)
        if kind == "compiled":
            self.observe(
                session.profile.language, "compile", time.monotonic() - session.started
            )
        session.emit(kind, body)

    def guard_run(self, session, active):
        if not session.sandbox:
            return
        generation = session.run_generation

        async def send():
            try:
                await session.sandbox.guard(
                    "run" if active else "run-end",
                    generation=generation,
                    **(
                        {
                            "seconds": session.profile.run_seconds
                            or self.policy.run_slice
                        }
                        if active
                        else {}
                    )
                )
            except Exception:
                if not session.closing:
                    await self.terminate(session, "DEBUG_GUARDIAN_FAILED")

        task = asyncio.create_task(send())
        self.cleanup_tasks.add(task)
        task.add_done_callback(self.cleanup_tasks.discard)

    def arm_run(self, session):
        limit = session.profile.run_seconds or self.policy.run_slice
        session.run_generation += 1
        session.run_until = time.monotonic() + limit
        self.guard_run(session, True)
        if session.run_watchdog:
            session.run_watchdog.cancel()

        async def expire(deadline):
            await asyncio.sleep(max(0, deadline - time.monotonic()))
            if (
                session.run_until == deadline
                and not session.closing
                and session.state not in TERMINAL
            ):
                self.metrics["run_timeout_total"] += 1
                await self.terminate(session, "DEBUG_RUN_TIMEOUT")

        session.run_watchdog = asyncio.create_task(expire(session.run_until))

    def release_execution(self, ticket):
        if ticket.released:
            return
        ticket.released = True
        self.active[ticket.session.profile.language] -= 1
        if ticket.operation == "start":
            self.starting[ticket.session.profile.language] -= 1
        self.wake.set()

    async def freeze(self, session):
        await session.sandbox.guard("freeze")
        session.frozen = True
        stats = await session.sandbox.guard("stats")
        session.stats = stats
        p = session.profile
        target = min(
            p.hard,
            max(
                p.floor, math.ceil((stats["memory"] + p.margin) / PAGE_SIZE) * PAGE_SIZE
            ),
        )
        if stats["memory"] + p.margin > target:
            # Startup retained more memory than normal runtime H: never lower
            # below real usage merely to fit a nominal resident allowance.
            target = session.grant
        if target < session.grant:
            try:
                confirmed = await session.sandbox.guard("limit", value=target)
                if confirmed["memory"] > target:
                    raise RuntimeError("Unsafe shrink")
            except Exception:
                self.metrics["shrink_failed_total"] += 1
                # Guardian errors are fail-stop; do not pretend the scene lives.
                raise
            session.grant = target
            self.metrics["shrink_total"] += 1
        self.metrics["frozen_total"] += 1
        self.wake.set()

    async def execute(self, ticket):
        session = ticket.session
        command = session.commands[ticket.command]
        began = time.monotonic()
        try:
            async with session.actor:
                if session.closing or session.state in TERMINAL:
                    return
                if self.authorizer:
                    await self.authorizer.check(
                        session, fresh=ticket.operation == "start" or ticket.operation in RESUME
                    )
                command["status"] = "dispatched"
                await self.store.save(session)
                if ticket.operation == "start":
                    session.started = time.monotonic()
                    session.started_wall = time.time()
                    session.hard_at = session.started + self.policy.lifetime
                    session.idle_at = min(
                        session.hard_at, session.started + self.policy.idle
                    )
                    session.state = "starting"
                    session.sandbox = self.factory(
                        session.id,
                        session.profile,
                        self.policy,
                        lambda kind, body: self.adapter_event(session, kind, body),
                    )
                    start_task = asyncio.create_task(
                        session.sandbox.start(session.spec)
                    )
                    try:
                        await asyncio.shield(start_task)
                    except asyncio.CancelledError:
                        await asyncio.gather(start_task, return_exceptions=True)
                        raise
                    self.metrics["started_total"] += 1
                    await asyncio.wait_for(
                        session.stopped.wait(),
                        min(
                            session.profile.compile_seconds + 15,
                            max(0.01, session.hard_at - time.monotonic()),
                        ),
                    )
                    result = {}
                else:
                    if not session.frozen or time.monotonic() >= min(
                        session.idle_at, session.hard_at
                    ):
                        raise DebugError("DEBUG_SESSION_EXPIRED")
                    await session.sandbox.guard("limit", value=session.grant)
                    await session.sandbox.guard("thaw")
                    session.frozen = False
                    if ticket.operation in RESUME:
                        session.stop = ""
                        session.stopped.clear()
                        session.state = "running"
                        session.version += 1
                        self.arm_run(session)
                    result = await session.sandbox.request(
                        ticket.operation, ticket.arguments
                    )
                    if ticket.operation == "stackTrace":
                        for frame in result.get("stackFrames", []):
                            source = frame.get("source")
                            path = (
                                source.get("path", "")
                                if isinstance(source, dict)
                                else str(source)
                            )
                            frame["editableSource"] = (
                                path == "/work/" + session.profile.source
                            )
                            if frame["editableSource"]:
                                frame["line"] = max(
                                    0,
                                    frame.get("line", 0)
                                    - session.spec.get("lineOffset", 0),
                                )
                            frame["source"] = {
                                "name": (
                                    session.profile.source
                                    if frame["editableSource"]
                                    else "<runtime>"
                                )
                            }
                    if ticket.operation in RESUME:
                        try:
                            await asyncio.wait_for(
                                session.stopped.wait(),
                                max(0.001, session.run_until - time.monotonic()),
                            )
                        except asyncio.TimeoutError:
                            raise DebugError("DEBUG_RUN_TIMEOUT")
                if session.closing or session.state in TERMINAL:
                    command.update(status="completed", result={})
                else:
                    await session.sandbox.guard(
                        "run-end", generation=session.run_generation
                    )
                    await self.freeze(session)
                    if ticket.operation == "setBreakpoints":
                        session.spec["breakpoints"] = list(ticket.arguments["lines"])
                    command.update(status="completed", result=result)
                    session.emit("command", command.copy())
                    self.trim_commands(session)
                    await self.store.save(session)
                    self.metrics["completed_total"] += 1
                    if result and any(result.values()):
                        self.metrics[
                            session.profile.language + "_effective_results_total"
                        ] += 1
        except asyncio.CancelledError:
            command.update(status="unknown", error="DEBUG_COMMAND_INTERRUPTED")
            raise
        except Exception as error:
            command.update(
                status="unknown",
                error=(
                    error.code
                    if isinstance(error, DebugError)
                    else "DEBUG_OPERATION_FAILED"
                ),
            )
            self.metrics["operation_failed_total"] += 1
            await self.terminate(session, command["error"])
        finally:
            self.release_execution(ticket)
            self.metrics["operation_ms_total"] += int((time.monotonic() - began) * 1000)
            self.observe(
                session.profile.language, ticket.operation, time.monotonic() - began
            )
            self.wake.set()

    async def terminate(self, session, reason, already_closing=False):
        if session.cleanup_task is None:
            session.closing = True
            session.cleanup_task = asyncio.create_task(
                self._terminate(session, reason, asyncio.current_task())
            )
            self.cleanup_tasks.add(session.cleanup_task)
            session.cleanup_task.add_done_callback(self.cleanup_tasks.discard)
        return await asyncio.shield(session.cleanup_task)

    async def _terminate(self, session, reason, initiator=None):
        if session.state in TERMINAL and not session.grant:
            return
        cleanup_started = time.monotonic()
        session.reason = reason
        if session.run_watchdog and session.run_watchdog is not initiator:
            session.run_watchdog.cancel()
        execution = session.execution_task
        if execution and execution is not initiator and not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        io = [
            task
            for task in session.io_tasks
            if task is not initiator and not task.done()
        ]
        for task in io:
            task.cancel()
        if io:
            await asyncio.gather(*io, return_exceptions=True)
        self.queue = deque(t for t in self.queue if t.session is not session)
        if session.ticket:
            session.commands[session.ticket.command].update(
                status="failed", error=reason
            )
        session.ticket = None
        clean = await session.sandbox.close() if session.sandbox else True
        session.state = "terminated" if clean else "lost"
        session.version += 1
        session.stop = ""
        session.stopped.set()
        if clean:
            session.grant = 0
            self.users.pop(session.user, None)
            session.emit("terminated", {"reason": reason})
            await self.store.terminal(session)
            session.spec.clear()
        else:
            # Quarantine both grant and unique-user ownership until an operator
            # proves that no process survived. Do not recycle an uncertain slot.
            session.reason = "DEBUG_CLEANUP_UNCONFIRMED"
            self.admitting = False
            self.metrics["cleanup_unconfirmed_total"] += 1
            session.emit("lost", {"reason": "DEBUG_CLEANUP_UNCONFIRMED"})
            await self.store.save(session)
        self.metrics["terminated_total"] += 1
        self.observe(
            session.profile.language, "cleanup", time.monotonic() - cleanup_started
        )
        self.wake.set()

    async def control(self, session_id, user, epoch, operation):
        session = await self.lookup(session_id, user)
        if epoch != session.epoch:
            raise DebugError("DEBUG_EPOCH_MISMATCH")
        if operation == "stop":
            await self.terminate(session, "DEBUG_USER_STOP")
        elif (
            operation == "pause"
            and session.sandbox
            and not session.frozen
            and not session.closing
        ):
            await session.sandbox.request("pause", {})
        return session.snapshot()

    async def cancel(self, session_id, user, epoch, ticket_id):
        session = await self.lookup(session_id, user)
        async with self.lock:
            if session.epoch != epoch:
                raise DebugError("DEBUG_EPOCH_MISMATCH")
            ticket = session.ticket
            if not ticket or ticket.id != ticket_id:
                raise DebugError("DEBUG_TICKET_ALREADY_DISPATCHED")
            self.queue.remove(ticket)
            session.ticket = None
            session.commands[ticket.command].update(
                status="failed", error="DEBUG_CANCELLED"
            )
            session.emit("command", session.commands[ticket.command].copy())
            await self.store.save(session)
        if ticket.operation == "start":
            await self.terminate(session, "DEBUG_CANCELLED")
        self.wake.set()
        return session.snapshot()

    async def poll(self, session_id, user, cursor, wait):
        session = await self.lookup(session_id, user)
        if session.cursor <= cursor and wait and session.state not in TERMINAL:
            session.changed.clear()
            if session.cursor <= cursor:
                try:
                    await asyncio.wait_for(session.changed.wait(), wait)
                except asyncio.TimeoutError:
                    pass
        events = [e for e in session.events if e["cursor"] > cursor]
        return {
            "snapshot": session.snapshot(),
            "events": events,
            "truncated": bool(
                session.events and cursor < session.events[0]["cursor"] - 1
            ),
        }

    async def maintenance(self):
        try:
            while not self.closed:
                await asyncio.sleep(0.5)
                now = time.monotonic()
                self.wake.set()  # one sampler corrects host-pressure changes/queue deadlines
                if now - self.last_heartbeat >= 4:
                    if not await self.store.renew_node(self.incarnation):
                        raise RuntimeError("Debug ownership lease lost")
                    self.last_heartbeat = now
                    live = [
                        s
                        for s in self.sessions.values()
                        if s.sandbox and not s.closing and s.state not in TERMINAL
                    ]
                    guardians = [s.sandbox.guard("heartbeat") for s in live]
                    if guardians:
                        results = await asyncio.gather(
                            *guardians, return_exceptions=True
                        )
                        for session, result in zip(live, results):
                            if not isinstance(result, BaseException):
                                session.stats = result
                        if any(isinstance(r, BaseException) for r in results):
                            self.metrics["guardian_heartbeat_failed_total"] += 1
                for session in list(self.sessions.values()):
                    if (
                        not session.closing
                        and session.state not in TERMINAL
                        and now >= min(session.idle_at, session.hard_at)
                    ):
                        reason = (
                            "DEBUG_SESSION_MAX_AGE"
                            if now >= session.hard_at
                            else "DEBUG_SESSION_IDLE_EXPIRED"
                        )
                        task = asyncio.create_task(self.terminate(session, reason))
                        self.cleanup_tasks.add(task)
                        task.add_done_callback(self.cleanup_tasks.discard)
                    if (
                        session.state in TERMINAL
                        and not session.grant
                        and now - session.idle_at > 300
                    ):
                        self.sessions.pop(session.id, None)
        except asyncio.CancelledError:
            pass
        except Exception:
            self.admitting = False
            self.metrics["lease_lost_total"] += 1
            # Guardian heartbeat now stops; independent 12-second watchdog also
            # kills everything if API/Redis cleanup cannot complete.
            await asyncio.gather(
                *(
                    self.terminate(s, "DEBUG_OWNER_LOST")
                    for s in list(self.sessions.values())
                ),
                return_exceptions=True
            )

    async def close(self):
        self.closed = True
        self.admitting = False
        self.wake.set()
        self.scheduler.cancel()
        self.reaper.cancel()
        for task in list(self.running):
            task.cancel()
        await asyncio.gather(
            self.scheduler, self.reaper, *list(self.running), return_exceptions=True
        )
        await asyncio.gather(
            *(
                self.terminate(s, "DEBUG_SERVICE_STOP")
                for s in list(self.sessions.values())
            ),
            return_exceptions=True
        )
        await asyncio.gather(
            *list(getattr(self, "cleanup_tasks", set())), return_exceptions=True
        )
        if not any(s.grant for s in self.sessions.values()):
            await self.store.release_node(self.incarnation)
