# WebSocket implementation tickets

These tickets implement the backend design in [WEBSOCKET_DESIGN.md](WEBSOCKET_DESIGN.md) and the messages in [API.md](../API.md). Accounts and canvas management already exist. Frontend drawing interactions and socket wiring are separate work.

WS-01 through WS-07 are implemented. Tests cover protocol validation, replay storage, database upgrades, authenticated snapshots, connection cleanup, durable shape creation, updates, soft deletes, and conflicts. Independent reviews are recorded in [reviews/ws01-ws02/summary.md](reviews/ws01-ws02/summary.md), [reviews/ws03/summary.md](reviews/ws03/summary.md), and [reviews/ws04/summary.md](reviews/ws04/summary.md). WS-08 remains unimplemented. Further review is deferred until all remaining tickets are implemented.

## Build order

Work through the tickets in this order. Each ticket ends with working behavior that later tickets can use.

| Ticket | Deliverable | Depends on |
| --- | --- | --- |
| WS-01 | Validated messages and shape properties | None |
| WS-02 | Stored requests and original results for retries | None |
| WS-03 | Authenticated rooms, snapshots, and connection lifecycle | WS-01 |
| WS-04 | Shape creation, persistence, and ordered broadcast | WS-02, WS-03 |
| WS-05 | Shape updates, soft deletes, and conflicts | WS-04 |
| WS-06 | Presence and cursors | WS-03 |
| WS-07 | Connection-scoped undo and redo | WS-05 |
| WS-08 | Logout revocation and session expiry | WS-03, WS-06 |

WS-06 can follow WS-03 if seeing multiple cursors is useful before shape editing. Keep one implementation owner while the tickets share `canvas_ws.py`.

## Test-first rule for every ticket

Before changing production behavior for a ticket:

1. Write its focused behavior tests. Add only the fixture or callable signatures necessary to run them.
2. Run the new tests and record the expected failure. A missing dependency, unavailable database, or broken fixture does not count as evidence.
3. Implement the smallest change that makes those tests pass.
4. Rerun the new tests and the existing backend suite. Keep the failing-before and passing-after results in the completion summary.

Use the existing `unittest`, FastAPI `TestClient`, and `asyncpg` setup. Use unit tests for parsing and pure transitions. Use a separate PostgreSQL test database for migrations, transactions, and socket flows. Do not model SQL behavior with a growing in-memory database fake.

Reuse small fixtures for accounts, membership, canvases, and socket connections. Seed only test-owned data and clean it up. Give receives and joins bounded timeouts. Use events or barriers to coordinate race tests; do not depend on arbitrary sleeps. Integration tests may be skipped during ordinary discovery when `TEST_DATABASE_URL` is absent, but a skipped required test does not complete its ticket.

From `interview/server`, with the server environment activated:

```bash
python -m unittest discover -s tests -v
```

Run database tests with `TEST_DATABASE_URL` pointing at a separate database initialized with `schema.sql` and any required migration. Do not point test cleanup at the application's database.

## WS-01: Define and validate socket messages

**Goal.** Convert untrusted JSON into typed commands with one stable contract.

**Scope.** Add private command models and parsing helpers in `app/canvas_protocol.py`. Handle `shape.create`, `shape.update`, `shape.delete`, `undo`, `redo`, and `cursor`. Match the field names in `API.md`. Parse UUIDs, require positive expected revisions, reject unsupported message types and unknown fields, and reject malformed JSON. Actor, session, and canvas identity come from the connection.

Use these shape properties:

| Kind | Required properties |
| --- | --- |
| Rectangle or ellipse | `x`, `y`, `width`, `height`, `color` |
| Line | `x1`, `y1`, `x2`, `y2`, `color` |
| Text | `x`, `y`, `width`, `height`, `text`, `font_size`, `color` |

Coordinates must be finite numbers. Dimensions and font size must be positive finite numbers. Colors use `#RRGGBB`. Text is a plain string of at most 10,000 characters. An update patch must be nonempty and may change only properties for the stored shape kind. Validate the merged shape when applying a patch. A text update replaces the entire string.

**Write tests first.** Add `tests/test_canvas_protocol.py` with a small parameterized matrix:

- Valid create messages cover all four kinds. Other command examples cover update, delete, undo, redo, cursor position, and cursor hiding.
- Invalid cases cover an unknown type, malformed UUID, invalid revision, nonfinite geometry, invalid dimensions, and an unexpected property.
- A partial update preserves omitted properties. Invalid merged shape properties are rejected.

