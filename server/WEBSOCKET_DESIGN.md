# Canvas WebSocket design

Implementation is broken into eight tickets in [WEBSOCKET_TICKETS.md](WEBSOCKET_TICKETS.md). Each ticket requires behavior tests before production implementation.

## Problem

`main.py` has a placeholder `/ws` route. The backend already has cookie sessions, canvas membership, an asyncpg pool, and tables for shapes and operations. The WebSocket needs one ordering rule across snapshot delivery, edits, and presence. The server targets one Uvicorn worker and 2–5 collaborators per canvas.

## Usage

`main.py` creates one `CanvasRooms` instance during startup and registers its router. The room owner handles a connection from authentication through disconnect. Logout calls its session-revocation hook after deleting the database session.

```python
rooms = CanvasRooms(pool, allowed_origins)
app.state.canvas_rooms = rooms
app.include_router(rooms.router)

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
    undo: list[UUID]
    redo: list[UUID]
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

The handler parses JSON into private Pydantic command types at the socket boundary. Command helpers accept those typed values. They validate shape properties by kind, check the expected shape revision, and write the shape, operation, and next canvas revision in one transaction. They return a typed outcome such as `Applied`, `Conflict`, or `Refused`.

Each room owns one lock. Snapshot loading and connection registration happen under that lock. Durable commands update PostgreSQL under the lock, commit, then enqueue the resulting event to each connection before releasing it. A per-connection sender drains a bounded outbound queue, so network writes never hold the room lock. A slow client is disconnected and reconnects with a fresh snapshot.

Connection state is keyed by `connection_id`, not user ID. Each tab therefore has its own cursor and undo/redo navigation. Room state is transient. PostgreSQL remains authoritative for shapes and operation history.

Authentication uses the existing session cookie and session lookup. The socket checks the configured `Origin`, session, and canvas membership before acceptance. Commands recheck session validity and membership. Logout closes all sockets for that session. An expiry task closes idle sockets when their session expires.

## Persistence change

`canvas_operation` now has JSONB `request` and `result` columns alongside its before and after patches. The fresh schema and `migrations/001_operation_replay.sql` require populated values to be objects and permit both to be null for legacy rows. The future command handler must populate both columns, compare the saved actor, canvas, and request on retry, and return the saved result for an exact retry. Reject reuse with different input and legacy IDs whose requests cannot be verified.

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

Candidate A's cohesive room owner is the base. It scored better on ordering ownership, session revocation, retry semantics, and interface depth. Candidate B's split modules would make the route coordinate locking, commands, and event delivery. Keep B's typed command outcomes and pure shape-transition helpers private inside `canvas_ws.py` until command logic earns a separate persistence boundary.

The independent cross-judge also recommended A. It identified two corrections included here: persist immutable request/result data for idempotent retries, and handle global operation-ID collisions across canvases. The judge also recommended one Uvicorn worker because in-memory rooms cannot coordinate across processes.

## Tradeoffs accepted

- The collaboration module owns transport lifecycle and command orchestration. This keeps ordering rules in one place, at the cost of a larger module.
- One Uvicorn worker owns room locks and broadcasts. PostgreSQL row locks alone cannot synchronize snapshots or presence across workers.
- Undo uses connection-scoped navigation and conservative shape-level conflict checks. Property-level undo remains out of scope.
- Slow peers reconnect after queue overflow. The server does not let a blocked socket hold a room lock.

## Alternatives considered

Separate `canvas_ws.py`, `realtime.py`, and `canvas_commands.py` modules. This makes each file smaller but exposes callback coordination across snapshot loading, locking, persistence, and broadcast. Keep this option for later if command code grows enough to sit behind one complete `apply` boundary.

An actor task and mailbox per canvas. This gives each canvas one writer, but adds task startup, cancellation, and request/reply lifecycle rules. A room lock and sender queue cover the current single-process workload with less machinery.

## Implementation reconciliation

WS-01 implements private command models, parsing, shape validation, and patch merging in `canvas_ws.py`. WS-02 implements replay columns and the rerunnable migration. WS-03 registers the canvas socket and implements authenticated snapshots, room leases, bounded outbound queues, and shutdown. The application lifespan owns one `CanvasRooms` instance. A public `serve` wrapper tracks connection handlers so shutdown also cleans up in-flight handshakes; private helpers retain protocol and room behavior in the same module. Independent Luna reviews found oversized-number parsing and handshake/shutdown cleanup errors; regression tests and boundary fixes resolve them. WS-04 implements transactional shape creation, exact retry acknowledgements, and ordered committed broadcasts; its independent review approved without confirmed bugs. WS-05 adds updates, soft deletes, and whole-shape revision conflicts through the shared transaction path. Presence/cursor broadcasts, history, and session revocation remain future work.

## Open questions and risks

- Deployment must use one Uvicorn worker. Multiple workers need cross-process pub/sub and coordinated snapshot subscription.
- Operation request/result records must remain available as long as retries are accepted. If operation history is pruned, the retry window needs an explicit limit.

## Next implementation step

Implement WS-06's presence and cursors alongside WS-07's connection-scoped history, then WS-08's session revocation.
