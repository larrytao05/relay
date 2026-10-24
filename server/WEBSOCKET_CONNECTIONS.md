# WebSocket connection deployment

The canvas WebSocket checks the browser's `Origin` against an exact allowlist before reading the session or canvas. By default it accepts these local frontend origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

Set `WEBSOCKET_ALLOWED_ORIGINS` to a comma-separated list of exact origins for another deployment, including the scheme and port when present. For example:

```sh
WEBSOCKET_ALLOWED_ORIGINS=https://whiteboard.example.com
```

An absent or unlisted origin is rejected before a snapshot is loaded. The list does not support wildcard matching.

The durable operation listener uses a dedicated PostgreSQL session while a
process has active WebSocket connections. Set `DATABASE_LISTENER_URL` to the
direct PostgreSQL endpoint when `DATABASE_URL` uses a transaction pooler. It
defaults to `DATABASE_URL`.

Durable edits are journaled and can be delivered between processes. Presence,
cursors, and logout revocation still use process-local state, so keep one
Uvicorn worker until those cross-process paths are implemented and verified:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 3001 --workers 1
```

Room locks, presence, cursors, and session revocation live in process memory.
Multiple workers still need shared coordination for those transient events.
Durable operation notifications are only wake-ups; the operation journal
remains authoritative, and each process catches up by canvas revision after
notifications and listener reconnects. The listener closes after the last
local socket leaves and a short idle grace period expires.

Shutdown cancels and awaits in-flight connection handlers and senders. Socket-close attempts run independently and time out after one second so a blocked transport cannot stall other peers. A cancelled handshake releases its room lease.

## Session lifetime

Logout deletes the database session, detaches all connections for its token digest across canvases under room locks, stops their senders and queued delivery, and closes them with code `1008` before returning. Other sessions for the same user remain connected. Session and membership are rechecked for incoming frames and at subscription.

Each accepted connection has an owned expiry task. The default check interval is **1 second**; it compares the recorded session expiry against the room clock. Expired idle connections detach and close with `1008`. Disconnect and shutdown cancel and await expiry tasks. Tests inject the clock to advance expiry without waiting for a real session lifetime.

The endpoint authenticates, sends snapshots, and accepts `shape.create`, `shape.update`, `shape.delete`, and `cursor`. Presence joins and leaves identify each tab independently. Invalid messages receive `invalid_message`. Undo and redo persist inverse operations and protect later collaborator edits; navigation resets on reconnect.

Run the backend tests from `server` with the test database configured:

```sh
TEST_DATABASE_URL=postgresql://... python -m unittest discover -s tests -v
```
