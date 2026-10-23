# Database migrations

Docker Compose applies `schema.sql` and every SQL migration before it starts the
backend. The base schema and current migration are safe to rerun, so this also
repairs an existing volume that missed initialization. To apply the operation
replay migration manually from the `server` directory, run:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operation_replay.sql
```

The migration is safe to rerun and leaves existing operation rows intact. Rows
created before this migration keep `NULL` in both `request` and `result`; these
legacy operations cannot be verified as exact retries.
