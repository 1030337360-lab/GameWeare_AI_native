# API Notes

Backend base URL: `http://localhost:8080`

The current implementation is intentionally small and runnable. PostgreSQL is now the source of truth for published games, users, Create jobs, play events, and asset metadata. Redis stores active JWT records. MinIO is used by the upload endpoint. The full multi-agent generation worker is still deferred.

AI-generated game artifacts must follow `docs/ai-game-generation-guide.md`.

## Game APIs

- `GET /games`
- `GET /games/{game_id}`
- `GET /play/{game_id}/manifest`
- `POST /events/play`

Game list/detail and Play manifest are read from PostgreSQL. `POST /events/play` writes to `play_events`.

## Auth APIs

- `GET /auth/session`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/google/start`
- `GET /auth/google/callback`

Auth routes support email registration/login, Bearer JWT session lookup, logout, and Google OAuth route shape. The database also has `auth_accounts` so Google/GitHub OAuth can be added without changing `users`.

`POST /auth/register` and `POST /auth/login` return `accessToken`, `tokenType`, `expiresIn`, and `user`. Protected requests use `Authorization: Bearer <token>`.

## Create APIs

- `POST /create/jobs`
- `GET /create/jobs/{job_id}`
- `POST /create/jobs/{job_id}/publish`

Create jobs are persisted in PostgreSQL with an initial skipped `agent_runs` row. They prove the database contract and UI integration, but do not yet run the real generation worker.

## Upload APIs

- `POST /uploads`

Uploads write the file to MinIO and record an `assets` row with bucket, object key, public URL, content type, and size.
