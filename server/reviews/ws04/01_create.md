# WS-04 create, replay, ordering, and lifecycle review

## Scope and verdict

Reviewed only the WS-04 delta in `server/app/canvas_ws.py` and new `server/tests/test_canvas_create.py`, against `server/WEBSOCKET_TICKETS.md`, `API.md`, `server/WEBSOCKET_DESIGN.md`, and baseline `c68f419` / `/tmp/ws04-baseline/canvas_ws.py`. Concurrent frontend, authentication, and unrelated endpoint-test edits were excluded. WS-05 through WS-08 were treated as pending.

**Verdict: approve.** No high-conviction bug or material maintainability regression found. `canvas_ws.py` is 807 lines, below the review skill's 1,000-line decomposition threshold. The implementation adds a focused create branch and private persistence helper without changing unrelated command behavior.

## Evidence reviewed

`_receive_loop` acquires the per-room lock around `_create_shape` and enqueues an applied event for all currently registered connections before releasing that lock. This preserves committed revision order for a canvas. The sender tasks continue to drain queues independently of the lock. Exact retries enqueue only to the requester and do not produce another room event.

`_create_shape` locks the canvas row and rechecks the exact session token digest, expiry, and membership before writing. Shape insert, revision increment, inverse patch, replay request/result, and journal row share one PostgreSQL transaction. Shape ID uniqueness is translated to a requester error. A global operation ID uniqueness failure exits the failed transaction before reading the winning record; request, actor, and canvas are compared before returning a saved result. Legacy rows with null replay data are refused as reused IDs.

## Verification

Commands run from `interview/server`:

- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws04_20261023 .venv/bin/python -m unittest tests.test_canvas_create -v` — 7 tests passed against PostgreSQL. Coverage includes all four shape kinds and reconnect snapshots; durable row/revision agreement; exact retry, changed payload and actor reuse; legacy operation refusal; shape ID collision; forced journal failure with rollback and later socket reuse; cross-canvas global operation ID collision; and per-canvas broadcast revision ordering/isolation.
- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws04_20261023 .venv/bin/python -m unittest tests.test_canvas_websocket.CanvasRoomLifecycleTests.test_slow_peer_overflow_isolated_and_sends_do_not_hold_room_lock -v` — passed. Queue capacity is one; overflow removes and closes the blocked peer while the healthy sender remains usable.

The forced-trigger test emits an expected PostgreSQL `RaiseError` stack trace in application logs while the assertion verifies `operation_failed` and complete rollback. This is expected test evidence, not a test failure. Root reports the full database-enabled suite passed 32/32 with scoped Ruff and formatting clean.

## Findings

None.

## Verification limit

The current worktree proves the post-change tests pass, but does not itself preserve the ticket's required failing-before test run. I did not treat that missing historical run record as a behavioral defect; it is a process evidence limit only.
