# WS-01 protocol review

## Finding history: large integer coordinates escaped the protocol error boundary — resolved

The initial finding was **Medium**. In the reviewed version, `_finite_number` accepted `int` values and immediately evaluated `float(value)`. Python raised `OverflowError` for values too large for a float, bypassing the parser's error normalization.

Root's remediation catches `OverflowError` around the float conversion and raises `ValueError`, which `_parse_client_message` normalizes to `InvalidMessage`. It also catches `ValueError` from `json.loads`; this handles Python's integer digit-limit exception for a 5000-digit literal. The new test, `test_rejects_oversized_json_numbers_with_normal_validation_error`, uses serialized JSON for a shape coordinate of `10**400`, cursor coordinate of `10**400`, and a 5000-digit integer. It asserts the stable `invalid_message` code and safe operation ID behavior. Root reported these cases failed before the fix, and I verified they pass after it.

## Test coverage and process

`test_canvas_protocol.py` covers all four create kinds, command examples, malformed JSON, UUID/revision validation, nonfinite float geometry, unknown fields, and merged patch behavior. It does not cover oversized integers, which is why the escape was missed. The user's reported pre-change run failed at import because `app.canvas_ws` was absent. This demonstrates the module was not yet present, but it does not meet the ticket's stricter requirement to record the new behavior assertions failing against a runnable fixture. The limitation should be noted rather than described as a full behavior-level red run.

The implementation remains small and stays in the parser boundary. Shape-specific validation is centralized in `_validate_shape_properties` and `_merge_shape_patch`; I found no unjustified helper layer or file-size concern. The earlier Ruff findings are resolved: imports are sorted and wrong-type branches use `TypeError`, which `_parse_client_message` catches and maps to the same `invalid_message` result. No regression from those changes was observed.

## Verification

- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws01_ws02_20261023 .venv/bin/python -m unittest tests.test_canvas_protocol -v` — 7 passed.
- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws01_ws02_20261023 .venv/bin/python -m unittest discover -s tests -v` — 16 passed, zero skipped.
- `.venv/bin/ruff check app/canvas_ws.py tests/test_canvas_protocol.py tests/test_canvas_persistence.py` — all checks passed.