**Acceptance criteria.** Valid messages produce typed commands. Invalid input produces a consistent `invalid_message` error with the operation ID when it can be safely parsed. No parsing helper reads or writes the database. Later tickets must keep the connection usable after ordinary validation errors.

## WS-02: Preserve request identity and original acknowledgements

**Goal.** Store enough information to recognize an exact retry and return its original result.

**Scope.** Add JSONB `request` and `result` fields to the fresh `canvas_operation` schema and add `migrations/001_operation_replay.sql` for an existing schema. Both fields hold JSON objects. The request stores the parsed command in canonical form. The result stores the original `operation.applied` payload, including the resulting shape and revisions. Actor and canvas remain separate columns.

Make the migration safe to rerun. Preserve existing rows. Legacy rows may have both fields null; enforce paired nullability and object types for populated values. New WebSocket operations must populate both. A retry matching a legacy operation cannot be proven identical and must return `operation_id_reused` without mutation. Do not guess its result.

**Write tests first.** Add real-Postgres tests in `tests/test_canvas_persistence.py`:

- A fresh schema stores and retrieves a canonical request and its exact result, including deletion state and revisions. Invalid JSON shapes fail database constraints.
- Upgrading a schema with an existing operation preserves that row. Applying the migration twice succeeds. New operations can store request/result data after upgrade.

**Acceptance criteria.** Both fresh setup and upgrade support replay records without deleting data. Document the migration command. Do not add a second migration framework. Runtime replay behavior belongs to WS-04 and WS-05.

## WS-03: Connect to a room and receive a consistent snapshot

**Goal.** An authorized browser opens its canvas socket and receives the current document as its first message.

**Scope.** Implement `CanvasRooms.serve`, room and connection state, a single sender per socket, and cleanup in `app/canvas_ws.py`. Replace the `/ws` placeholder with `/ws/canvases/{canvas_id}`. Create and close the room manager in the application lifespan. Reuse session authentication and check membership before acceptance. Add a configured WebSocket origin allowlist that matches the actual local frontend origin.

Use one lock per canvas. Under that lock, read canvas metadata and visible shapes, enqueue the snapshot, and subscribe the connection. Include `connection_id`, `canvas_revision`, and existing connections with their public user and latest cursor. Keep connections separate for multiple tabs. Never retain a database connection for the socket's whole lifetime.

Use bounded outbound queues. Enqueue under the room lock and send outside it. Disconnect a peer that cannot keep up. Remove an empty room after all join, command, and cleanup work has finished; never allow two active locks for the same canvas. Shutdown closes sockets and awaits owned sender tasks.

**Write tests first.** Add `tests/test_canvas_websocket.py`:

- A seeded canvas opens with matching metadata, revision, and visible shapes. Soft-deleted shapes are absent. The first frame is always `snapshot`.
- Missing or expired sessions, a nonmember, and a disallowed origin fail before any snapshot or canvas data is sent. Use a short parameterized access matrix.
- Two tabs have distinct connection IDs. Disconnecting one leaves the other usable. A different canvas has an independent room.
- A blocked sender cannot block another peer. Queue overflow removes only the slow peer. Shutdown finishes without leaving connection tasks running. Use a controllable transport double for these lifecycle cases.

**Acceptance criteria.** The route is registered, authenticated snapshots work against Postgres, and ordinary disconnects clean up once. This ticket supplies current presence in snapshots; join/leave notifications arrive in WS-06. WS-05 adds the snapshot-versus-edit race test once durable edits exist. Document the single-worker deployment requirement.

## WS-04: Create shapes and broadcast committed operations

**Goal.** One member creates a shape; every member receives the same committed result, and reconnecting reloads it.

**Scope.** Implement `shape.create` under the room lock. In one database transaction, lock the canvas row, confirm the session and membership, insert the shape at revision 1, record server-derived inverse data plus the request/result, and advance the canvas revision once. Broadcast after commit to all room connections, including the sender. Reject shape ID reuse without changing data.

Look up operation IDs before applying a command. An identical request from the same actor and canvas returns the saved result only to its requester. It causes no second write, broadcast, or history entry. Reuse with different input, actor, or canvas returns `operation_id_reused`. Handle global ID collisions across different canvas locks by rolling back the losing transaction and checking the winning operation.

**Write tests first.** Extend the socket and persistence tests:

