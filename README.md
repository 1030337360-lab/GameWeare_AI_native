# Yahaha MVP

Minimal runnable scaffold for an AI-native interactive game platform.

This build follows the technical route in `Yahaha-MVP-技术路线报告.md`:

- Frontend: React + Vite + TypeScript on port `1314`
- Backend: Python + FastAPI on port `8080`
- Docker startup: Web, API, PostgreSQL, MinIO, and Redis via Docker Compose
- Local development startup: PostgreSQL, MinIO, and Redis via Docker Compose; Web/API run on the host
- MinIO storage: Docker named volume `minio_data` in the full Docker stack; local development can override MinIO storage through Compose volumes
- Create generation: real LLM generation by default; static test generation is available only when `CREATE_STATIC_GENERATION=true`

## Requirements

For Docker startup:

- Docker Desktop `28.3.3` or newer
- Docker Compose integrated with Docker
- WSL enabled on Windows

For local development startup:

- Docker Desktop and Docker Compose for PostgreSQL, MinIO, and Redis
- Node.js 24+
- Python 3.12+
- Git, if you want real Create worktree isolation with `CREATE_WORKTREE_ENABLED=true`

## Startup Option A: Full Docker Stack

Use this path when another person wants to run the whole project without installing Python or Node locally.

```powershell
git clone https://github.com/1030337360-lab/yahaha-mvp.git
cd yahaha-mvp
docker compose up -d --build
```

This starts:

| Service | Port | Purpose |
| ------- | ---- | ------- |
| `web` | `1314` | React production build served by Nginx |
| `api` | `8080` | FastAPI backend |
| `postgres` | `5432` | PostgreSQL database; runs `apps/api/db/init/*.sql` on first volume creation |
| `minio` | `9000`, `9001` | Object storage API and Console |
| `redis` | `6379` | Auth/session cache, Create state, SSE pubsub, play stat buffers |

Open:

```text
Web: http://localhost:1314
API health: http://localhost:8080/health
MinIO Console: http://localhost:9001
```

Default local MinIO credentials are `minioadmin` / `minioadmin`.

The Docker stack uses Docker named volumes:

| Volume | Purpose |
| ------ | ------- |
| `postgres_data` | PostgreSQL data |
| `minio_data` | MinIO object storage |
| `api_worktrees` | Create isolated workspace/stub files |

Docker-specific notes:

- The web image is built with `VITE_API_BASE_URL=http://localhost:8080`, because the browser reaches the API through the host port.
- The API container reaches dependencies by service names: `postgres`, `minio`, and `redis`.
- `CREATE_WORKTREE_ENABLED` defaults to `false` in Docker Compose. This keeps container startup independent of a mounted Git checkout. Create still writes only inside `/workspace/.worktrees` through the isolated stub workspace. Local development can enable real git worktrees.
- `MINIO_PUBLIC_BASE_URL` defaults to `http://localhost:9000/yahaha-games`, so URLs returned to the browser use the host port.
- Do not put real secrets in committed files. Override sensitive values through shell environment variables or a local untracked `.env` file next to `docker-compose.yml`.

Useful Docker commands:

```powershell
docker compose logs -f api
docker compose logs -f web
docker compose ps
docker compose down
docker compose down -v  # also removes database/object-storage volumes
```

If Docker fails before building project code with an error like `429 Too Many Requests` while loading `python`, `node`, or `nginx` image metadata, the blocker is the configured Docker registry mirror rather than this repository. Remove or change the Docker Desktop registry mirror, then run `docker compose up -d --build` again. The base images can also be overridden without editing project files:

```powershell
$env:PYTHON_IMAGE='python:3.12-slim'
$env:NODE_IMAGE='node:24-alpine'
$env:NGINX_IMAGE='nginx:1.27-alpine'
docker compose build api web
```

If you already have old Docker volumes and need to re-run database init SQL, remove volumes with `docker compose down -v` before starting again, or initialize manually.

## Startup Option B: Local Development

Use this path when you want hot reload, local debugging, or real git worktree isolation.

### Start dependencies only

```powershell
docker compose up -d postgres minio redis
```

PostgreSQL listens on `localhost:5432`.
MinIO API listens on `localhost:9000`.
MinIO Console listens on `http://localhost:9001`.
Redis listens on `localhost:6379`.

On a brand-new PostgreSQL volume, the SQL files in `apps/api/db/init` run automatically. If your Docker named volume already existed before these files were added, initialize the schema manually:

```powershell
Get-Content apps\api\db\init\001_schema.sql -Raw | docker exec -i yahaha-postgres psql -U yahaha -d yahaha
Get-Content apps\api\db\init\002_seed.sql -Raw | docker exec -i yahaha-postgres psql -U yahaha -d yahaha
```

### Start backend locally

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
.venv\Scripts\python tests\test_create_llm_generation.py
.venv\Scripts\python tests\test_langgraph_react.py
.venv\Scripts\python tests\test_llm_service.py
.venv\Scripts\python tests\test_prompt_templates.py
.venv\Scripts\python tests\test_agent_tools.py
.venv\Scripts\python tests\test_agent_strategies.py
.venv\Scripts\python tests\test_multi_agent_orchestration.py
.venv\Scripts\python tests\test_workspace_isolation.py
```

To verify real git worktree isolation, run the workspace test with the opt-in flag:

```powershell
$env:RUN_GIT_WORKTREE_TEST='1'; .venv\Scripts\python tests\test_workspace_isolation.py
```

### Start frontend locally

```powershell
cd apps/web
Copy-Item .env.example .env
npm install
npm run dev
```

Open `http://localhost:1314`.

