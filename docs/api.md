# API Notes

Backend base URL: `http://localhost:8080`

The current implementation is intentionally small and runnable. It keeps the Create and upload interfaces so the real generation pipeline can be added without changing frontend routes.

## Game APIs

- `GET /games`
- `GET /games/{game_id}`
- `GET /play/{game_id}/manifest`
- `POST /events/play`

## Auth APIs

- `GET /auth/session`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`

Auth routes currently return an unauthenticated stub response.

## Create APIs

- `POST /create/jobs`
- `GET /create/jobs/{job_id}`
- `POST /create/jobs/{job_id}/publish`

Create jobs are in-memory stubs. They prove API shape and UI integration, but do not run real generation.
