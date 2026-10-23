# WS-03 review summary

**Verdict: approve.** The authenticated snapshot path and room lifecycle now satisfy the WS-03 requirements reviewed here. Origin, session, and membership are checked before acceptance; database connections are released after their queries; snapshots serialize JSONB properties and exclude soft-deleted shapes; the snapshot is queued first under the room lock; separate tabs retain separate connection IDs; and slow peers do not hold room locks.

The lifecycle fixes now cover the three races found during review: cancellation during handshake releases its room lease; shutdown waits for in-flight handshakes and bounds blocked transport closes; and shutdown cannot interrupt disconnect cleanup before detach and lease release. `_serve` owns a cleanup task, shields it while waiting, and propagates cancellation only after cleanup finishes. The new regression test reproduces the previously failing room-lock/disconnect/shutdown interleaving and passes.

The WebSocket lifecycle suite passes 9/9, the full DB-enabled backend suite passes 25/25, and scoped Ruff passes. The implementation remains within the intended cohesive room-owner module and below the 1,000-line threshold. WS-04/06/08 behavior was excluded as planned.

See [01_rooms.md](01_rooms.md) for the prior findings, how each was resolved, and exact verification commands.
