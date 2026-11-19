"""JSONL transport for a short-lived Codex app-server process."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from importlib.metadata import PackageNotFoundError, version
import json
import os
import shutil
import signal
import subprocess

from anyio import CancelScope


class AppServerError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class AppServer:
    def __init__(self, process: asyncio.subprocess.Process, transport: asyncio.SubprocessTransport):
        self.process = process
        self.transport = transport
        self.request_id = 0
        self.turn_events: list[dict] = []

    @classmethod
    @asynccontextmanager
    async def connect(cls, timeout: float = 60):
        executable = shutil.which("codex")
        if not executable:
            raise AppServerError("Codex CLI was not found on PATH.")
        options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
            else {"start_new_session": True}
        )
        loop = asyncio.get_running_loop()
        with CancelScope(shield=True):
            transport, protocol = await loop.subprocess_exec(
                lambda: asyncio.subprocess.SubprocessStreamProtocol(limit=64 * 1024 * 1024, loop=loop),
                executable, "app-server", "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,
                **options,
            )
        client = cls(asyncio.subprocess.Process(transport, protocol, loop), transport)
        graceful = False
        try:
            async with asyncio.timeout(timeout):
                try:
                    client_version = version("codexmcp")
                except PackageNotFoundError:
                    client_version = "dev"
                await client.request("initialize", {
                    "clientInfo": {"name": "codexmcp", "title": "Antigravity via Codex MCP", "version": client_version},
                })
                await client.send({"method": "initialized"})
                yield client
                graceful = True
        except TimeoutError as exc:
            raise AppServerError(f"Codex app-server timed out after {timeout:g}s.") from exc
        finally:
            with CancelScope(shield=True):
                await client.close(graceful)

    async def close(self, graceful: bool) -> None:
        try:
            await self.shutdown(graceful)
        finally:
            self.transport.close()
            await asyncio.sleep(0)

    async def shutdown(self, graceful: bool) -> None:
        if graceful:
            try:
                await asyncio.wait_for(self.process.communicate(), timeout=5)
                return
            except (TimeoutError, OSError):
                pass
        if os.name == "nt":
            if self.process.returncode is None:
                with suppress(OSError, TimeoutError):
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill.exe", "/PID", str(self.process.pid), "/T", "/F",
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    try:
                        await asyncio.wait_for(killer.wait(), timeout=5)
                    finally:
                        if killer.returncode is None:
                            with suppress(ProcessLookupError):
                                killer.kill()
                            await killer.wait()
                if self.process.returncode is None:
                    with suppress(ProcessLookupError):
                        self.process.kill()
        else:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
        self.transport.close()
        with suppress(TimeoutError):
            await asyncio.wait_for(self.process.wait(), timeout=5)

    async def send(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            self.process.stdin.write(data)
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise AppServerError("Codex app-server closed its input pipe.") from exc

    async def receive(self) -> dict:
        while line := await self.process.stdout.readline():
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(message, dict):
                continue
            if "id" in message and "method" in message:
                await self.send({"id": message["id"], "error": {
                    "code": -32601, "message": "This MCP client does not support interactive requests.",
                }})
                continue
            return message
        raise AppServerError("Codex app-server exited before replying. Check Codex CLI and its configuration.")

    async def request(self, method: str, params: dict, *, capture_turn: bool = False) -> dict:
        self.request_id += 1
        await self.send({"id": self.request_id, "method": method, "params": params})
        while True:
            message = await self.receive()
            if message.get("id") == self.request_id:
                if "error" in message:
                    error = message["error"]
                    raise AppServerError(f"{method}: {error['message']}", error.get("code"))
                return message["result"]
            if capture_turn and message.get("method") in {"item/completed", "turn/completed"}:
                self.turn_events.append(message)

    async def completed_turn(self, thread_id: str, turn_id: str) -> tuple[dict, list[dict]]:
        items = []
        pending, self.turn_events = iter(self.turn_events), []
        while True:
            message = next(pending, None) or await self.receive()
            params = message.get("params", {})
            if not isinstance(params, dict) or params.get("threadId") != thread_id:
                continue
            if message.get("method") == "item/completed" and params.get("turnId") == turn_id:
                if params["item"].get("type") == "agentMessage":
                    items.append(params["item"])
            if message.get("method") == "turn/completed" and params["turn"]["id"] == turn_id:
                return params["turn"], items
