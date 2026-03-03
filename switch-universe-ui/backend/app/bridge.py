from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SimulatorSession:
    session_id: str
    process: asyncio.subprocess.Process
    stdout_task: Optional[asyncio.Task] = None
    stderr_task: Optional[asyncio.Task] = None
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SimulatorBridge:
    def __init__(self) -> None:
        self._sessions: dict[str, SimulatorSession] = {}
        self._root = Path(__file__).resolve().parents[3]

    async def start_session(self, session_id: str, scenario: str = "default_lab") -> SimulatorSession:
        existing = self._sessions.get(session_id)
        if existing and existing.process.returncode is None:
            return existing

        command = ["-u", "main.py", "--scenario", scenario]
        process = await asyncio.create_subprocess_exec(
            "python",
            *command,
            cwd=str(self._root),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        session = SimulatorSession(session_id=session_id, process=process)
        self._sessions[session_id] = session
        return session

    async def write_command(self, session_id: str, command: str) -> None:
        session = self._sessions[session_id]
        if session.process.stdin is None:
            return
        async with session.write_lock:
            session.process.stdin.write((command + "\n").encode("utf-8"))
            await session.process.stdin.drain()

    async def stream_output(self, session_id: str, emit) -> None:
        session = self._sessions[session_id]

        async def _read_stream(stream: asyncio.StreamReader, channel: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                await emit(channel, line.decode(errors="replace"))

        assert session.process.stdout is not None
        assert session.process.stderr is not None

        session.stdout_task = asyncio.create_task(_read_stream(session.process.stdout, "stdout"))
        session.stderr_task = asyncio.create_task(_read_stream(session.process.stderr, "stderr"))

        await asyncio.wait([session.stdout_task, session.stderr_task], return_when=asyncio.ALL_COMPLETED)

    async def stop_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return

        if session.process.returncode is None:
            session.process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await asyncio.wait_for(session.process.wait(), timeout=2)

        for task in (session.stdout_task, session.stderr_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        self._sessions.pop(session_id, None)

    async def cleanup(self) -> None:
        for session_id in list(self._sessions.keys()):
            await self.stop_session(session_id)
