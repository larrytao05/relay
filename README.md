# Relay

Relay is a collaborative whiteboard for small teams. Create canvases, invite teammates, and work through ideas together in real time. Canvas edits are saved to PostgreSQL, so the team can return to them later.

## Features

- Username and password accounts
- Create canvases and invite other users
- Add and edit rectangles, ellipses, lines, and text
- Move, resize, recolor, reorder, and delete shapes
- Undo and redo canvas changes
- See collaborators' cursors and live edits
- Persist canvases and membership in PostgreSQL

## Tech stack

- Frontend: React, TypeScript, and Vite
- Backend: FastAPI and Python
- Database: PostgreSQL
- Live collaboration: WebSockets, with PostgreSQL notifications for durable cross-instance updates
- Hosting: Vercel for the app and Neon for managed PostgreSQL

## Run locally

### With Docker Compose

Requirements: Docker with Compose.

From this directory, run:

```bash
docker compose up --build
```

Compose starts PostgreSQL, initializes the schema and migrations, and runs the API and frontend. Open [http://localhost:5173](http://localhost:5173).

### Without Docker Compose

Requirements: Node.js 22+, Python 3.12+, and a PostgreSQL database. The default local database URL is `postgres://whiteboard:whiteboard@localhost:5432/whiteboard`.

Initialize the database and start the API:

```bash
cd server
DATABASE_URL="${DATABASE_URL:-postgres://whiteboard:whiteboard@localhost:5432/whiteboard}"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql
for migration in migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"; done
pip install -e .
uvicorn app.main:app --reload --port 3001
```

In another terminal, start the frontend:

```bash
cd client
npm install
npm run dev
```

The Vite development server proxies `/api` and `/ws` to the backend on port 3001.

## Deploy

The repository includes a Vercel configuration for the React frontend and FastAPI backend. Connect the repository to Vercel and connect a PostgreSQL database such as Neon.

Run `server/schema.sql`, followed by each SQL file in `server/migrations/` in filename order, against the deployed database. The SQL files are safe to rerun.

Configure these backend environment variables in Vercel:

- `WEBSOCKET_ALLOWED_ORIGINS`: the app's public origin, including `https://` and without a trailing slash (for example, `https://relay.example.com`). For multiple origins, separate them with commas.
- `SESSION_COOKIE_SECURE`: set to `true` so session cookies are only sent over HTTPS.
- Database connection: the Neon Vercel integration can provide `STORAGE_DATABASE_URL`. The backend also recognizes `DATABASE_URL`. For a separate, direct connection used by the cross-instance notification listener, it recognizes `DATABASE_LISTENER_URL`, `DATABASE_URL_UNPOOLED`, and Neon’s `STORAGE_DATABASE_URL_UNPOOLED` or `STORAGE_POSTGRES_URL_NON_POOLING`. When no listener-specific URL is set, it uses the main database URL.

Redeploy after changing environment variables. The `/api` and `/ws` routes are routed to the FastAPI service by `vercel.json`.

## Project layout

```text
client/                 React application
server/app/              FastAPI routes and collaboration logic
server/schema.sql        Base PostgreSQL schema
server/migrations/       Incremental database changes
vercel.json              Vercel service and route configuration
docker-compose.yml       Local development environment
```
