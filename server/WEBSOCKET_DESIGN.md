# Canvas WebSocket design

Implementation is broken into eight tickets in [WEBSOCKET_TICKETS.md](WEBSOCKET_TICKETS.md). Each ticket requires behavior tests before production implementation.

## Problem

The original `/ws` placeholder has been replaced by `/ws/canvases/{canvas_id}`. The backend already has cookie sessions, canvas membership, an asyncpg pool, and tables for shapes and operations. The WebSocket needs one ordering rule across snapshot delivery, edits, and presence. The target workload is 2–5 collaborators per canvas.

## Usage

`main.py` creates one `CanvasRooms` instance during startup and registers its router. The room owner handles a connection from authentication through disconnect. Logout calls its session-revocation hook after deleting the database session.

```python
rooms = CanvasRooms(pool, allowed_origins)
app.state.canvas_rooms = rooms
app.include_router(canvas_ws_router)  # module-level router

# WebSocket route
await rooms.serve(socket, canvas_id)

# Auth logout, after deleting the session row
await request.app.state.canvas_rooms.revoke_session(session_hash)
```

## Shape

`canvas_ws.py` owns the connection lifecycle, per-canvas locks, presence, event ordering, and private durable command helpers. This keeps snapshot subscription and committed broadcast under one owner. The module exports the router and `CanvasRooms`; it does not export wire or database types.

```python
@dataclass(frozen=True)
class SessionIdentity:
    token_hash: str
    user: PublicUser
    expires_at: datetime

@dataclass
class Connection:
    id: UUID
    canvas_id: UUID
    identity: SessionIdentity
    socket: WebSocket
    outbound: asyncio.Queue[dict[str, object]]
    history: Navigation
    cursor: Point | None

@dataclass
class Room:
    lock: asyncio.Lock
    connections: dict[UUID, Connection]

class CanvasRooms:
    async def serve(self, socket: WebSocket, canvas_id: UUID) -> None: ...
    async def revoke_session(self, token_hash: str) -> None: ...
    async def close(self) -> None: ...
```

The handler parses JSON into private Pydantic command types at the socket boundary. Command helpers accept those typed values. They validate shape properties by kind, check the expected shape revision, and write the shape, operation, and next canvas revision in one transaction. They return the response payload and whether a new operation committed; exact retries and refusals do not alter navigation or broadcast.

Every shape also stores `opacity` (from 0 to 1) and `z_index`. Old shapes default to fully opaque and retain their prior deterministic ID order. Canvas rendering sorts by ascending `z_index`, then shape ID. Opacity and layer changes use ordinary revision-checked shape updates, so they persist, broadcast, and participate in connection-local undo/redo.

Each room owns one lock. Snapshot loading and connection registration happen under that lock. Durable commands update PostgreSQL under the lock, commit, then enqueue the resulting event to each connection before releasing it. A per-connection sender drains a bounded outbound queue, so network writes never hold the room lock. A slow client is disconnected and reconnects with a fresh snapshot.

Connection state is keyed by `connection_id`, not user ID. Each tab therefore has its own cursor and undo/redo navigation. Room state is transient. PostgreSQL remains authoritative for shapes and operation history.

Authentication uses the existing session cookie and session lookup. The socket checks the configured `Origin`, session, and canvas membership before acceptance. Commands and an owned periodic task recheck session validity and membership. Logout publishes an exact-session revocation in the session-deletion transaction, then closes local sockets synchronously after commit; remote closure is prompt but eventual, with periodic revalidation repairing missed notifications. Expired or invalid sessions detach and close with `1008`. Cleanup cancels and awaits the task.

## Persistence change

`canvas_operation` now has JSONB `request` and `result` columns alongside its before and after patches. The fresh schema and `migrations/001_operation_replay.sql` require populated values to be objects and permit both to be null for legacy rows. Durable command handlers populate both columns, compare the saved actor, canvas, and request on retry, and return the saved result for an exact retry. Reject reuse with different input and legacy IDs whose requests cannot be verified.

Operation IDs are globally unique. Handle a concurrent unique-key collision by reading the winning row and comparing its actor, canvas, and request. Do not rely on the per-canvas in-memory lock to protect IDs used in different canvases.

## Ordering and command rules

