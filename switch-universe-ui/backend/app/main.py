from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .bridge import SimulatorBridge

app = FastAPI(title="Switch Universe Gateway", version="0.1.0")
bridge = SimulatorBridge()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/session/{session_id}")
async def session_socket(
    websocket: WebSocket,
    session_id: str,
    scenario: str = Query(default="default_lab"),
) -> None:
    await websocket.accept()
    await bridge.start_session(session_id, scenario=scenario)

    async def emit(channel: str, text: str) -> None:
        await websocket.send_text(json.dumps({"type": channel, "payload": text}))

    stream_task = asyncio.create_task(bridge.stream_output(session_id, emit))

    try:
        await websocket.send_text(json.dumps({"type": "meta", "payload": f"session={session_id} scenario={scenario}"}))
        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                data = {"type": "input", "payload": message}

            if data.get("type") == "input":
                command = str(data.get("payload", "")).strip("\n")
                await bridge.write_command(session_id, command)
            elif data.get("type") == "shutdown":
                break
    except WebSocketDisconnect:
        pass
    finally:
        stream_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream_task
        await bridge.stop_session(session_id)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await bridge.cleanup()
