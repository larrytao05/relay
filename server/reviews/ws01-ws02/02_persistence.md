# WS-02 persistence review

## Verdict

No correctness or maintainability blocker found in the scoped WS-02 schema and migration. The fresh schema and upgrade migration use the same paired-null/object check: legacy rows may retain `(NULL, NULL)`, while populated request/result values must both be JSON objects. Existing rows are left intact. `ADD COLUMN IF NOT EXISTS` plus a constraint lookup scoped to the resolved table makes the migration rerunnable without introducing a migration framework.

## Schema and migration checks

- `schema.sql:66-67,82-89` and `migrations/001_operation_replay.sql:4-24` agree on nullable `jsonb` fields and paired nullability/object validation.
- The baseline comparison showed these are the only WS-02 additions to the operation table: `request`, `result`, and their check constraint.
- Migration README documents invocation from the server directory with `psql`, `ON_ERROR_STOP`, and the legacy-row behavior.
- The upgrade test starts from the current schema with only the new fields/constraint removed, seeds a legacy operation, runs the migration twice, checks that row remains null in both fields, and stores a new request/result record.
- Fresh-schema tests round-trip an exact delete result including revision and deletion state, and assert failures for arrays, scalar JSON, and unpaired nulls.

The migration test's pre-WS-02 table is reconstructed by removing the new columns from the fresh schema rather than loading a checked-in historical schema snapshot. Since the baseline diff confirms these are the only changes to this table and the test exercises preserved row data plus rerun behavior, this does not create a material confidence gap for this small migration.

## Verification

- `TEST_DATABASE_URL=postgresql://larrytao@127.0.0.1:5432/mechanize_ws01_ws02_20261023 .venv/bin/python -m unittest discover -s tests -v` — all three persistence tests passed as part of 15 total backend tests; zero skips. Each persistence test created and dropped a uniquely named schema in the dedicated test database.
- The reported pre-change failure was `UndefinedColumnError` before schema changes, which is meaningful evidence that the persistence behavior was not yet supported.
