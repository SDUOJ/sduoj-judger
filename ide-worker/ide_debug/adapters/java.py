"""JDI bridge over private pipes; target JVM uses the exact approved JDK."""

import asyncio
import base64
import json


class Java:
    def __init__(self, emit):
        self.emit, self.seq, self.pending = emit, 0, {}

    async def start(self, spec):
        # debugger argv is an operator-approved Java + bridge classpath, never
        # the shared LSP JVM. The bridge launches a separate target VM.
        self.process = await asyncio.create_subprocess_exec(
            *spec["debugger"],
            "/work",
            spec["source"][:-5],
            ";".join(str(n) for n in spec["breakpoints"]),
            base64.b64encode("\n".join(spec["javaOptions"]).encode()).decode(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=262144
        )
        self.task = asyncio.create_task(self.read())
        if spec.get("input"):
            await self.command("stdin", {"text": spec["input"]})

    async def read(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                if "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if message.get("ok"):
                            future.set_result(message.get("body", {}))
                        else:
                            future.set_exception(ValueError("Java debugger request failed"))
                else:
                    self.emit(message["event"], message.get("body", {}))
        finally:
            self.emit("terminated", {})
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(EOFError("JDI disconnected"))

    async def command(self, op, args):
        self.seq += 1
        seq = self.seq
        # Tab separated fields; only stdin text is encoded arbitrary content.
        fields = [
            str(seq),
            op,
            str(args.get("threadId", 0)),
            str(args.get("frameId", 0)),
            str(args.get("variablesReference", 0)),
            str(args.get("start", 0)),
            str(args.get("count", 100)),
            ";".join(str(n) for n in args.get("lines", [])),
            base64.b64encode(args.get("text", "").encode()).decode(),
        ]
        future = asyncio.get_running_loop().create_future()
        self.pending[seq] = future
        self.process.stdin.write(("\t".join(fields) + "\n").encode())
        await self.process.stdin.drain()
        try:
            return await asyncio.wait_for(future, 10)
        finally:
            self.pending.pop(seq, None)
