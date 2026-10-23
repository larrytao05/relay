# WS-05 through WS-08 review

## Scope and paused verdict

Reviewed the WebSocket ticket implementation in the isolated checkout at `ab497db` against `WEBSOCKET_TICKETS.md`, `API.md`, and `WEBSOCKET_DESIGN.md`. The review covered WS-05 update/delete/conflict/replay behavior, WS-07 connection-scoped undo/redo and collaborator protection, WS-08 logout revocation/expiry/handshake admission, and integration-relevant WS-04 behavior. The known WS-06 overflow issue was reviewed in the frozen fix delta.

**Review paused on one confirmed shutdown-cleanup bug in the WS-06 fix.** The WS-05, WS-07, and WS-08 audit found no confirmed new blocker. No source or test files were changed.

## Evidence and behavior review

`CanvasRooms._apply_shape_command` checks persisted session and membership in the transaction, looks up operation replay before shape mutation, and commits the shape state, inverse patches, immutable request/result, operation record, and next canvas revision atomically. Updates merge only validated patch fields; stale revisions return the current whole shape; unavailable, deleted, and invalid-patch refusals leave durable state unchanged. The operation ID collision path rolls back before looking up a globally unique winning ID. Exact retries compare actor, canvas, and canonical request and return the original result only to the requester.

`apply_history_command` checks replay before navigation eligibility, then validates the target actor and connection-local stack position in the transaction. Its inverse patches are based on stored before/after values. The later-effect scan removes edits reversed by undo and restores them when redone, so an effective edit from another connection blocks the inverse while an undone collaborator edit does not. Room-local operation origins distinguish another tab of the same account. The reviewed cases included Alice A, Bob B, Alice C, undo C, then refusal to undo A.

Logout deletes only the exact session digest and then serializes revocation through each room lock. Durable commands and incoming cursor or malformed frames recheck persisted access. A handshake that overlaps logout either observes the deleted session at its in-lock recheck or registers under the room lock before revocation detaches it; logout does not return before that detachment and queued delivery shutdown. Idle expiry uses the recorded expiry with the documented one-second check interval. Shutdown and disconnect cleanup remain idempotent in the tested flows.

The room owner remains cohesive and the implementation decomposes pure validation and history primitives into `canvas_protocol.py` and `canvas_history.py`. `canvas_ws.py` was 978 lines before the overflow fix and is 1,005 lines after it. The small increase crosses the review skill's 1,000-line threshold. The fix adds one cohesive ownership ledger and its drain helper, with cleanup explicitly outside the room lock; the issue is that its batch ownership is not cancellation-safe, not that the code needs cosmetic reshaping to fall below the line threshold. The history helper's broad `object` annotations weaken static contracts, but I found no concrete maintenance failure from them in this review.

## Verification

In the isolated checkout at `ab497db`:

- The PostgreSQL-enabled backend suite passed all 52 tests against the dedicated `mechanize_wsreview_20261023` database.
- Ruff check passed for `app/canvas_ws.py`, `app/canvas_protocol.py`, `app/canvas_history.py`, `app/auth.py`, and `app/main.py`.
- Ruff format check reported all five files already formatted.

The fixer evidence reports the two overflow regression tests pass and the full 54-test suite plus Ruff pass. The root's independent full-suite rerun then failed `test_cursor_broadcast_overflow_closes_and_stops_slow_peer` at `assertFalse(healthy.sender_task.done())`; that failure is still under investigation and was not adjudicated in this review. I also ran a direct async ownership reproduction for the shutdown-cancellation issue below.

## Finding

In `app/canvas_ws.py:940-948`, `_close_broadcast_overflows` copies and clears the overflow map before awaiting slow-peer cleanup serially. If application shutdown cancels the serving task while the first peer is being closed, the remaining detached peers are no longer in `room.connections` or `room.broadcast_overflows`. `_shutdown` scans only those two collections at `app/canvas_ws.py:973-984`, so it misses the remaining peer and does not cancel its sender/expiry tasks or close its socket. I reproduced the ownership gap against main source with a direct async harness: cancellation after the first close started left `broadcast_overflows` empty and the second overflow socket's close count at zero. This violates the shutdown cleanup contract. Keep the batch visible to shutdown until each peer is fully cleaned, or make drain cancellation restore/requeue unprocessed peers before propagating cancellation; add a regression that cancels shutdown during a multi-peer drain and verifies every socket and owned task is stopped.

Final quality approval is paused pending correction of this issue and resolution of the independent full-suite test failure.

### Reproduction command

Scratch harness: `/tmp/ws06_shutdown_overflow_cancel.py` (not part of the repository). From `interview/server`, run:

```bash
PYTHONPATH="$PWD" .venv/bin/python /tmp/ws06_shutdown_overflow_cancel.py
```

It prints `{'overflow_map_empty': True, 'first_close_count': 1, 'second_close_count': 0, 'owner_done': True}`. The blocked first close ensures shutdown cancels the serving task after the whole batch has been removed from the room's overflow map but before the second peer is processed.
