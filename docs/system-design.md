# System Design Notes

## Local Runtime

- React/Vite frontend runs on `http://localhost:1314`.
- FastAPI backend runs on `http://localhost:8080`.
- PostgreSQL and MinIO are started by `docker compose up -d`.
- Redis is started by `docker compose up -d` and stores active JWT records.
- MinIO stores local object data under `D:\yahaha`.

## Current MVP Flow

1. Home loads published games from PostgreSQL through `GET /games`.
2. Game detail pages read the selected game from the same database-backed catalog.
3. Play requests `GET /play/{game_id}/manifest`.
4. The backend resolves the current game version and manifest/bundle assets from PostgreSQL.
5. Login/register returns a JWT. The web app stores it locally and sends it as a Bearer token.
6. Create page submits to `POST /create/jobs`, which requires the Bearer token and persists a generation job plus an initial Agent log row.
7. Uploads go to MinIO and are recorded in the `assets` table.

## Deferred Work

- Providing Google OAuth Client ID/Secret to make the implemented Google route run against a real Google app.
- Uploading generated game bundles to MinIO from the Publisher step.
- Multi-agent generation and publishing worker.
- Alembic migrations after the schema stabilizes beyond the SQL init scripts.
