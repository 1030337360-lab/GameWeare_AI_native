# System Design Notes

## Local Runtime

- React/Vite frontend runs on `http://localhost:1314`.
- FastAPI backend runs on `http://localhost:8080`.
- PostgreSQL and MinIO are started by `docker compose up -d`.
- MinIO stores local object data under `D:\yahaha`.

## Current MVP Flow

1. Home loads published sample games from `GET /games`.
2. Game detail pages read the selected game from the same catalog.
3. Play requests `GET /play/{game_id}/manifest`.
4. The backend returns an iframe-compatible HTML entry URL.
5. Create page submits to `POST /create/jobs`, which returns a stubbed job.

## Deferred Work

- Real authentication and sessions.
- PostgreSQL-backed models and migrations.
- MinIO-backed uploads and game bundles.
- Multi-agent generation and publishing.
