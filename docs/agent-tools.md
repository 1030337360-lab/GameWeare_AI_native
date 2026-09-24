# Agent Tool Interface

## Goal

All Create agent paths should be driven by two things:

- LLM reasoning output.
- Tool calls with one consistent JSON contract.

Every tool must accept a JSON object and return a JSON object:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

Tool failures use the same JSON envelope:

```json
{
  "ok": false,
  "data": {},
  "error": {
    "code": "TOOL_VALIDATION_ERROR",
    "message": "$.userRequest is required",
    "type": "ToolValidationError",
    "tool": "llm.prompt_render",
    "request": {
      "tool": "llm.prompt_render",
      "input": {}
    },
    "files": []
  }
}
```

The `files` field is extracted from file-like request keys such as `path`, `file`, `files`, `filename`, `objectKey`, and `relativePath`. This gives the agent enough context to write useful run logs and user-facing error summaries.

Tool metadata must include runnable examples. The examples are part of the tool definition and are validated by `apps/api/tests/test_agent_tools.py`.

## Current Tool Layers

### Basic Tools

- `workspace.file_read`: read text files inside the active workspace boundary.
- `workspace.file_list`: list files inside the active workspace boundary.
- `llm.prompt_render`: render the Create game Responses API payload without calling an LLM provider.

### Extendable Tool Interfaces

- `memory.summary_build`: compact memory index entries before prompt injection.
- `run_log.preview_step`: validate the JSON shape of a run-log step before persistence.
- `command.plan`: normalize a command execution request without running it.
- `git.worktree_plan`: plan an isolated git worktree without creating it.
- `storage.object_key_plan`: plan MinIO object keys for memory, run logs, artifacts, and TaskState.
- `database.query_plan`: normalize a SQL entity/query target without executing SQL.
- `test.plan`: map a verification suite to its command.
- `web.fetch_plan`: validate a future web fetch request without network access.

The current implementation favors safe interfaces first. Tools that could modify files, run commands, access the network, or write SQL/Redis/MinIO are represented by dry-run planning tools until the corresponding execution policy is finalized.

## Project Tool Catalog

These are the tool families the Gameweare Create agent is expected to use as the project grows.

| Family | Current status | Purpose | Side effects |
| --- | --- | --- | --- |
| `workspace.*` | Partly implemented | Read/list/write project files under workspace isolation. Writes require git worktree isolation. | optional file write |
| `command.*` | Planning interface implemented | Run tests, builds, linters, package commands, and local validation commands. | process execution |
| `llm.*` | Partly implemented | Render prompts, test OpenAI-compatible Responses API settings, and call generation models through the LangGraph adapter when enabled. | optional network request |
| `memory.*` | Partly implemented | Summarize persistent MinIO memory, Redis long-term session memory, and Redis short-term run memory. | optional Redis/MinIO/SQL write |
| `run_log.*` | Partly implemented | Record structured Create execution steps and reproducible run logs. | SQL/MinIO write |
| `storage.*` | Planning interface implemented | Upload/download generated files and memory objects from MinIO. | MinIO read/write |
| `database.*` | Planning interface implemented | Query game/project/run metadata and persist Create results. | SQL read/write |
| `git.*` | Worktree isolation implemented; merge/diff still planning | Create and clean isolated worktrees for each Create run. | git state changes |
| `test.*` | Planning interface implemented | Execute focused smoke tests and normalize results into run logs. | process execution |
| `web.*` | Planning interface implemented | Fetch public documentation or inspect a generated game page when network/browser access is allowed. | network/browser access |

The first production rule is that agent code should ask for one of these tools through a registry lookup. It should not directly call raw file IO, SQL, Redis, MinIO, shell, or HTTP client code unless that capability has been wrapped as a tool.

## Metadata Contract

Each tool is registered with:

- `name`: stable tool ID, for example `workspace.file_read`.
- `category`: `basic` or `extendable`.
- `summary`: short human-readable purpose.
- `inputSchema`: JSON schema subset used by the local validator.
- `outputSchema`: standard result schema.
- `examples`: runnable JSON inputs.
- `sideEffects`: declared side effects such as file write, Redis write, MinIO write, SQL write, network request.
- `requires`: capability labels such as `workspace.read` or `prompt.template`.

## Example

```json
{
  "tool": "llm.prompt_render",
  "input": {
    "userRequest": "Create a keyboard controlled star collection game.",
    "model": "gpt-5.5",
    "maxOutputTokens": 25000
  }
}
```

The output contains a safe OpenAI Responses API payload. It never includes `api_key`; the key is only used by the HTTP Authorization header in the LLM service.
Backend-only fields such as `createType` and `agentMode` are not injected into this LLM prompt. The backend uses them before prompt rendering to choose the agent strategy.

Another example for command planning:

