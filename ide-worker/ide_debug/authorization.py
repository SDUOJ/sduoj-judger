"""Recheck the frozen execution context; never extend session lifetime by polling."""

import time
from types import SimpleNamespace

from ide_intelligence.models import IdeContext
from .profiles import DebugError, digest


def specification_hash(template, prefix, parameters):
    return digest({"template": template, "prefix": prefix, "parameters": parameters or {}})


class SessionAuthorizer:
    # Only inspection may reuse a very recent positive decision. Every actual
    # start/resume is checked again after admission, even after a long queue.
    inspection_seconds = 2.0

    def __init__(self, resolver):
        self.resolver = resolver

    async def check(self, session, actor=None, fresh=False):
        if actor is not None:
            if actor["userId"] != session.user:
                raise DebugError("DEBUG_SESSION_NOT_FOUND", 404)
            session.authorization_actor = dict(actor)
        async with session.authorization_lock:
            actor = session.authorization_actor
            if not actor:
                raise DebugError("DEBUG_AUTHORIZATION_UNAVAILABLE", 503)
            identity = digest(actor)
            if (not fresh and identity == session.authorization_identity
                    and time.monotonic() < session.authorization_until):
                return
            session.authorization_until = 0
            request = SimpleNamespace(
                judgeTemplateId=session.profile.template_id,
                problemCode=session.scope["problemCode"],
                context=IdeContext(**session.scope["context"]),
            )
            resolved = await self.resolver.resolve(request, actor)
            if specification_hash(resolved["template"], resolved["sourcePrefix"],
                                  resolved.get("parameters")) != session.authorization_hash:
                raise DebugError("DEBUG_CONTEXT_CHANGED", 403)
            session.authorization_identity = identity
            session.authorization_until = min(
                time.monotonic() + self.inspection_seconds,
                session.idle_at, session.hard_at,
            )
