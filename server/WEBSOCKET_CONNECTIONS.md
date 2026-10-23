# WebSocket connection deployment

The canvas WebSocket checks the browser's `Origin` against an exact allowlist before reading the session or canvas. By default it accepts these local frontend origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

Set `WEBSOCKET_ALLOWED_ORIGINS` to a comma-separated list of exact origins for another deployment, including the scheme and port when present. For example:

```sh
WEBSOCKET_ALLOWED_ORIGINS=https://whiteboard.example.com
```

An absent or unlisted origin is rejected before a snapshot is loaded. The list does not support wildcard matching.

Run the server with one Uvicorn worker:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 3001 --workers 1
```

Room locks and connection state live in process memory. Multiple workers would have separate room owners and could send inconsistent snapshots or miss broadcasts. A multi-worker deployment needs shared coordination before increasing the worker count.

Shutdown cancels and awaits in-flight connection handlers and senders. Socket-close attempts run independently and time out after one second so a blocked transport cannot stall other peers. A cancelled handshake releases its room lease.

The endpoint authenticates, sends snapshots, and accepts `shape.create`, `shape.update`, and `shape.delete`. Invalid messages receive `invalid_message`; other valid commands receive `feature_not_available` until their tickets are implemented.

Run the backend tests from `server` with the test database configured:

```sh
TEST_DATABASE_URL=postgresql://... python -m unittest discover -s tests -v
```
