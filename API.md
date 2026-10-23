# Whiteboard API contract

This is the API contract. `GET /health`, authentication, canvas management, and authenticated WebSocket snapshots are implemented. Shape commands, undo/redo, and presence/cursor broadcasts remain planned.
Use HTTP for accounts and canvas membership, and one WebSocket per open canvas for edits and presence.

## HTTP endpoints

All paths except `/health`, signup, login, and idempotent logout require an unexpired session cookie.
Public user objects contain `id` and `username`. Password hashes and session tokens are never returned in JSON.

| Method | Path | Request | Success |
| --- | --- | --- | --- |
| GET | `/health` | None | `200 {"ok": true}` after checking the database. |
| POST | `/api/auth/signup` | `{username, password}` | `201 {user}` and a new session cookie. |
| POST | `/api/auth/login` | `{username, password}` | `200 {user}` and a new session cookie. |
| POST | `/api/auth/logout` | None | `204`, delete the session, clear its cookie, and close its open canvas connections. Repeated logout also returns `204`. |
| GET | `/api/auth/me` | None | `200 {user}` for the current session. |
| GET | `/api/canvases` | None | `200 {canvases: [...]}` containing only canvases the user belongs to. |
| POST | `/api/canvases` | `{title}` | `201 {canvas}`. Create the canvas and its creator's membership in one transaction. |
| GET | `/api/canvases/{canvas_id}` | None | `200 {canvas, members}` for a member. Shapes arrive in the WebSocket snapshot. |
| POST | `/api/canvases/{canvas_id}/members` | `{username}` | `200 {user}`. Immediately add an existing account by normalized username. Repeated requests have the same result. |

The member endpoint grants access immediately for this simple version. A future pending-invitation flow can add an invitation inbox and accept/decline endpoints; recipients do not need to accept membership in the current version.

Canvas objects contain `id`, `title`, `created_by`, `revision`, `created_at`, and `updated_at`.
Normalize usernames with whitespace trimming and lowercase conversion. Accept 3-32 ASCII letters, digits, underscores, or hyphens.
Passwords contain 8-128 characters and are not trimmed. Trim titles and require 1-120 characters.

Use an opaque random `session` cookie with `HttpOnly`, `SameSite=Lax`, and `Path=/`; set `SESSION_COOKIE_SECURE=true` when serving over HTTPS so the cookie receives the `Secure` flag. Store only its SHA-256 digest in `auth_session`; sessions expire after 14 days.
The HTTP client sends credentials with requests.
Allow only the configured frontend origins for credentialed CORS and WebSocket handshakes.
Require an allowed origin on state-changing browser requests. Authentication and membership also apply to every canvas command.

Use FastAPI's normal `detail` error field. Expected statuses are `401` for a missing, expired, or invalid session; `404` for an unavailable canvas or unknown invitee; `409` for a duplicate username; and `422` for invalid input.
Return the same login error for unknown usernames and incorrect passwords.

## Canvas WebSocket

Connect to `/ws/canvases/{canvas_id}` using the same cookie. Authenticate and check membership before accepting the connection.
The existing Vite `/ws` proxy supports this path.

The first server message is a `snapshot` containing the canvas, its `canvas_revision`, all visible shapes, current presence, and this connection's `connection_id`.
The snapshot's `connections` list includes each active connection, including this tab, with `connection_id`, public `user`, and `cursor`. Cursor positions remain null until cursor handling is implemented.
Subscribe and load the snapshot under the same canvas queue used for edits so that an update cannot disappear between those steps.
Reconnect by obtaining a fresh snapshot.

WS-03 currently returns `invalid_message` for invalid frames and `feature_not_available` for valid commands in the table below. The remaining tickets add those commands. Origin configuration and the single-worker deployment requirement are documented in [WEBSOCKET_CONNECTIONS.md](server/WEBSOCKET_CONNECTIONS.md).

| Client message | Fields besides `type` | Effect |
| --- | --- | --- |
| `shape.create` | `operation_id`, `shape_id`, `kind`, `properties` | Add one shape. Client-generated UUIDs identify the operation and shape. |
| `shape.update` | `operation_id`, `shape_id`, `expected_revision`, `patch` | Change position, size, color, or text. Send only the properties being changed. |
| `shape.delete` | `operation_id`, `shape_id`, `expected_revision` | Soft-delete a shape so undo can restore it. |
| `undo` | `operation_id`, `target_operation_id` | Reverse the user's latest eligible acknowledged edit using server-recorded values. |
| `redo` | `operation_id`, `target_operation_id` | Reverse the user's latest eligible undo. The target is that undo operation's ID. |
| `cursor` | `position: {x, y}` or `position: null` | Broadcast this connection's cursor or hide it. Do not write a database row. |

`expected_revision` is the shape's revision, not the canvas revision.
An update or delete with a stale revision returns a conflict and the current shape. It does not replace collaborators' newer state.
The client reconciles that state before another attempt. Property-level conflict merging can be added behind the same update message later.

Operation IDs identify retries. An identical retry from the same actor receives its original acknowledgement without reapplying the edit.
Reject reuse of an ID for a different command or actor. Derive actor and canvas IDs from the authenticated connection.

| Server message | Contents |
| --- | --- |
| `snapshot` | Initial document and presence as described above. |
| `operation.applied` | `operation_id`, `actor_id`, `kind`, `target_operation_id`, `canvas_revision`, and the resulting shape, including its revision and deletion state. Send to all canvas connections, including the sender. |
| `cursor` | `connection_id`, `user_id`, and `position`. Multiple tabs have distinct connection IDs. |
| `presence.joined` | The connection and public user that joined. |
| `presence.left` | The connection that disconnected. Remove its cursor. |
| `error` | The request's `operation_id` when present, `code`, and `message`; include the authoritative shape for a conflict. |

Durable commands run in a canvas-scoped queue. One database transaction updates the shape, inserts `canvas_operation`, and increments the canvas revision.
Capture inverse patches on the server. Broadcast only after commit, in revision order. Clients replace local canonical shapes with the acknowledged results.
An operation error leaves durable state and the canvas revision unchanged.

Undo and redo are per user, never a whole-canvas snapshot restore. They must check later edits before applying an inverse and refuse a conflicting undo rather than erase another user's work.
The initial implementation may conservatively reject undo after any later edit to that shape; allowing undo across unrelated property changes requires additional provenance checks.
Keep undo navigation stacks scoped to the user's current canvas connection. Canvas contents persist across sessions; undo stacks do not need to.

A drag should create one undo entry. Local drag previews can render immediately; a later transient `shape.preview` message can show movement to peers without persisting every pointer event.
Persistent shape writes, including undo and redo, use the WebSocket command handler. Do not add a second set of HTTP shape-mutation routes.

## Build order

1. Implement signup, login, logout, and current-user lookup.
2. Implement canvas creation, listing, opening, and invitations.
3. Implement the authenticated canvas socket, snapshots, and shape commands.
4. Implement presence, cursors, and per-user undo and redo.
