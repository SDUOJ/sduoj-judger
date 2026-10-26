"""Judger-compatible Nacos namespace/group, configuration and ephemeral discovery.

Configuration uses JSON in a .yml dataId, as does sduoj-deploy/dev-config/nacos.
Only explicitly allowed process settings may be supplied by the config server.
Secrets are expanded locally and are never included in discovery metadata.
"""
import asyncio
import hashlib
import json
import os
import re
import socket

import httpx
from ide_intelligence.resource_settings import LIMITS, validate as validate_resources


ALLOWED = {
    'SDUOJ_IDE_REDIS_URL', 'SDUOJ_IDE_PREFIX', 'SDUOJ_IDE_CONCURRENCY',
    'SDUOJ_IDE_LSP_PROCESSES', 'SDUOJ_IDE_MAX_DOCUMENTS',
    'SDUOJ_DEBUG_GLOBAL_HARD', 'SDUOJ_DEBUG_GLOBAL_BUDGET',
    'AUTOLAB_IDE_TOOLCHAIN_TOKEN', 'AUTOLAB_DEBUG_RESOLVER_URL',
}
ALLOWED.update(LIMITS)
ALLOWED.update('SDUOJ_IDE_' + lang + '_' + name
               for lang in ('C', 'CPP', 'JAVA', 'PYTHON', 'DEBUG')
               for name in ('CONCURRENCY',))
ALLOWED.update('AUTOLAB_DEBUG_' + name for name in (
    'ENABLED', 'RESIDENT', 'ACTIVE', 'QUEUE', 'IDLE', 'LIFETIME', 'WAIT',
    'OPERATION', 'RUN_SLICE', 'BUDGET', 'HARD', 'RESERVE', 'HOST_FLOOR',
    'PID_BUDGET', 'GUARDIAN_MEMORY', 'CGROUP_VERSION', 'CGROUP_PARENT',
    'CGROUP_ROOT', 'SUBUID', 'SUBGID', 'STATE_DIR', 'MANIFEST',
))


def settings(raw, environment=None):
    if len(raw.encode()) > 65536:
        raise ValueError('IDE configuration exceeds limit')
    data = json.loads(raw)
    if data.get('schemaVersion') != 1 or not isinstance(data.get('environment'), dict):
        raise ValueError('Unsupported IDE configuration schema')
    source = os.environ if environment is None else environment
    values = {}
    for name, value in data['environment'].items():
        if name not in ALLOWED or not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError('Unsupported IDE configuration key or value')
        def expand(match):
            result = source.get(match[1])
            if not result:
                raise ValueError('Required IDE configuration secret is missing')
            return result
        values[name] = re.sub(r'\$\{([A-Z][A-Z0-9_]*)\}', expand, str(value))
    if not values.get('SDUOJ_IDE_REDIS_URL', '').startswith(('redis://', 'rediss://')):
        raise ValueError('Nacos must configure the AutoLab Redis URL')
    prefix = values.get('SDUOJ_IDE_PREFIX', '')
    if not re.fullmatch(r'[A-Za-z0-9:_-]{4,100}:', prefix):
        raise ValueError('A bounded explicit IDE Redis prefix is required')
    if values.get('AUTOLAB_DEBUG_ENABLED') != '1':
        raise ValueError('Unified IDE workers require Debug enabled')
    validate_resources(values)
    return values


def fingerprint(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class Nacos:
    def __init__(self, client=None):
        address = os.getenv('NACOS_ADDR', 'sduoj-nacos:8848')
        if not address.startswith(('http://', 'https://')):
            address = 'http://' + address
        self.address = address.rstrip('/') + '/nacos/v1'
        self.namespace = os.getenv('NACOS_NAMESPACE', os.getenv('ACTIVE', 'dev'))
        self.group = os.getenv('NACOS_GROUP', 'DEFAULT_GROUP')
        self.data_id = os.getenv('NACOS_DATA_ID', 'ide-worker.yml')
        self.service = os.getenv('NACOS_SERVICE', 'ide-worker')
        self.client = client or httpx.AsyncClient(timeout=3, trust_env=False)
        self.token = None
        self.instance = None

    async def request(self, method, endpoint, params, *, retry_auth=True):
        if os.getenv('NACOS_USERNAME') and not self.token:
            response = await self.client.post(self.address + '/auth/login', data={
                'username': os.environ['NACOS_USERNAME'], 'password': os.environ['NACOS_PASSWORD']})
            response.raise_for_status()
            self.token = response.json()['accessToken']
        query = dict(params)
        if self.token:
            query['accessToken'] = self.token
        response = await self.client.request(method, self.address + endpoint, params=query)
        if response.status_code in (401, 403) and self.token:
            self.token = None
            if retry_auth:
                return await self.request(method, endpoint, params, retry_auth=False)
        if response.status_code != 200:
            # Do not expose config, credentials or response bodies in exceptions.
            raise RuntimeError('Nacos operation failed status=' + str(response.status_code))
        return response

    async def configuration(self):
        response = await self.request('GET', '/cs/configs', {
            'dataId': self.data_id, 'group': self.group, 'tenant': self.namespace})
        settings(response.text)  # Also validate subsequent remote changes.
        return response.text

    async def register(self, worker_id, port):
        ip = os.getenv('NACOS_IP')
        if not ip:
            ip = socket.gethostbyname(socket.gethostname())
        self.instance = {'serviceName': self.service, 'groupName': self.group,
            'namespaceId': self.namespace, 'ip': ip, 'port': port, 'ephemeral': 'true',
            'metadata': json.dumps({'workerId': worker_id, 'capabilities': 'lsp,debug',
                                    'protocolVersion': '1'})}
        response = await self.request('POST', '/ns/instance', self.instance)
        if response.text.strip() != 'ok':
            raise RuntimeError('Nacos did not confirm IDE registration')

    async def beat(self):
        instance = self.instance
        beat = {'serviceName': self.group + '@@' + self.service, 'ip': instance['ip'],
                'port': instance['port'], 'cluster': 'DEFAULT', 'scheduled': False,
                'weight': 1, 'metadata': json.loads(instance['metadata'])}
        response = await self.request('PUT', '/ns/instance/beat', {
            **instance, 'beat': json.dumps(beat)})
        if response.json().get('code') != 10200:
            raise RuntimeError('Nacos did not confirm IDE heartbeat')

    async def deregister(self):
        if self.instance:
            response = await self.request('DELETE', '/ns/instance', self.instance)
            if response.text.strip() != 'ok':
                raise RuntimeError('Nacos did not confirm IDE deregistration')

    async def close(self):
        await self.client.aclose()


async def bootstrap():
    client = Nacos()
    try:
        raw = await client.configuration()
        os.environ.update(settings(raw))
        os.environ['SDUOJ_IDE_NACOS_HASH'] = fingerprint(raw)
    finally:
        await client.close()
