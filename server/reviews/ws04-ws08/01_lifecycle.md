# Lifecycle finding: broadcast overflow detaches but does not close the peer

**Status: confirmed by the broadcast call path; not yet fixed.**

In `server/app/canvas_ws.py`, `_enqueue_locked` detaches a connection when its outbound queue is full (lines 890–900). `_broadcast_locked` invokes it for every recipient but discards the boolean result (lines 902–910). Presence joins call `_broadcast_locked` directly at lines 362–373, and cursor updates do so at lines 477–486. Neither caller collects overflowed peers or invokes `_close_slow_connection` / `_stop_delivery` afterward.

The result is that a peer whose queue fills on a join or cursor event is removed from `room.connections` and gets one `presence.left`, but its WebSocket remains open and its sender task is not cancelled by this path. The receive loop only notices `connection.detached` when that client sends another frame; an idle client can therefore remain connected and retain its serving task, expiry task, and room lease. This contradicts WS-03/WS-06's requirement that queue overflow disconnect only the slow peer and keep lifecycle cleanup owned.

The shape and history command paths do collect failed enqueue targets and call `_close_slow_connection` after releasing the room lock (canvas_ws.py lines 507–529 and 543–571). The non-durable broadcast paths need equivalent ownership: have locked broadcast return the overflowed connections, then cancel delivery and close them outside the lock. Avoid awaiting socket operations while holding the room lock.

**Verification performed.** Inspected the overflow branch and each direct caller. Existing test `test_slow_peer_overflow_isolated_and_sends_do_not_hold_room_lock` exercises overflow from an applied shape command, which uses the separate collection-and-close path; it does not exercise overflow from presence or cursor broadcasts. Full test command from `server/`: `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws08_20261023 .venv/bin/python -m unittest discover -s tests -v` — 52 passed. Ruff: `.venv/bin/ruff check app tests` — all checks passed. Neither verifies this specific branch.
