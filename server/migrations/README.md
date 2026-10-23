# Database migrations

Docker Compose applies `schema.sql` and every SQL migration before it starts the
backend. The base schema and migrations are safe to rerun, so this also repairs
an existing volume that missed initialization. To apply the canvas invitation
migration manually from the `server` directory, run:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_canvas_invitations.sql
```

The operation replay migration leaves existing operation rows intact. Rows
created before it keep `NULL` in both `request` and `result`; these legacy
operations cannot be verified as exact retries.
