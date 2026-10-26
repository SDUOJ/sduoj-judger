"""One persistent GDB for one private process tree. No console/evaluate API."""

import asyncio
import json
import os
import re
import sys
import tty
from .mi import parse


class Native:
    def __init__(self, emit):
        self.emit, self.seq, self.pending = emit, 0, {}
        self.breakpoints = []
        self.tasks = []
        self.references = {}
        self.frame = 0
        self.stop = asyncio.Event()
        self.stderr_tail = bytearray()

    async def start(self, spec):
        self.source = spec["source"]
        self.master, self.slave = os.openpty()
        slave = self.slave
        self.input_buffer = bytearray()
        os.set_blocking(self.master, False)
        tty.setraw(slave)
        self.process = await asyncio.create_subprocess_exec(
            *spec["debugger"],
            "--interpreter=mi2",
            "--nx",
            "--quiet",
            "-iex",
            "set auto-load off",
            "-iex",
            "maintenance set worker-threads 1",
            "/work/main",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=262144
        )
        self.tasks.append(asyncio.create_task(self.read()))
        self.tasks.append(asyncio.create_task(self.output()))
        self.tasks.append(asyncio.create_task(self.read_stderr()))
        try:
            # Apply before the executable loads and verify support over MI too.
            # GDB otherwise sizes its worker pool from the host's CPU count,
            # which can exhaust a bounded sandbox before it forks the target.
            await self.rpc('-interpreter-exec console "maintenance set worker-threads 1"')
            await self.rpc("-gdb-set pagination off")
            await self.rpc("-gdb-set confirm off")
            await self.rpc("-gdb-set print elements 100")
            await self.rpc("-gdb-set may-call-functions off")
            await self.rpc("-inferior-tty-set " + json.dumps(os.ttyname(slave)))
            await self.command("setBreakpoints", {"lines": spec["breakpoints"]})
            await self.rpc("-break-insert -t main")
            if spec.get("input"):
                self.queue_input(spec["input"])
            await self.rpc("-exec-run")
        except Exception as error:
            await asyncio.sleep(0)
            # Private startup evidence only. It must never become IDE output.
            print(json.dumps({"stage": "gdb-start", "exception": type(error).__name__,
                              "message": str(error)[:1024],
                              "returnCode": self.process.returncode,
                              "stderr": bytes(self.stderr_tail).decode(errors="replace")}),
                  file=sys.stderr, flush=True)
            raise

    async def read_stderr(self):
        while True:
            chunk = await self.process.stderr.read(4096)
            if not chunk:
                return
            self.stderr_tail.extend(chunk)
            del self.stderr_tail[:-4096]

    async def rpc(self, command):
        self.seq += 1
        future = asyncio.get_running_loop().create_future()
        seq = self.seq
        self.pending[seq] = future
        self.process.stdin.write((str(self.seq) + command + "\n").encode())
        await self.process.stdin.drain()
        try:
            return await asyncio.wait_for(future, 10)
        finally:
            self.pending.pop(seq, None)

    async def read(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                record = parse(line.decode(errors="replace").strip())
                if not record:
                    continue
                if record["kind"] == "^":
                    future = self.pending.get(record["token"])
                    if future and not future.done():
                        if record["name"] == "error":
                            future.set_exception(
                                ValueError(record["body"].get("msg", "GDB error"))
                            )
                        else:
                            future.set_result(record["body"])
                elif record["kind"] == "*" and record["name"] == "stopped":
                    body = record["body"]
                    if str(body.get("reason", "")).startswith("exited"):
                        self.emit("terminated", {"reason": body["reason"]})
                    else:
                        self.references.clear()
                        self.emit(
                            "stopped",
                            {
                                "threadId": int(body.get("thread-id", "1")),
                                "reason": body.get("reason", "pause"),
                            },
                        )
                elif record["kind"] == "*" and record["name"] == "running":
                    self.emit("running", {})
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(EOFError("GDB disconnected"))
            self.emit("terminated", {})

    async def output(self):
        # A single reader watches the PTY. It does not run blocking executor
        # reads that would leave one thread behind for each resident session.
        os.set_blocking(self.master, False)
        loop = asyncio.get_running_loop()

        def readable():
            try:
                data = os.read(self.master, 8192)
                if data:
                    self.emit(
                        "output",
                        {"output": data.decode(errors="replace"), "category": "stdout"},
                    )
            except OSError:
                pass

        loop.add_reader(self.master, readable)
        try:
            await self.process.wait()
        finally:
            loop.remove_reader(self.master)
            loop.remove_writer(self.master)
            os.close(self.slave)
            os.close(self.master)

    def queue_input(self, text):
        data = text.encode()
        if len(self.input_buffer) + len(data) > 65536:
            return {"acceptedBytes": 0, "error": "DEBUG_STDIN_BUFFER_FULL"}
        self.input_buffer.extend(data)
        loop = asyncio.get_running_loop()

        def flush():
            try:
                count = os.write(self.master, self.input_buffer)
                del self.input_buffer[:count]
                if not self.input_buffer:
                    loop.remove_writer(self.master)
            except BlockingIOError:
                pass
            except OSError:
                loop.remove_writer(self.master)

        if self.input_buffer:
            loop.add_writer(self.master, flush)
        return {"acceptedBytes": len(data)}

    async def inspect_paths(self, args):
        from ide_debug.watch import valid_path

        expressions = args.get("expressions", [])
        if not 1 <= len(expressions) <= 16 or any(
            not valid_path(v) for v in expressions
        ):
            raise ValueError("Invalid watch")
        await self.rpc("-stack-select-frame " + str(args["frameId"]))
        results = []
        for expression in expressions:
            variable = None
            try:
                # Only data paths pass validation. Function calls remain disabled
                # in GDB too, including overloaded C++ operators.
                body = await self.rpc("-var-create - * " + json.dumps(expression))
                variable = body.get("name")
                results.append(
                    {
                        "expression": expression,
                        "available": True,
                        "value": str(body.get("value", "<unavailable>"))[:1024],
                    }
                )
            except ValueError:
                results.append(
                    {
                        "expression": expression,
                        "available": False,
                        "value": "<unavailable>",
                    }
                )
            finally:
                if variable:
                    await self.rpc("-var-delete " + variable)
        return {"watches": results}

    async def command(self, op, args):
        if op == "setBreakpoints":
            if self.breakpoints:
                await self.rpc("-break-delete " + " ".join(self.breakpoints))
            self.breakpoints = []
            result = []
            for line in args["lines"]:
                try:
                    body = await self.rpc(
                        "-break-insert " + json.dumps(self.source + ":" + str(line))
                    )
                    self.breakpoints.append(body["bkpt"]["number"])
                    result.append(
                        {
                            "line": line,
                            "verified": body["bkpt"].get("addr") != "<PENDING>",
                        }
                    )
                except ValueError:
                    result.append({"line": line, "verified": False})
            return {"breakpoints": result}
        if op in ("continue", "next", "stepIn", "stepOut", "pause"):
            self.references.clear()
            cmd = {
                "continue": "-exec-continue",
                "next": "-exec-next",
                "stepIn": "-exec-step",
                "stepOut": "-exec-finish",
                "pause": "-exec-interrupt --all",
            }[op]
            return await self.rpc(cmd)
        if op == "threads":
            body = await self.rpc("-thread-info")
            return {
                "threads": [
                    {"id": int(t["id"]), "name": t.get("name", t["id"])}
                    for t in body.get("threads", [])
                ][:100]
            }
        if op == "stackTrace":
            await self.rpc("-thread-select " + str(args.get("threadId", 1)))
            body = await self.rpc("-stack-list-frames 0 99")
            return {
                "stackFrames": [
                    {
                        "id": int(f["frame"]["level"]),
                        "name": f["frame"].get("func", "?"),
                        "line": int(f["frame"].get("line", 0)),
                        "source": f["frame"].get("fullname", ""),
                    }
                    for f in body.get("stack", [])
                ]
            }
        if op == "scopes":
            self.frame = args["frameId"]
            await self.rpc("-stack-select-frame " + str(self.frame))
            return {
                "scopes": [
                    {
                        "name": "Locals",
                        "variablesReference": self.frame + 1,
                        "expensive": False,
                    }
                ]
            }
        if op == "variables":
            await self.rpc("-stack-select-frame " + str(args["variablesReference"] - 1))
            body = await self.rpc("-stack-list-variables --all-values")
            return {
                "variables": [
                    {
                        "name": v.get("name", "?"),
                        "value": str(v.get("value", "<unavailable>"))[:4096],
                        "variablesReference": 0,
                    }
                    for v in body.get("variables", [])
                ][args.get("start", 0) : args.get("start", 0) + args.get("count", 100)]
            }
        if op == "stdin":
            return self.queue_input(args["text"])
        raise ValueError("Unsupported debugger command")
