# WS-01 / WS-02 review

**Updated verdict: Approve.** WS-02 passed the original review. Root's remediation resolves the WS-01 parser boundary bug: oversized numbers now become `InvalidMessage` responses, and regression coverage includes large shape/cursor values plus Python's JSON integer digit limit. The remaining note is process-only: the original WS-01 pre-implementation run failed at module import rather than on runnable behavior assertions.

## Findings

1. **Resolved — WS-01 parser leaked `OverflowError` for large JSON integers.** The initial review reproduced shape and cursor coordinates escaping `_parse_client_message`. The fix now catches overflow in `_finite_number` and maps it through `InvalidMessage`; `json.loads` also maps its `ValueError` for over-limit integer literals. The added regression test passes all three serialized-JSON cases. Evidence is in [01_protocol.md](01_protocol.md).

2. **Process note — WS-01 test-first evidence did not demonstrate per-case red behavior.** The reported pre-implementation run failed because `app.canvas_ws` did not exist, so it showed the feature module was absent but did not exercise focused assertions against callable parsing behavior. The ticket's global test-first contract says missing setup/dependency failures do not count as expected failure evidence. The regression test now demonstrates the original bug when run before the fix (as root reported) and passes after it, but this does not retroactively change the original test-first evidence. WS-02 had a meaningful `UndefinedColumnError` before its schema change. Details are in [01_protocol.md](01_protocol.md).

## Verification after remediation

- Focused protocol tests: 7 passed.
- Full backend suite with the dedicated Postgres test database: 16 passed, zero skipped.
- Ruff on the scoped Python implementation and tests: all checks passed. Imports are sorted and wrong-type paths use `TypeError`, which the parser catches and normalizes.

WS-02 detail: [02_persistence.md](02_persistence.md). No production or test files were modified during this review.
