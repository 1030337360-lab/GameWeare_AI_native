# Yahaha MVP

Minimal runnable scaffold for an AI-native interactive game platform.

This build follows the technical route in `Yahaha-MVP-技术路线报告.md`:

- Frontend: React + Vite + TypeScript on port `1314`
- Backend: Python + FastAPI on port `8080`
- Local dependencies: PostgreSQL and MinIO via Docker Compose
- MinIO local storage path: `D:\yahaha`
- Create generation: intentionally stubbed, with API routes preserved

## Requirements

- Docker Desktop `28.3.3`
- Docker Compose integrated with Docker
- WSL enabled
- Node.js 24+
- Python 3.12+

## Start dependencies

```powershell
docker compose up -d
```

PostgreSQL listens on `localhost:5432`.
MinIO API listens on `localhost:9000`.
MinIO Console listens on `http://localhost:9001`.

## Start backend

```powershell
cd apps/api
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

On this Windows environment, do not use `--reload` for now. The reloader starts a watcher subprocess and can fail with `PermissionError: [WinError 5]` while creating a named pipe.

Health check:

```powershell
curl http://localhost:8080/health
```

Run backend smoke checks:

```powershell
.venv\Scripts\python tests\test_smoke.py
```

## Start frontend

```powershell
cd apps/web
Copy-Item .env.example .env
npm install
npm run dev
```

Open `http://localhost:1314`.

## Implemented API surface

- `GET /health`
- `GET /games`
- `GET /games/{game_id}`
- `GET /play/{game_id}/manifest`
- `POST /events/play`
- `GET /auth/session`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /create/jobs`
- `GET /create/jobs/{job_id}`
- `POST /create/jobs/{job_id}/publish`
- `POST /uploads`

## Current scope

The app is a minimum runnable project. It includes a game gallery, game detail pages, sandbox Play iframe, Docker dependencies, and preserved Create/upload/auth interfaces. Real authentication, database persistence, MinIO uploads, and multi-agent generation are intentionally left for the next implementation phase.