```json
{
  "tool": "command.plan",
  "input": {
    "args": [".venv\\Scripts\\python", "tests\\test_agent_tools.py"],
    "cwd": "apps/api",
    "timeoutSeconds": 60
  }
}
```

The output is a normalized dry-run command plan. It does not execute the command.

## LangGraph Strategy Layer

Create strategy selection is separate from tool execution. The backend builds `AgentRequestSettings`, chooses a strategy, then asks the strategy to render `system_prompt(settings)` and `user_prompt(settings)`.

Current strategy modules:

- `react`: single-agent ReAct loop with JSON tool calls.
- `plan`: single-agent planning interface.
- `refine`: single-agent continuation/optimization interface.
- `decentralized`: peer-agent strategy with registered Planner / Asset / GameCode / Build / Safety / Publisher contracts, claimed work metadata, conflict notes, and run-step audit logging.

All strategies expose `build_responses_payload(...)` and `run_langgraph(...)`. ReAct is the first strategy with a real loop:

```text
build payload
LLM decision
  -> {"type":"tool","tool":{"name":"...","args":{...}}}
     run registered tool, append JSON result, continue
  -> {"type":"final","output":{"Finished":true,...}}
     stop
stop after 4 iterations if Finished=true is never returned
```

The LLM adapter currently targets OpenAI-compatible Responses API providers:

```text
POST {baseUrl}/responses
Authorization: Bearer {apiKey}
```

`apiKey` is used only in the HTTP header and is not put into prompts, run logs, TaskState checkpoints, or frontend responses.

## Multi-Agent Production Contracts

`decentralized` mode registers six durable stages before generation:

| Stage | Role | Output |
| --- | --- | --- |
| `planner` | Planner Agent | Game brief, task graph, acceptance criteria |
| `asset_agent` | Asset Agent | Asset manifest and cover requirements |
| `game_code_agent` | GameCode Agent | `index.html`, implementation summary, safety notes |
| `build_agent` | Build Agent | Artifact list, entry file, runtime metadata |
| `safety_agent` | Safety Agent | Safety decision and structured issues |
| `publisher_agent` | Publisher Agent | Storage prefix, published game metadata, audit summary |

Each stage writes a `create_run_steps` record and full JSONL run-log entry with input contract, output contract, retry policy, and handoff target. This provides auditable production choreography while the independent sub-agent worker loop is still being hardened.

## LLM Call Metrics

Every provider call is normalized into an `llm_call` event. The recorder writes the event to:

- SQL `create_run_steps`
- MinIO `agent-runs/{runId}/run-log.jsonl`
- Redis short-term run memory
- Redis long-term session history

Recorded metrics include:

- `promptPrefix`: first 600 characters of the rendered prompt input.
- `promptEnglishWords` and `promptChineseChars`: full prompt language counts.
- `prefixEnglishWords` and `prefixChineseChars`: prefix language counts.
- `outputEnglishWords` and `outputChineseChars`: generated text counts.
- `tokenUsage.outputTokens`: provider output token count when the Responses API result includes usage.

These metrics are visible through `GET /create/runs/{run_id}/steps` and the web Create page's Run steps panel.

The live Create page also receives these summaries through `GET /create/runs/{run_id}/events`. The event stream sends only summaries and metrics; full prompts, full model output, raw API keys, and authorization secrets are not emitted.

## Adding A Tool

1. Add a handler that accepts `dict[str, Any]` and returns the standard result object.
2. Register a `ToolSpec` in `apps/api/app/agents/tools/builtin.py` or a future provider module.
3. Define input and output schemas.
4. Add at least one runnable example to `examples`.
5. Keep side effects explicit in `sideEffects`.
6. Run:

```powershell
cd C:\Users\梁淇峰\Documents\gameweare-mvp\apps\api
.venv\Scripts\python tests\test_agent_tools.py
```

## Verification

The current metadata examples are executable and covered by:

```powershell
cd C:\Users\梁淇峰\Documents\gameweare-mvp\apps\api
.venv\Scripts\python tests\test_agent_tools.py
```

That test loads the registry, checks every tool has schemas and examples, runs every example through the real handler, and verifies the output follows the unified JSON result schema.

## Design Notes

- Tools should not receive raw secrets unless the tool specifically exists to perform a provider call.
- Tools should return structured errors instead of plain strings when the failure is expected business behavior.
- Tool-call errors must include the original tool request, involved file paths when present, and an error object in the standard JSON envelope.
- File tools must use workspace boundary checks.
- Write tools require an isolated workspace before writing to the filesystem. By default, this is a real git worktree when `CREATE_WORKTREE_ENABLED=true`; otherwise it is an isolated stub directory under `.worktrees/`.
- SQL, Redis, and MinIO tools should log their side effects to `run_log` when they are used inside a Create run.
