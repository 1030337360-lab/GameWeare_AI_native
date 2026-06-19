# API Notes

Backend base URL: `http://localhost:8080`

The current implementation is intentionally small and runnable. PostgreSQL is the source of truth for published games, users, Create jobs, Create projects/runs, play events, and asset metadata. Redis stores active JWT records plus Create memory/cache data. MinIO stores uploaded assets, generated game artifacts, persistent memory objects, and full run logs.

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

`GET /create/ai-config` has optional auth. Anonymous callers receive:

```json
{
  "authenticated": false,
  "configured": false,
  "staticGeneration": false
}
```

Logged-in callers receive only non-secret config state:

```json
{
  "authenticated": true,
  "configured": true,
  "baseUrl": "http://localhost:8081/v1",
  "model": "gpt-5.5",
  "provider": "fighting",
  "staticGeneration": false
}
```

`PUT /create/ai-config` requires auth:

```json
{
  "baseUrl": "http://43.106.115.130:8080/v1",
  "model": "gpt-5.5",
  "apiKey": "secret value",
  "provider": "fighting"
}
```

The backend encrypts `apiKey` before writing it to PostgreSQL and caches the current session config in Redis. Responses never include the key.

`POST /create/ai-config/test` sends a small OpenAI Responses API request to `{baseUrl}/responses` and returns a structured test result:

```json
{
  "ok": true,
  "code": "OK",
  "message": "LLM configuration is reachable.",
  "details": {}
}
```

`POST /create/jobs` requires auth:

```json
{
  "prompt": "Make a pointer-controlled arcade game.",
  "files": [],
  "agentMode": "react",
  "createType": "init",
  "projectId": null
}
```

Allowed `createType` values are `init` and `opt`. `init` creates a new project and returns its `projectId`. `opt` continues an existing project and requires a user-owned `projectId`.

Allowed `agentMode` values are `chat`, `react`, `plan`, `refine`, `centralized`, `decentralized`, `init`, and `opt`. The strategy router maps these to the current strategy set; for example `react` selects the ReAct LangGraph path, and `createType=opt` defaults toward the refine strategy when no more specific strategy is selected.

`POST /create/jobs` returns `202 Accepted` after the job/run/task records are created. Generation continues in a background task. The initial response includes the run indexes but does not yet include the generated game:

```json
{
  "id": "job uuid",
  "status": "planning",
  "prompt": "Make a pointer-controlled arcade game.",
  "createdAt": "2026-06-19T00:00:00Z",
  "logs": [],
  "gameId": null,
  "gameSlug": null,
  "playUrl": null,
  "manifestUrl": null,
  "agentMode": "react",
  "createType": "init",
  "projectId": "project uuid",
  "runId": "run uuid",
  "taskId": "task uuid",
  "resumeStatus": "fresh"
}
```

Generation modes:

- `CREATE_STATIC_GENERATION=false`: default. Call the selected LangGraph strategy through the OpenAI-compatible Responses adapter, parse the final output, and publish the generated artifacts through the same MinIO/PostgreSQL path.
- `CREATE_STATIC_GENERATION=true`: explicit local test mode. Generate deterministic local test artifacts without calling an LLM provider; the web UI shows a static-mode warning.

LLM mode expects the final model output to be JSON containing game `files`, `cover`, `implementationSummary`, and `safetyNotes`. ReAct can also return JSON tool calls. The loop stops on `Finished=true` and caps at 4 iterations. Invalid LLM output fails the run and does not publish fallback static content.

Common Create errors:

- `409 AI_CONFIG_REQUIRED`: the user has not saved AI config.
- `400 LLM_CONFIG_INVALID`: AI config test failed before generation.
- `400 PROMPT_RENDER_FAILED`: strategy prompt/payload rendering failed.
- `400 LLM_GENERATION_FAILED`: provider call, graph execution, or output parsing failed.
- `409 PROJECT_ID_REQUIRED`: `createType=opt` was used without `projectId`.
- `404 Project not found`: `projectId` does not exist or does not belong to the current user.

`GET /create/runs/{run_id}/events` returns `text/event-stream`. It replays existing steps, then streams new Redis-backed events. The frontend uses `fetch` streaming so it can include `Authorization: Bearer <token>`.

SSE event types:

- `step`: normal Create stage.
- `llm_call`: LLM response summary and token metrics.
- `tool_call`: tool request/response summary.
- `done`: terminal success event with run summary.
- `error`: terminal failure event.
- `heartbeat`: keepalive.

`GET /create/runs/{run_id}/steps` returns ordered structured steps for refresh/recovery. LLM calls use `stage="llm_call"` and metrics such as:

```json
{
  "iteration": 1,
  "strategy": "react",
  "topology": "single-agent",
  "promptEnglishWords": 1000,
  "promptChineseChars": 20,
  "prefixEnglishWords": 120,
  "prefixChineseChars": 8,
  "outputEnglishWords": 600,
  "outputChineseChars": 0,
  "outputTokens": 900
}
```

## Upload APIs

- `POST /uploads`

Uploads write the file to MinIO and record an `assets` row with bucket, object key, public URL, content type, and size.
