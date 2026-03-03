# Switch Universe Backend

WebSocket gateway that runs one simulator process per browser session.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /health`
- `WS /ws/session/{session_id}?scenario=default_lab`

### WebSocket message format

Client -> Server:

```json
{"type":"input","payload":"show mac address-table"}
```

Server -> Client:

```json
{"type":"stdout","payload":"Switch# ..."}
```
