# Yahaha MVP

Minimal runnable scaffold for an AI-native interactive game platform.

This build follows the technical route in `Yahaha-MVP-技术路线报告.md`:

- Frontend: React + Vite + TypeScript on port `1314`
- Backend: Python + FastAPI on port `8080`
- Local dependencies: PostgreSQL, MinIO, and Redis via Docker Compose
- Auth cache: Redis via Docker Compose
- MinIO local storage path: `D:\yahaha`
- Create generation: real LLM generation by default; static test generation is available only when `CREATE_STATIC_GENERATION=true`

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
Redis listens on `localhost:6379`.

On a brand-new PostgreSQL volume, the SQL files in `apps/api/db/init` run automatically. If your Docker named volume already existed before these files were added, initialize the schema manually:

```powershell
Get-Content apps\api\db\init\001_schema.sql -Raw | docker exec -i yahaha-postgres psql -U yahaha -d yahaha
Get-Content apps\api\db\init\002_seed.sql -Raw | docker exec -i yahaha-postgres psql -U yahaha -d yahaha
```

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
