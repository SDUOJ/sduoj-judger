import asyncio
import json
import os

import httpx
import pytest

from sduoj_ide_worker.nacos import Nacos, settings
from sduoj_ide_worker.service import Service


def configuration(**extra):
    return json.dumps({'schemaVersion': 1, 'environment': {
        'SDUOJ_IDE_REDIS_URL': '${AUTOLAB_REDIS_URL}',
        'SDUOJ_IDE_PREFIX': 'ide:test:', 'AUTOLAB_DEBUG_ENABLED': 1, **extra}})


def test_configuration_is_strict_and_expands_secrets_locally():
    env = {'AUTOLAB_REDIS_URL': 'redis://:private@autolab-redis:6379/14'}
    assert settings(configuration(), env)['SDUOJ_IDE_REDIS_URL'] == env['AUTOLAB_REDIS_URL']
    for raw in [configuration(PATH='/evil'), configuration(AUTOLAB_DEBUG_ENABLED=0),
                configuration(SDUOJ_IDE_PREFIX='bad*'), configuration(SDUOJ_IDE_REDIS_URL='http://bad')]:
        with pytest.raises(ValueError):
            settings(raw, env)
    with pytest.raises(ValueError):
        settings(configuration(), {})


@pytest.mark.asyncio
async def test_nacos_config_registration_beat_delete(monkeypatch):
    monkeypatch.setenv('NACOS_IP', '127.0.0.1')
    monkeypatch.setenv('AUTOLAB_REDIS_URL', 'redis://localhost/14')
    seen = []
    async def handler(request):
        seen.append(request)
        if request.url.path.endswith('/cs/configs'):
            return httpx.Response(200, text=configuration())
        if request.url.path.endswith('/beat'):
            return httpx.Response(200, json={'code': 10200})
        return httpx.Response(200, text='ok')
    client = Nacos(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await client.configuration()
        await client.register('test-worker', 9086)
        await client.beat()
        await client.deregister()
        assert [r.method for r in seen] == ['GET', 'POST', 'PUT', 'DELETE']
        assert seen[0].url.params['tenant'] == 'dev'
        assert seen[1].url.params['namespaceId'] == 'dev'
        metadata = seen[1].url.params['metadata']
        assert 'redis' not in metadata and 'private' not in metadata
    finally:
        await client.close()


class Child:
    def __init__(self, role, language=None, **kw):
        self.role, self.language, self.kw = role, language, kw
        self.ready, self.closed = asyncio.Event(), asyncio.Event()
        self.cleaned = False
    def registration(self):
        return {'role': self.role, 'language': self.language}
    async def run(self, **kw):
        self.ready.set()
        await self.closed.wait()
        self.cleaned = True


class Discovery:
    instance = None
    def __init__(self, fail=False):
        self.fail, self.removed, self.closed = fail, False, False
    async def register(self, *args):
        self.instance = args
        if self.fail:
            raise RuntimeError('registration failed')
    async def beat(self):
        pass
    async def deregister(self):
        self.removed = True
    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [False, True])
async def test_supervisor_registers_one_service_and_cleans_all_components(monkeypatch, failure):
    monkeypatch.setenv('SDUOJ_IDE_HEALTH_PORT', '0')
    discovery = Discovery(failure)
    service = Service(discovery, Child)
    task = asyncio.create_task(service.run(manage_signals=False))
    if failure:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(task, 2)
    else:
        async def wait_ready():
            while not service.ready:
                await asyncio.sleep(.001)
        await asyncio.wait_for(wait_ready(), 2)
        assert len(service.children) == 5
        assert len({c.kw['worker_id'] for c in service.children}) == 5
        service.closed.set()
        await asyncio.wait_for(task, 2)
    assert discovery.removed and discovery.closed
    assert all(c.cleaned for c in service.children)
    assert not service.ready


@pytest.mark.asyncio
async def test_nacos_expired_token_reauthenticates_once(monkeypatch):
    monkeypatch.setenv('NACOS_USERNAME', 'test-user')
    monkeypatch.setenv('NACOS_PASSWORD', 'test-password')
    monkeypatch.setenv('AUTOLAB_REDIS_URL', 'redis://localhost/14')
    counts = {'login': 0, 'config': 0}
    async def handler(request):
        if request.url.path.endswith('/auth/login'):
            counts['login'] += 1
            return httpx.Response(200, json={'accessToken': str(counts['login'])})
        counts['config'] += 1
        if counts['config'] == 1:
            return httpx.Response(403)
        return httpx.Response(200, text=configuration())
    client = Nacos(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await client.configuration()
        assert counts == {'login': 2, 'config': 2}
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('denied', [True, False])
async def test_debug_authorization_retry_never_bypasses_denial(monkeypatch, denied):
    from ide_debug.resolver import Resolver
    from ide_debug.profiles import DebugError
    from tests.test_debug_runtime import body
    monkeypatch.setenv('AUTOLAB_DEBUG_RESOLVER_URL', 'http://problem/internal/ide/debug/resolve')
    monkeypatch.setenv('AUTOLAB_IDE_TOOLCHAIN_TOKEN', 'test-token')
    count = 0
    async def handler(request):
        nonlocal count
        count += 1
        if denied:
            return httpx.Response(403)
        if count == 1:
            raise httpx.RemoteProtocolError('stale connection')
        return httpx.Response(200, json={'template': {'id': '19'}, 'sourcePrefix': ''})
    resolver = Resolver()
    await resolver.client.aclose()
    resolver.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        if denied:
            with pytest.raises(DebugError, match='DEBUG_CONTEXT_FORBIDDEN'):
                await resolver.resolve(body(), {'userId': '7'})
            assert count == 1
        else:
            assert (await resolver.resolve(body(), {'userId': '7'}))['template']['id'] == '19'
            assert count == 2
    finally:
        await resolver.close()


@pytest.mark.asyncio
async def test_config_change_stops_service_instead_of_hot_switching_live_sessions(monkeypatch):
    import sduoj_ide_worker.service as module
    monkeypatch.setenv('SDUOJ_IDE_NACOS_HASH', 'previous-hash')
    service = Service(Discovery(), Child)
    service.nacos.configuration = lambda: None
    async def configuration_changed():
        return configuration()
    service.nacos.configuration = configuration_changed
    async def no_wait(_):
        pass
    monkeypatch.setattr(module.asyncio, 'sleep', no_wait)
    await service.control_plane()
    assert service.closed.is_set()
    assert service.reason == 'configuration_changed_restart_required'


@pytest.mark.asyncio
async def test_control_plane_tolerates_one_transient_failure_but_stops_after_three(monkeypatch):
    import sduoj_ide_worker.service as module
    discovery = Discovery()
    count = 0
    async def failing_beat():
        nonlocal count
        count += 1
        raise httpx.ReadTimeout('unavailable')
    discovery.beat = failing_beat
    service = Service(discovery, Child)
    async def no_wait(_):
        pass
    monkeypatch.setattr(module.asyncio, 'sleep', no_wait)
    await service.control_plane()
    assert count == 3
    assert service.closed.is_set() and not service.ready
    assert service.reason == 'control_plane_unavailable'
