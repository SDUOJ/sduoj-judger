"""Trusted private PID1: native compile, kernel drain, then bounded handoff.

The untrusted compiler lives in the official sandbox's nested namespaces and
native cgroup. This supervisor retains only its own tmpfs until that compiler
tree is dead. Guardian moves the trusted supervisor to the handoff accounting
branch before any artifact copy. Neither source nor diagnostics use stdout.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from .compile_artifacts import ArtifactContract, Limits, freeze_artifacts
from .judge_compile import compile_source
from .runner import namespace_identity


MAX_FRAME = 262144


def encode_message(value):
    wire = json.dumps(value, separators=(',', ':'))
    if len(wire) + 1 > MAX_FRAME and value.get('event') == 'compileError':
        value = dict(value, body=dict(value['body'], truncated=True))
        output = value['body'].get('output', '')
        low, high = 0, len(output)
        while low < high:
            middle = (low + high + 1) // 2
            value['body']['output'] = output[:middle]
            if len(json.dumps(value, separators=(',', ':'))) + 1 <= MAX_FRAME:
                low = middle
            else:
                high = middle - 1
        value['body']['output'] = output[:low]
        wire = json.dumps(value, separators=(',', ':'))
    if len(wire) + 1 > MAX_FRAME:
        raise ValueError('Compile control frame exceeds bound')
    return wire


def send(value):
    print(encode_message(value), flush=True)


def confirm_compiler_drained():
    root = Path('/compile-cgroup')
    for path in (root, *[child for child in root.iterdir() if child.is_dir()]):
        if path != root and path.name != 'control':
            raise RuntimeError('Native compiler cgroup not removed')
        if (path / 'cgroup.procs').read_text().split():
            raise RuntimeError('Compiler phase not drained')
        events = dict(line.split() for line in (path / 'cgroup.events').read_text().splitlines())
        if events.get('populated') != '0':
            raise RuntimeError('Compiler descendants still populated')


async def main():
    namespace_identity()
    spec = json.loads(sys.stdin.buffer.readline(1048577))['spec']
    source = Path('/work/tree')
    source.mkdir(mode=0o777)
    source.chmod(0o777)
    path = source / spec['source']
    raw = spec['code'].encode()
    with path.open('xb') as stream:
        stream.write(raw)
    path.chmod(0o644)
    identity = source.stat()
    failure = await compile_source(spec, str(source))
    if failure:
        send({'event': 'compileError', 'body': failure})
        return 1
    # No compiler, adapter or source-controlled code can write this pipe.
    send({'phase': 'handoff'})
    if sys.stdin.buffer.readline(128) != b'freeze\n':
        raise RuntimeError('Guardian handoff acknowledgement required')
    confirm_compiler_drained()
    cache_tag = ''
    if spec['language'] == 'python':
        if os.path.realpath(spec['targetPython']) != os.path.realpath(sys.executable):
            raise RuntimeError('Unverified Python cache ABI')
        cache_tag = sys.implementation.cache_tag
    contract = ArtifactContract(spec['language'], spec['source'],
        hashlib.sha256(raw).hexdigest(), spec['templateSha256'],
        spec['compileSandboxSha256'], identity.st_dev, identity.st_ino, 65534,
        python_cache_tag=cache_tag, limits=Limits(max_bytes=spec['artifactMaxBytes']))
    parent = os.open('/work', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    export = os.open('/control', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        frozen = freeze_artifacts(parent, 'tree', export, 'artifacts',
            contract=contract, confirm_drained=confirm_compiler_drained)
    finally:
        os.close(parent)
        os.close(export)
    send({'prepared': frozen.manifest_sha256})
    return 0


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except Exception as error:
        print(json.dumps({'stage': 'compile-phase', 'exception': type(error).__name__}),
              file=sys.stderr, flush=True)
        send({'event': 'compileError', 'body': {'code': 'DEBUG_COMPILE_SANDBOX_FAILED', 'output': ''}})
        sys.exit(1)
