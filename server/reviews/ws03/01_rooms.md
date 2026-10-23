# WS-03 room lifecycle review

## Verdict

Approve. The lifecycle issues found in the prior reviews have been addressed and their controlled-transport regressions pass. The current implementation keeps room membership changes under the room lock, avoids holding database connections for socket lifetimes, and awaits connection cleanup before room reclamation.

## Findings resolved

The first review found that `socket.accept()` ran outside the lease cleanup boundary. Cancellation could leave an empty room with `leases == 1`, and shutdown did not track or await a handshake in progress. `server/app/canvas_ws.py:403-416` now tracks the ASGI serving task; `_serve` wraps acceptance and all post-acquisition work in its room lease `try/finally` at lines 418-438. Shutdown cancels and awaits serving tasks before collecting rooms at lines 560-565. The controlled tests `test_cancelled_handshake_releases_its_room` and `test_shutdown_finishes_an_inflight_handshake` verify those cases.

The first review also found shutdown awaiting `socket.close()` before canceling sender tasks. `_shutdown()` now cancels and awaits senders before starting socket closes at lines 573-580, while `_close_socket()` applies a one-second timeout at lines 545-552. `test_shutdown_bounds_blocked_close_and_cleans_up_other_peers` verifies a blocked close does not hold shutdown or prevent other peers from being closed.

The second review found shutdown cancellation interrupting a serving task already in disconnect cleanup while it waited for `room.lock`, leaving the room lease at one. `_serve` now starts `_finish_connection()` as an owned cleanup task in its `finally` at lines 471-486. It shields that task and records cancellation, then re-raises only after cleanup completes. `_finish_connection()` cancels and awaits the sender, detaches under the room lock, releases the lease, and performs any required handshake close at lines 488-505. `test_shutdown_does_not_interrupt_disconnect_cleanup` reproduces the previously failing interleaving and asserts both the serving task is done and `_rooms` is empty.

## Verification and scope

Reviewed the WS-03 backend delta in `server/app/canvas_ws.py`, `server/app/main.py`, `server/tests/test_canvas_websocket.py`, and `server/WEBSOCKET_CONNECTIONS.md`, against committed HEAD `966d149` and `/tmp/ws03-baseline`. Read `server/WEBSOCKET_TICKETS.md`, `server/WEBSOCKET_DESIGN.md`, and `API.md`. Frontend and unrelated working-tree changes were excluded. No implementation or test source files were changed during this review.

Commands and results from `server/`:

- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws03_20261023 .venv/bin/python -m unittest tests.test_canvas_websocket.CanvasRoomLifecycleTests.test_shutdown_does_not_interrupt_disconnect_cleanup -v` — passed.
- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws03_20261023 .venv/bin/python -m unittest tests.test_canvas_websocket -v` — 9 tests passed.
- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws03_20261023 .venv/bin/python -m unittest discover -s tests -v` — 25 tests passed.
- `.venv/bin/ruff check app/canvas_ws.py app/main.py tests/test_canvas_websocket.py` — all checks passed.

The lifecycle regression coordinates disconnect and shutdown with events and a held room lock, not arbitrary sleeps. It passed with the current code and confirmed cleanup releases the lease before shutdown reclaims the empty room. Durable commands, presence broadcasts, cursor handling, and session revocation remain intentionally pending WS-04/06/08 and were not reviewed as defects.
