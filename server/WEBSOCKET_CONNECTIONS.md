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
cursors, and logout revocations use transient PostgreSQL notifications on the
same per-process listener. Presence remains in memory; periodic per-peer sync
merges reported peers and TTL expiry removes peers no longer refreshed. Each
sync notification contains at most one peer, below PostgreSQL's payload limit. Multi-process
deployment requires a direct listener endpoint and adequate database connection
capacity:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 3001 --workers 2
```

Durable operation notifications are only wake-ups; the operation journal
remains authoritative, and each process catches up by canvas revision after
notifications and listener reconnects. The listener closes after the last
local socket leaves and a short idle grace period expires. A joining socket's
snapshot includes its local peers and currently known remote peers; additional
remote peers arrive after the snapshot through sync and notification events.

Shutdown cancels and awaits in-flight connection handlers and senders. Socket-close attempts run independently and time out after one second so a blocked transport cannot stall other peers. A cancelled handshake releases its room lease.

## Session lifetime

Logout deletes the database session and publishes its exact token digest in the same transaction. After the transaction commits, the current process detaches matching connections and closes them with code `1008` before returning; remote listeners detach matching sockets after notification delivery. Periodic session and membership revalidation, including idle sockets, closes connections if a notification is missed. Other sessions for the same user remain connected.

Each accepted connection has an owned revalidation task. The default check interval is **1 second**; it checks the database session, membership, and recorded expiry. Invalid or unverifiable sessions detach and close with `1008`. Disconnect and shutdown cancel and await the task.

The endpoint authenticates, sends snapshots, and accepts `shape.create`, `shape.update`, `shape.delete`, and `cursor`. Presence joins and leaves identify each tab independently. Invalid messages receive `invalid_message`. Undo and redo persist inverse operations and protect later collaborator edits; navigation resets on reconnect.

Run the backend tests from `server` with the test database configured:

```sh
TEST_DATABASE_URL=postgresql://... python -m unittest discover -s tests -v
```