## Distribution

The recommended MVP distribution path is source plus Docker Compose:

1. Push source code to GitHub.
2. Share the repository URL.
3. The recipient runs `git clone`, then `docker compose up -d --build`.

If you want recipients to run without building source, publish images to a registry such as GitHub Container Registry or Docker Hub, then replace the `build:` sections in Compose with image references, for example:

```yaml
api:
  image: ghcr.io/1030337360-lab/yahaha-api:latest
web:
  image: ghcr.io/1030337360-lab/yahaha-web:latest
```

For this repository, source-plus-Compose is the simpler and more transparent handoff. Registry images are better after the API and Web release cadence stabilizes.

Docker packaging files use project-relative paths: `docker-compose.yml`, `.dockerignore`, `apps/api/Dockerfile`, `apps/api/.dockerignore`, `apps/web/Dockerfile`, `apps/web/nginx.conf`, and `apps/web/.dockerignore`.

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
- `GET /auth/google/start`
- `GET /auth/google/callback`
- `GET /create/ai-config`
- `PUT /create/ai-config`
- `POST /create/ai-config/test`
- `GET /create/recent-game`
- `GET /create/projects`
- `GET /create/projects/{project_id}`
- `GET /create/runs/{run_id}`
- `GET /create/runs/{run_id}/steps`
- `GET /create/runs/{run_id}/events`
- `POST /create/jobs`
- `GET /create/jobs/{job_id}`
- `POST /create/jobs/{job_id}/publish`
- `GET /create/jobs/{job_id}/agent-state`
- `POST /uploads`
- `GET /games/{game_id}/versions`
- `POST /games/{game_id}/remix`
- `GET /maintenance/overview`
- `GET /maintenance/create-runs/failed`
- `GET /maintenance/jobs`
- `POST /maintenance/jobs/{job_id}/mark-reviewed`
- `POST /maintenance/jobs/{job_id}/retry`
- `GET /maintenance/games`
- `PATCH /maintenance/games/{game_id}`
- `POST /maintenance/games/{game_id}/moderate`
- `GET /maintenance/assets`
- `DELETE /maintenance/assets/{asset_id}`

## Create and LLM generation

Create jobs require login and a saved AI configuration. The AI config contains `baseUrl`, `model`, `provider`, and an encrypted `apiKey`; API responses and logs never return the key.

By default, `apps/api/.env.example` sets `CREATE_STATIC_GENERATION=false`. Create jobs run the selected LangGraph strategy through the OpenAI-compatible Responses adapter. Static generation is still available for local testing when `CREATE_STATIC_GENERATION=true`; in that mode the Create page shows a warning so it is not confused with real LLM generation.

`POST /create/jobs` now returns `202 Accepted` after creating the job/run/task records. Generation continues in a FastAPI background task. The web app opens `GET /create/runs/{run_id}/events` with a fetch stream and receives replayed plus live SSE events for `step`, `llm_call`, `tool_call`, `done`, `error`, and `heartbeat`.

The first experimental LLM path is ReAct: it can call registered JSON tools, stops only when the LLM returns `Finished=true`, and caps execution at 4 iterations. Parsed LLM output is normalized into the same artifact pipeline used by static generation, so publishing still goes through PostgreSQL plus MinIO. If real LLM output does not include the required game package contract, the run fails instead of silently publishing a fallback static game.

LLM requests use `LLM_REQUEST_TIMEOUT_SECONDS`, defaulting to `120` seconds. Keep this above typical model latency when using a local or proxy Responses API provider; a timeout only means the provider did not answer before this backend deadline.

The current strategy modules are `react`, `plan`, `refine`, and `decentralized`. `decentralized` registers the minimum production multi-agent stages for Planner, Asset, GameCode, Build, Safety, and Publisher. These stages write run steps, contracts, handoff rules, and retry policy metadata; the full independent sub-agent execution loop is still a later production hardening item.

Create workspaces use filesystem isolation by default. `CREATE_WORKTREE_ENABLED=true` creates a git worktree at `.worktrees/create-{runId}` with an isolated branch. `CREATE_WORKTREE_CLEANUP_POLICY=auto_on_success` removes successful run worktrees while preserving failed run worktrees for inspection. If git worktrees are disabled, the backend still uses an isolated stub directory rather than writing into the main repository.

Each LLM call records a `llm_call` run step with prompt prefix counts, English word counts, Chinese character counts, output counts, and provider token usage when the response includes it. The recorder writes summaries into SQL run steps, full JSONL run logs in MinIO, Redis short-term memory, and Redis long-term session history.

## Game artifact contract

AI-generated games should follow `docs/ai-game-generation-guide.md`. The target play model is an Astrocade-like platform shell that runs a self-contained generated HTML game document inside a sandboxed iframe and resolves the playable object through PostgreSQL metadata plus MinIO object storage.

## Current scope

The app is a minimum runnable project. It includes a game gallery, game detail pages, sandbox Play iframe, Docker dependencies, PostgreSQL schema/seed data, database-backed game catalog, JWT auth backed by Redis, play events with Redis-to-PostgreSQL flushing, MinIO-backed uploads, Create project/run tracking, isolated Create workspaces, an experimental LangGraph LLM generation path, live Create progress streaming, MVP safety scanning, Profile run details, maintainer retry/review tooling, and multi-agent production stage contracts. Full independent sub-agent execution, deeper recovery policy, and queue-grade background execution remain later-phase work.
