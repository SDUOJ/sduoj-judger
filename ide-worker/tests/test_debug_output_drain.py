import asyncio
import json
import os

from ide_debug.adapters.native import Native
from ide_debug.adapters.python import Python
from ide_debug.compile_phase import encode_message, MAX_FRAME


def test_native_exit_drains_queued_utf8_before_terminal():
    async def check():
        events = []
        adapter = Native(lambda kind, body: events.append((kind, body)))
        adapter.master, writer = os.pipe()
        os.set_blocking(adapter.master, False)
        stream = asyncio.StreamReader()
        stream.feed_data(b'*stopped,reason="exited-normally"\n')
        stream.feed_eof()
        adapter.process = type('Process', (), {'stdout': stream})()
        try:
            data = '结果-TAIL'.encode()
            os.write(writer, data[:1])
            adapter.drain_output()
            os.write(writer, data[1:])
            await adapter.read()
            assert ''.join(body['output'] for kind, body in events if kind == 'output') == '结果-TAIL'
            assert [kind for kind, _ in events][-1] == 'terminated'
            assert sum(kind == 'terminated' for kind, _ in events) == 1
        finally:
            os.close(adapter.master)
            os.close(writer)
    asyncio.run(check())


def test_python_terminal_waits_for_both_output_streams():
    async def check():
        events = []
        adapter = Python(lambda kind, body: events.append((kind, body)))
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        adapter.output_tasks = [asyncio.create_task(adapter.output(stdout, 'stdout')),
                                asyncio.create_task(adapter.output(stderr, 'stderr'))]
        data = '结果-TAIL'.encode()
        stdout.feed_data(data[:1])
        await asyncio.sleep(0)
        terminal = asyncio.create_task(adapter.finish({}))
        stdout.feed_data(data[1:])
        stderr.feed_data(b'ERR-TAIL')
        stdout.feed_eof()
        stderr.feed_eof()
        await terminal
        assert events[-1][0] == 'terminated'
        assert ''.join(body['output'] for kind, body in events if kind == 'output' and body['category'] == 'stdout') == '结果-TAIL'
        assert ''.join(body['output'] for kind, body in events if kind == 'output' and body['category'] == 'stderr') == 'ERR-TAIL'
    asyncio.run(check())


def test_escaped_compiler_diagnostics_fit_actual_json_frame():
    diagnostic = {'event': 'compileError', 'body': {'code': 'DEBUG_COMPILE_FAILED', 'output': '\x00' * 65536}}
    wire = encode_message(diagnostic)
    assert len(wire.encode()) + 1 <= MAX_FRAME
    result = json.loads(wire)
    assert result['body']['code'] == 'DEBUG_COMPILE_FAILED'
    assert result['body']['output'] and result['body']['truncated']
