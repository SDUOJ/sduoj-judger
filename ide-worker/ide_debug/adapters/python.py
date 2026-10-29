"""Private debugpy DAP connection; only normalized operations reach the adapter."""

import asyncio
import codecs
import json


class Python:
    def __init__(self, emit):
        self.emit, self.seq, self.pending = emit, 0, {}
        self.initialized = asyncio.Event()
        self.thread_id = 1
        self.entry_breakpoint = False
        self.terminated = False
        self.output_tasks = []

    async def start(self, spec):
        self.source = "/work/" + spec["source"]
        self.process = await asyncio.create_subprocess_exec(
            spec["targetPython"],
            "-u",
            "-Xfrozen_modules=off",
            "/opt/sduoj-debug/ide_debug/python_entry.py",
            "--allow-plain-fields",
            "--listen",
            "127.0.0.1:5678",
            "--wait-for-client",
            self.source,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.output_tasks = [
            asyncio.create_task(self.output(self.process.stdout, "stdout")),
            asyncio.create_task(self.output(self.process.stderr, "stderr")),
        ]
        self.tasks = list(self.output_tasks)
        for attempt in range(100):
            try:
                self.reader, self.writer = await asyncio.open_connection(
                    "127.0.0.1", 5678, limit=262144
                )
                break
            except OSError:
                if self.process.returncode is not None:
                    raise RuntimeError("debugpy failed to start")
                await asyncio.sleep(0.05)
        else:
            raise TimeoutError("debugpy listen timeout")
        self.tasks.append(asyncio.create_task(self.read()))
        await self.rpc(
            "initialize",
            {
                "adapterID": "debugpy",
                "clientID": "sduoj",
                "pathFormat": "path",
                "linesStartAt1": True,
                "columnsStartAt1": True,
            },
        )
        attach = asyncio.create_task(
            self.rpc("attach", {"justMyCode": False, "subProcess": False})
        )
        await asyncio.wait_for(self.initialized.wait(), 10)
        await self.command("setBreakpoints", {"lines": spec["breakpoints"] or [1]})
        self.entry_breakpoint = not spec["breakpoints"]
        await self.rpc("configurationDone", {})
        await attach
        if spec.get("input"):
            self.process.stdin.write(spec["input"].encode())
            # Stream transport drains asynchronously; a paused target may not
            # read yet, so input must not block the session actor.

    async def rpc(self, command, arguments):
        self.seq += 1
        seq = self.seq
        future = asyncio.get_running_loop().create_future()
        self.pending[seq] = future
        data = json.dumps(
            {"seq": seq, "type": "request", "command": command, "arguments": arguments}
        ).encode()
        self.writer.write(("Content-Length: %d\r\n\r\n" % len(data)).encode() + data)
        await self.writer.drain()
        try:
            return await asyncio.wait_for(future, 10)
        finally:
            self.pending.pop(seq, None)

    async def read(self):
        try:
            while True:
                header = await self.reader.readuntil(b"\r\n\r\n")
                length = int(
                    dict(line.split(b":", 1) for line in header.strip().split(b"\r\n"))[
                        b"Content-Length"
                    ]
                )
                if length > 262144:
                    raise ValueError("DAP response limit")
                message = json.loads(await self.reader.readexactly(length))
                if message.get("type") == "response":
                    future = self.pending.get(message.get("request_seq"))
                    if future and not future.done():
                        if message.get("success"):
                            future.set_result(message.get("body", {}))
                        else:
                            future.set_exception(ValueError("Debugger request failed"))
                elif message.get("type") == "event":
                    name = message["event"]
                    if name == "initialized":
                        self.initialized.set()
                    elif name in ("stopped", "terminated"):
                        if name == "stopped":
                            self.thread_id = message.get("body", {}).get("threadId", 1)
                        if name == 'terminated':
                            await self.finish(message.get('body', {}))
                        else:
                            self.emit(name, message.get("body", {}))
                    elif name == "continued":
                        self.emit("running", {})
                elif message.get("type") == "request":
                    # No runInTerminal or host-side reverse launch.
                    raise ValueError("Unexpected DAP reverse request")
        except (EOFError, asyncio.IncompleteReadError):
            await self.finish({})
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(EOFError("debugpy disconnected"))

    async def finish(self, body):
        if self.terminated:
            return
        self.terminated = True
        if self.output_tasks:
            # A descendant may hold a pipe open; keep a finite drain window
            # while the independent guardian deadlines remain active.
            await asyncio.wait(self.output_tasks, timeout=1)
        self.emit('terminated', body)

    async def output(self, stream, category):
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        while True:
            value = await stream.read(8192)
            if not value:
                tail = decoder.decode(b'', final=True)
                if tail:
                    self.emit('output', {'output': tail, 'category': category})
                return
            text = decoder.decode(value)
            if text:
                self.emit('output', {'output': text, 'category': category})

    async def command(self, op, args):
        if op == "setBreakpoints":
            result = await self.rpc(
                op,
                {
                    "source": {"path": self.source},
                    "breakpoints": [{"line": n} for n in args["lines"]],
                },
            )
            self.entry_breakpoint = False
            return result
        if self.entry_breakpoint and op in ("continue", "next", "stepIn", "stepOut"):
            # The implicit entry stop is one-shot. Keeping a line-1 breakpoint
            # would stop again in a class body defined on that same line.
            await self.command("setBreakpoints", {"lines": []})
        if op == "stdin":
            data = args["text"].encode()
            if self.process.stdin.transport.get_write_buffer_size() + len(data) > 65536:
                return {"acceptedBytes": 0, "error": "DEBUG_STDIN_BUFFER_FULL"}
            self.process.stdin.write(data)
            # Stream transport drains asynchronously; a paused target may not
            # read yet, so input must not block the session actor.
            return {"acceptedBytes": len(data)}
        if op in ("continue", "next", "stepIn", "stepOut", "pause"):
            args = {"threadId": args.get("threadId") or self.thread_id}
        if op == "stackTrace":
            args = {
                "threadId": args.get("threadId") or self.thread_id,
                "startFrame": 0,
                "levels": 100,
            }
        return await self.rpc(op, args)
