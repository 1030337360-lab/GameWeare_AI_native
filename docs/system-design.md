# System Design Notes

## Local Runtime

- React/Vite frontend runs on `http://localhost:1314`.
- FastAPI backend runs on `http://localhost:8080`.
- PostgreSQL, MinIO, and Redis are started by `docker compose up -d`.
- Redis stores active JWT records plus Create memory and cache data.
- MinIO stores local object data under `D:\gameweare`.
- Create agent filesystem work uses `.worktrees/create-{runId}`. With `CREATE_WORKTREE_ENABLED=true`, this is a real git worktree and branch; otherwise it is still an isolated stub directory, never the main repository root.

## Current MVP Flow

1. Home loads published games from PostgreSQL through `GET /games`.
2. Game detail pages read the selected game from the same database-backed catalog.
3. Play requests `GET /play/{game_id}/manifest`.
4. The backend resolves the current game version and manifest/bundle assets from PostgreSQL.
5. Login/register returns a JWT. The web app stores it locally and sends it as a Bearer token.
6. Create page checks `GET /create/ai-config`. If the logged-in user has no saved AI config, the web UI asks for `baseUrl`, `model`, and `apiKey`.
7. `PUT /create/ai-config` encrypts the API key in PostgreSQL and caches the config for the current JWT session in Redis.
8. Create page submits to `POST /create/jobs`, which requires the Bearer token and accepts `prompt`, `files`, `agentMode`, `createType`, and optional `projectId`.
9. `createType=init` creates a new `agent_projects` record. `createType=opt` requires a user-owned `projectId` and creates a new run under that project.
10. The backend creates a generation job, Create run, TaskState, workspace context, memory context, and run log, then immediately returns `202 Accepted`.
11. Generation continues in a FastAPI background task. The web app opens `GET /create/runs/{run_id}/events` and receives live SSE progress.
12. By default the backend runs the selected LangGraph strategy. Static generation only runs when `CREATE_STATIC_GENERATION=true`.
13. Generated `index.html`, `manifest.json`, and `source.json` are uploaded to MinIO and recorded in PostgreSQL `assets`, `game_versions`, `games`, `generation_jobs`, and `job_artifacts`.
14. `GET /create/runs/{run_id}/steps` exposes structured run steps for refresh/recovery, including `llm_call` and `tool_call` metrics.
15. Uploads go to MinIO and are recorded in the `assets` table.

## Create Agent Runtime

The current agent framework separates project lifecycle from agent strategy:

- `createType` controls lifecycle: `init` starts a project, `opt` continues an existing project.
- `agentMode` controls strategy selection: `chat`, `react`, `plan`, `decentralized`, or `refine`. Initial creation supports `chat/react/plan/decentralized`; continuation supports those same modes plus `refine`.
- Backend routing fields such as `createType`, `agentMode`, `projectId`, `runId`, and `taskId` are not injected into the LLM prompt.

Prompt rendering uses strategy-specific `system_prompt(settings)` and `user_prompt(settings)` methods. Prompts include the user request, workspace capability, workspace boundary, available tool metadata, and non-empty history or memory summaries. They never include API keys.

The LangGraph integration wraps the OpenAI-compatible Responses API through `OpenAIResponsesGraphAdapter`. ReAct is the first executable strategy: it loops through LLM decision and JSON tool calls, terminates only when the final JSON contains `Finished=true`, and stops after 4 iterations.

`decentralized` multi-agent mode now registers a minimum production orchestration contract for Planner, Asset, GameCode, Build, Safety, and Publisher. Each stage has an input contract, output contract, retry policy, handoff target, SQL run step, JSONL run-log entry, and TaskState checkpoint. The current implementation still uses the existing generation/publish path for execution; a fully independent sub-agent worker loop remains a later production item.

Every LLM call is recorded as:

- SQL step: `create_run_steps.stage='llm_call'`
- SSE event: `llm_call`
- MinIO JSONL run log: `agent-runs/{runId}/run-log.jsonl`
- Redis short-term run memory
- Redis long-term session history

Every ReAct tool call is recorded as `create_run_steps.stage='tool_call'` and streamed as a `tool_call` event with request/response summaries.

The recorded metrics include prompt prefix text, prefix English word count, prefix Chinese character count, full prompt counts, output counts, and provider token usage such as `outputTokens` when available.

## Deferred Work

- Hardening the full Astrocade-like iframe `srcdoc` runtime described in `docs/ai-game-generation-guide.md`.
- Providing Google OAuth Client ID/Secret to make the implemented Google route run against a real Google app.
- Adding production safety scanning for generated HTML, external scripts, file sizes, and platform-secret access.
- Adding retry, resume, and failure-recovery policies around LLM/tool/provider errors.
- Expanding multi-agent execution from registered Planner / Asset / GameCode / Build / Safety / Publisher contracts into independently scheduled sub-agent workers.
- Alembic migrations after the schema stabilizes beyond the SQL init scripts.