- The first frame is the snapshot. Queue it before registering later room events for that connection.
- Use `canvas.revision` to order document events. Use `shape.revision` only for stale shape checks.
- Broadcast durable operations only after the transaction commits. A conflict or refusal changes neither the shape nor the canvas revision.
- Store soft deletes as shape state so undo can restore them.
- Keep undo and redo navigation per connection. Store operation IDs in the navigation stacks, not copies of shapes.
- Refuse undo when a collaborator has changed the target shape since the operation. Each accepted undo or redo writes a new operation and revision.
- Treat text replacement as one whole-value edit. Do not merge concurrent text input or individual shape properties.
- Keep cursor positions and presence in memory. Never write cursor updates to PostgreSQL.

## Synthesis decision

Candidate A's cohesive room owner is the base. It scored better on ordering ownership, session revocation, retry semantics, and interface depth. Candidate B's split modules would make the route coordinate locking, commands, and event delivery. Pure validation lives in `canvas_protocol.py`; history inverses and navigation live in `canvas_history.py`. Room admission, commit ordering, and delivery remain owned by `CanvasRooms`.

The independent cross-judge also recommended A. It identified two corrections included here: persist immutable request/result data for idempotent retries, and handle global operation-ID collisions across canvases. At that point, the single-process room owner required one Uvicorn worker; transient notifications now relay presence between process-local rooms.

## Tradeoffs accepted

- The collaboration module owns transport lifecycle and command orchestration. This keeps ordering rules in one place, at the cost of a larger module.
- Each process owns its room locks and local sockets. PostgreSQL notifications carry committed operation wake-ups and transient presence, cursor, and session-revocation events. `canvas_transient.py` owns remote peer cache, protocol validation, versions, deduplication, per-peer sync, and TTL expiry; sync merges peers and TTL removes unrefreshed entries.
- Undo uses connection-scoped navigation and conservative shape-level conflict checks. Property-level undo remains out of scope.
- Slow peers reconnect after queue overflow. The server does not let a blocked socket hold a room lock.

## Alternatives considered

Separate `canvas_ws.py`, `realtime.py`, and `canvas_commands.py` modules. This makes each file smaller but exposes callback coordination across snapshot loading, locking, persistence, and broadcast. Keep this option for later if command code grows enough to sit behind one complete `apply` boundary.

An actor task and mailbox per canvas. This gives each process-local canvas room one writer, but adds task startup, cancellation, and request/reply lifecycle rules. A room lock and sender queue cover local ordering with less machinery.

## Implementation reconciliation

WS-01 implements private command models, parsing, shape validation, and patch merging in `canvas_protocol.py`. WS-02 implements replay columns and the rerunnable migration. WS-03 registers the canvas socket and implements authenticated snapshots, room leases, bounded outbound queues, and shutdown. The application lifespan owns one `CanvasRooms` instance. A public `serve` wrapper tracks connection handlers so shutdown also cleans up in-flight handshakes; private helpers keep room behavior in `canvas_ws.py`, while pure validation lives in `canvas_protocol.py`. Independent Luna reviews found oversized-number parsing and handshake/shutdown cleanup errors; regression tests and boundary fixes resolve them. WS-04 implements transactional shape creation, exact retry acknowledgements, and ordered committed broadcasts; its independent review approved without confirmed bugs. WS-05 adds updates, soft deletes, and whole-shape revision conflicts through the shared transaction path. WS-06 adds tab-scoped presence joins/leaves and transient cursors through room queues. WS-07 adds connection-local navigation and transactional inverses in `canvas_history.py`. Room state records operation origins so another tab of the same user counts as a collaborator. WS-08 wires logout to exact-session revocation across canvases, rechecks access at subscription and incoming frames, and closes idle expired sessions on a one-second polling interval. Logout stops sender delivery and drains queued messages before returning.

## Open questions and risks

- Multi-process deployment requires a direct PostgreSQL listener endpoint and available connections for each process with local sockets. See the [cross-instance collaboration plan](CROSS_INSTANCE_PLAN.md) for lifecycle and validation details.
- Operation request/result records must remain available as long as retries are accepted. If operation history is pruned, the retry window needs an explicit limit.

## Verification status

All eight tickets are implemented. The integrated PostgreSQL-enabled backend suite passes 52 tests, including the two-account create/update/cursor/undo/redo/reconnect flow. Independent review of the remaining tickets is pending.
