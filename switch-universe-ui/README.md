# Switch Universe UI (External Experience Layer)

This project is a separate web interface for the switch simulator.

It is designed to avoid touching simulator internals while providing:
- browser-based CLI session
- visual world/3D switch experience
- clean gateway boundary for future labs and storytelling

## Structure

- `backend/` FastAPI WebSocket gateway that launches simulator session processes
- `frontend/` React + Three.js immersive UI

## Why this is separate

Your original simulator remains authoritative for switch logic and command behavior.

This app treats the simulator as a runtime dependency and interacts through process I/O only.

## Run backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

## Run frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

The frontend connects to backend URL from `VITE_BACKEND_URL` (defaults to `http://localhost:8000`).

## Near-term roadmap

1. Parse key `show` outputs into structured JSON snapshots
2. Add click-to-run commands from ports/devices
3. Add scenario timeline and playback
4. Add guided beginner missions
5. Add multi-switch topology room