- Two members receive the same create result. Database shape, operation, and canvas revision agree. Reconnect loads the new shape. Parameterize the four shape kinds.
- An exact retry returns the original result with one durable operation and no second peer event. Changed payload, actor, or canvas reuse is rejected. Race two canvases using the same operation ID and verify that only one succeeds.
- A forced operation-insert failure rolls back the shape and canvas revision and emits no applied event. Keep the peer connection usable for a subsequent valid command.
- Concurrent independent creates reach both peers in the same increasing canvas-revision order. A third connection on another canvas receives neither event.

**Acceptance criteria.** Persistence and event delivery agree. No failed transaction is broadcast, exact retries have no extra effects, and rooms never cache the authoritative document. Store committed operation references for history; navigation behavior is added in WS-07.

## WS-05: Update and delete shapes with conflict handling

**Goal.** Members can move, resize, recolor, replace text, and delete shapes without silently accepting stale edits.

**Scope.** Implement `shape.update` and `shape.delete` through the same transaction and broadcast path as create. Compare `expected_revision` with the stored shape revision atomically. Update only requested properties. Soft-delete rather than remove rows. Each successful command advances shape and canvas revisions once and stores its inverse and immutable result.

Return `conflict` with the current shape, including deletion state, for a stale revision. Return `shape_unavailable` for an unknown shape or a shape belonging to another canvas; do not expose another canvas's data. Updating or deleting an already deleted shape with its current revision returns `shape_deleted`. A conflict or refusal is sent only to the requester and has no durable effects.

**Write tests first.** Extend `tests/test_canvas_websocket.py`:

- A partial update preserves other properties. A delete hides the shape on reconnect while retaining its row and operation data. Other peers receive both committed results.
- Two clients update the same revision concurrently. Exactly one succeeds; the other receives the authoritative conflict. Repeat for update-versus-delete.
- Invalid patches, unknown shapes, foreign-canvas shape IDs, and edits to deleted shapes leave shapes, journal, and canvas revision unchanged. A valid command still works afterward.
- Retry an earlier successful update after a later edit. The reply contains its original result, while the database and peer remain at the later revision.
- Coordinate a join and an edit at the snapshot boundary. The joiner either sees the edit in its snapshot or receives the edit afterward, exactly once, with no gap or event before its snapshot.

**Acceptance criteria.** Whole-shape optimistic concurrency is enforced consistently. Property merging and text collaboration are out of scope. A nonempty valid patch is an accepted operation even if its values equal the stored values. A client must not apply a replayed old revision over newer canonical state; record that requirement in `API.md` for frontend integration.

## WS-06: Broadcast presence and cursors

**Goal.** Members see each active tab and its latest cursor only while that connection is present.

**Scope.** Broadcast `presence.joined`, `presence.left`, and `cursor` using the existing room owner and outbound queues. Derive identity from the connection. Cursor coordinates use canvas coordinates. `position: null` hides the cursor. Send cursor events to other connections on the same canvas. Presence changes do not include the recipient's own join event.

Snapshots include the latest cursor of existing peers. Disconnect removes one connection and emits one leave event, including on send failure. Do not persist presence or cursor events and do not advance canvas revisions.

**Write tests first.** Add two focused multi-connection flows:

- A second connection appears in the first peer's presence feed and sees the first peer in its snapshot. Movement and cursor hiding reach peers with the correct connection/user IDs. A later join sees the latest cursor. Another canvas receives nothing.
- Two tabs for one user remain distinct. Disconnecting either removes only that tab and emits one leave. Cursor and presence traffic leaves database shapes, operations, and revisions unchanged.

**Acceptance criteria.** Cursor markers can be drawn and removed using only server messages. No durable rows are added. This ticket does not add drag previews, selections, or frontend rendering.

## WS-07: Implement undo and redo without erasing collaborators

**Goal.** Each connection reverses its own acknowledged actions while protecting later collaborator edits.

**Scope.** Keep undo/redo navigation per connection and persist each accepted inverse as a new operation. Undo must target that connection's latest eligible action. Redo must target its latest eligible undo operation. Validate ownership and history on the server. Replays must be recognized before history eligibility checks and must not modify navigation again.

Use server-recorded before/after values. Undoing create soft-deletes; undoing delete restores; undoing update restores its changed values. Normal accepted edits clear redo. Refused operations leave navigation unchanged. Reconnect starts with empty navigation and keeps document contents.

