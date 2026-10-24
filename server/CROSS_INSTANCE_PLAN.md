# Cross-instance collaboration plan

## Goal

Allow collaborators connected to different FastAPI processes to see the same committed canvas edits, presence changes, and session revocations. Keep PostgreSQL as the durable source for canvas state and operation history.

## Current constraints

- `CanvasRooms` keeps WebSocket connections, locks, presence, and cursors in process memory.
- The current deployment assumes one Uvicorn worker. Multiple workers do not share rooms or broadcasts.
- Shape commands update PostgreSQL transactionally, then broadcast to connections owned by that process.
- The first WebSocket message is a snapshot. Existing in-process room locking orders that snapshot with later local events.
- Presence and cursor state is intentionally transient and is not written to PostgreSQL.

## Chosen design

Use PostgreSQL for durable operations and as the notification transport. A committed operation record is the source of truth. `LISTEN` and `NOTIFY` wake processes that may have relevant collaborators connected, but notifications are not treated as a durable queue.

Each backend process starts one dedicated PostgreSQL listener as it admits its first local WebSocket. It keeps the listener while that process has local WebSocket connections, then closes it after the last connection leaves and a short configurable idle grace period expires. Each process tracks its own connections. No global worker or global active-session counter is required.

The listener uses a direct PostgreSQL session connection because `LISTEN` requires session state. The existing pooled connection remains responsible for ordinary queries and transactions. If Neon is selected, use its direct endpoint for this listener.

When a process receives an operation notification, it queries the durable operation journal for any missing revisions and delivers them to its local room connections in canvas revision order. It deduplicates already delivered revisions and fills gaps from PostgreSQL. This also recovers from listener disconnects, process restarts, and missed notifications.

On WebSocket admission, establish the listener before reading the canvas snapshot and revision watermark in the same repeatable-read transaction. Queue the snapshot first, then reconcile journal entries after that watermark before delivering newer notifications. Deduplicate by canvas revision so a notification racing with catch-up or an operation committed by the same process cannot reorder or duplicate an edit.

Use transient PostgreSQL notifications for presence joins, leaves, and session revocations. Include a source process ID and event ID so a process can ignore its own notification echo and consumers can deduplicate transient events. Keep cursor updates out of durable tables. Throttle cursor notifications and validate the expected two-to-five collaborator workload before adding a separate pub/sub service.

## Implementation sequence

1. **Confirm deployment prerequisites.** Verify that the chosen app runtime supports the project's long-lived WebSocket connections and that its network can reach a direct PostgreSQL endpoint. Keep the database on PostgreSQL 16. Record connection and compute limits for the selected provider.
2. **Add durable cross-process operation delivery.** Ensure each committed shape operation has enough persisted data for another process to construct the same client event. Publish a small notification containing identifiers and revision metadata in the same transaction as the operation. Do not put the full operation payload in `NOTIFY`.
3. **Add a process-local listener lifecycle.** Start one listener when a process gains its first socket, route notifications to local rooms, and stop it after the process loses its last socket and the idle grace period expires. Handle concurrent first and last connections without duplicate listeners or premature shutdown.
4. **Make snapshot admission and catch-up race-safe.** Subscribe before reading the snapshot and its revision watermark. Queue the snapshot first, replay journal entries after the watermark, then continue with live notifications. Recover gaps and duplicates using canvas revisions.
5. **Share transient presence and revocation.** Broadcast presence and throttled cursors to the relevant processes. Publish logout revocations after the session deletion commits so each process closes sockets for that exact session. Keep server-side session checks on incoming frames as the fallback if a notification is lost.
6. **Prove multi-process behavior.** Run two backend processes against one PostgreSQL database. Verify ordered edits, snapshot consistency during concurrent edits, reconnect catch-up after listener loss, presence and cursor delivery, exact-session logout, and listener shutdown after the last local socket closes.
7. **Enable multi-instance deployment.** Increase process or instance count only after the multi-process checks pass. Observe listener connection count, database compute time, reconnect rates, and notification-to-journal catch-up behavior under active and idle collaboration.

## Acceptance criteria

- Two collaborators connected to different backend processes see each committed operation once and in canvas revision order.
- A collaborator joining during an edit receives a consistent snapshot followed by every later committed operation.
- A disconnected listener catches up from the journal without losing durable edits.
- Presence, cursor updates, and exact-session logout reach the other active processes without making transient state durable.
- A process with no local WebSocket connections closes its listener after the idle grace period.
- The deployment can run more than one backend process without relying on shared in-process memory.

## Risks and boundaries

- PostgreSQL notifications can be missed during disconnection. The operation journal and revision-based catch-up are required for durable edits.
- A listener per active backend process uses database connections. Configure connection limits and make listener startup and shutdown idempotent.
- A long-lived listener may keep database compute active while collaboration sessions are active. Idle processes should close listeners so the database can suspend when there is no application activity.
- Cursor updates can be frequent. Throttle them and revisit the transport if the measured workload exceeds what PostgreSQL notifications handle well.
- Vercel hosting remains conditional on validating its WebSocket lifecycle and service runtime for this FastAPI app. Vercel's ability to deploy multiple services does not by itself establish that this long-lived connection model works there.

## Existing work

Validation, snapshot consistency, and logout/write ordering were completed in commit `4692013` (`Fix collaboration validation, snapshots, and logout ordering`). The current WebSocket implementation and its one-process assumptions are documented in [WEBSOCKET_DESIGN.md](WEBSOCKET_DESIGN.md). This plan covers the remaining cross-process work; it does not change code or deploy infrastructure.