Allow consecutive undos/redos on the same shape when only that connection's reversed actions intervene. Refuse an inverse if a later, still-effective edit from another connection touched the shape. For this first version, refuse even when that collaborator changed a different property. Another tab counts as another connection, even for the same account.

A check against the original target's shape revision alone is insufficient because the first undo increments that revision. Implement the history guard around the behavior below, rather than disabling the guard to allow repeated undo.

**Write tests first.** Add `tests/test_canvas_history.py` using pure transition tests where practical and real socket/Postgres tests for durable outcomes:

- Create, update, and delete each undo and redo correctly. Each accepted inverse advances revisions, records its target, and reaches peers.
- Create a shape, move it twice, undo both moves, then redo both. Verify every intermediate state. A new edit after undo clears redo.
- Another connection edits the shape after the target action; undo is refused without erasing its change. Also cover Alice action A, Bob action B, Alice action C, undo C, then attempt undo A: B must remain protected.
- Cross-user targets, another tab's targets, and out-of-order targets are refused. Reconnect has no history. Retrying an accepted undo returns its original acknowledgement without changing state or navigation twice.

**Acceptance criteria.** Undo/redo works repeatedly, remains connection-scoped, and never restores a whole-canvas snapshot. One completed drag must be one durable update, so frontend drag integration later sends one final update instead of a write on every pointer event.

## WS-08: Revoke live sessions and verify the complete flow

**Goal.** A socket stops receiving or changing canvas data when its browser session is logged out or expires.

**Scope.** Wire logout to `CanvasRooms.revoke_session` after deleting the session row. Find all connections for that token digest, across canvases. Close those connections and emit their leave events once. Keep other sessions for the same user active. Never store the raw cookie token in room state.

Close idle connections at their recorded session expiry. Recheck the database session and membership before handling incoming commands, including cursors, so revoked credentials cannot keep using an established socket. Serialize revocation with room command admission. An already-admitted command may finish before revocation acquires the room lock; once logout returns, the revoked connection must be detached and no later command or room event may reach it.

**Write tests first.** Extend the real HTTP/WebSocket integration suite:

- One session opens two canvases; another session for the same account also connects. Logout closes only the first session's sockets. Peers see one leave per closed connection. The other session can still edit.
- A short-lived session expires while idle and closes within the documented expiry-check interval. Use a controllable clock or expiry scheduling helper rather than a long wait.
- Delete a session row after connection, then send a command. The socket closes with no write or cursor broadcast. Coordinate a logout-versus-command race and verify that nothing is accepted after logout returns.

Run one final flow through existing test helpers: two accounts join, create/update a shape, observe cursor traffic, undo/redo, disconnect, reconnect, and verify the persisted document. Reuse prior assertions rather than adding a second comprehensive suite.

**Acceptance criteria.** Logout's documented live-socket behavior is implemented. Expiry, disconnect, and shutdown cleanup are idempotent. Run all backend tests with the real database cases enabled. Update `API.md` and `WEBSOCKET_DESIGN.md` to match the implemented origin policy, errors, expiry interval, and any accepted design changes.

## Completion checklist

For each ticket, record the new tests, their expected initial failure, the final passing run, and any unfinished acceptance criterion. Keep frontend files outside these backend tickets. Use one Uvicorn worker. Run the final shared flow with two real WebSockets and PostgreSQL before declaring the collaboration backend complete.

## Implementation evidence

| Ticket | Failing before implementation | Passing after implementation | Review |
| --- | --- | --- | --- |
| WS-04 | Create commands returned `feature_not_available` in the new socket tests. | 7 create tests; 32 backend tests with PostgreSQL enabled. | Approved by an independent Luna reviewer. |
| WS-05 | Update/delete commands returned `feature_not_available`; concurrent edits produced zero accepted operations. | 5 edit tests; 37 backend tests with PostgreSQL enabled; Ruff and formatting passed. | Deferred until all tickets are implemented. |
| WS-06 | Presence tests timed out waiting for the missing `presence.joined` event. | 28 isolated tests; 40 tests after integration with WS-05, PostgreSQL enabled; Ruff and formatting passed. | Deferred until all tickets are implemented. |
| WS-07 | Undo/redo returned `feature_not_available` in six new socket test methods. | 7 focused history tests; 47 integrated backend tests with PostgreSQL enabled; Ruff and formatting passed. | Deferred until all tickets are implemented. |
