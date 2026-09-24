# Yahaha MVP 交付说明

## 1. 源码仓库

| 项目 | 内容 |
| ---- | ---- |
| GitHub 仓库 | https://github.com/1030337360-lab/GameWeare_AI_native.git |
| 仓库类型 | Monorepo，包含 `apps/api` 后端、`apps/web` 前端、`docs` 文档、`apps/api/db/init` 数据库初始化脚本 |
| 提交记录 | 已满足不少于 3 次提交要求 |

最近提交记录示例：

| Commit | 说明 |
| ------ | ---- |
| `a285a35` | 优化了 Create 中的提示词、对接协议和降级措施 |
| `edecbf1` | 更新 plan/refine/multi-agent 等 Create 方案，优化前后端连接，新增用户级游戏删除，提供后端清理接口 |
| `51da15a` | 修改 Create 部分 bug，优化前端页面展示 |
| `21ebd4f` | 更新页面显示，加入 Profile 详细功能，加入管理员设置 |
| `6c5b916` | 建立 LangGraph 智能体框架，实现前后端协同，完成 Create 模块首次贯通 |

## 2. Demo 地址

当前没有线上部署地址，Demo 以本地运行方式交付。

| 类型 | 地址 / 说明 |
| ---- | ----------- |
| 前端本地地址 | `http://localhost:1314` |
| 后端 API | `http://localhost:8080` |
| 后端健康检查 | `http://localhost:8080/health` |
| MinIO Console | `http://localhost:9001` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

完整本地启动方式见第 3 节。

## 3. 启动命令

项目提供两套启动方案：

- 方案 A：完整 Docker Stack，适合交付给他人一键运行。
- 方案 B：本机开发启动，适合调试、开发和真实 git worktree 隔离。

### 3.1 方案 A：完整 Docker Stack

使用方式：

```powershell
git clone https://github.com/1030337360-lab/GameWeare_AI_native.git
cd GameWeare_AI_native
docker compose up -d --build
```

该命令会构建并启动：

| 服务 | 端口 | 用途 |
| ---- | ---- | ---- |
| `web` | `1314` | React 生产构建，由 Nginx 提供静态服务 |
| `api` | `8080` | FastAPI 后端 |
| `postgres` | `5432` | 主数据库，首次创建 volume 时自动执行 `apps/api/db/init/*.sql` |
| `minio` | `9000`, `9001` | 对象存储 API 和控制台 |
| `redis` | `6379` | JWT 活跃状态、Create 缓存、Agent memory、SSE pubsub、播放统计缓存 |

启动后访问：

```text
前端 Web: http://localhost:1314
后端健康检查: http://localhost:8080/health
MinIO Console: http://localhost:9001
```

MinIO 本地默认账号密码：

```text
minioadmin / minioadmin
```

Docker 方案使用的项目内相对路径：

| 路径 | 作用 |
| ---- | ---- |
| `docker-compose.yml` | 一键编排 web、api、postgres、minio、redis |
| `.dockerignore` | 根构建忽略规则 |
| `apps/api/Dockerfile` | 后端镜像构建文件 |
| `apps/api/.dockerignore` | 后端镜像构建忽略规则 |
| `apps/web/Dockerfile` | 前端镜像构建文件 |
| `apps/web/nginx.conf` | 前端生产环境 Nginx SPA 配置 |
| `apps/web/.dockerignore` | 前端镜像构建忽略规则 |

Docker 方案说明：

- 前端镜像构建时使用 `VITE_API_BASE_URL=http://localhost:8080`，因为浏览器通过宿主机端口访问 API。
- 后端容器内部通过服务名访问依赖：`postgres`、`minio`、`redis`。
- Docker Compose 中 `CREATE_WORKTREE_ENABLED` 默认是 `false`，避免容器内必须存在完整 git checkout；Create 文件仍写入隔离 stub workspace，不会写主目录。
- 本机开发方案可以使用 `CREATE_WORKTREE_ENABLED=true` 启用真实 git worktree。
- 敏感配置不要提交到 GitHub；部署或演示时通过本机未提交的 `.env` 或 shell 环境变量覆盖。

常用命令：

```powershell
docker compose logs -f api
docker compose logs -f web
docker compose ps
docker compose down
docker compose down -v
```

`docker compose down -v` 会删除 PostgreSQL / MinIO 等 Docker volume，适合需要重置数据库和对象存储时使用。
如果 Docker 在构建项目代码前就因为拉取 `python`、`node`、`nginx` 基础镜像失败，并出现 `429 Too Many Requests`，通常是 Docker Desktop 当前配置的镜像源限流，不是项目 Dockerfile 或 Compose 配置错误。处理方式是移除或更换 Docker Desktop registry mirror 后重新运行 `docker compose up -d --build`。项目也支持通过环境变量覆盖基础镜像：

```powershell
$env:PYTHON_IMAGE='python:3.12-slim'
$env:NODE_IMAGE='node:24-alpine'
$env:NGINX_IMAGE='nginx:1.27-alpine'
docker compose build api web
```

### 3.2 方案 B：本机开发启动

该方案只用 Docker 启动 PostgreSQL、MinIO、Redis，前端和后端在宿主机运行。

#### 3.2.1 启动依赖服务

```powershell
docker compose up -d postgres minio redis
```

该命令启动：

| 服务 | 端口 | 用途 |
| ---- | ---- | ---- |
| PostgreSQL | `5432` | 主数据库，自动执行 `apps/api/db/init/*.sql` 初始化 schema 和 seed 数据 |
| MinIO | `9000`, `9001` | 对象存储和控制台 |
| Redis | `6379` | JWT 活跃状态、Create 缓存、Agent memory、SSE pubsub |

#### 3.2.2 启动后端

```powershell
cd apps/api
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Windows 环境下当前不建议使用 `--reload`，因为 reloader watcher 可能触发 named pipe 权限问题。

#### 3.2.3 启动前端

```powershell
cd apps/web
Copy-Item .env.example .env
npm install
npm run dev
```

启动后打开：

```text
http://localhost:1314
```

#### 3.2.4 后端快速验证

```powershell
curl http://localhost:8080/health
```

期望响应：

```json
{"status":"ok"}
```

### 3.3 GitHub 与镜像分发

当前推荐交付方式是“GitHub 源码 + Docker Compose”：

1. 将源码推送到 GitHub。
2. 接收方 clone 仓库。
3. 接收方在仓库根目录运行 `docker compose up -d --build`。

如果希望接收方不构建源码，可以后续把镜像推送到 GitHub Container Registry 或 Docker Hub，再把 `docker-compose.yml` 中的 `build:` 改成远端镜像：

```yaml
api:
  image: ghcr.io/1030337360-lab/yahaha-api:latest
web:
  image: ghcr.io/1030337360-lab/yahaha-web:latest
```

对当前 MVP 来说，源码加 Compose 更透明，也更适合老师或测试者查看实现细节。
## 4. 测试数据

数据库初始化脚本 `apps/api/db/init/002_seed.sql` 提供至少 3 个示例游戏，满足测试数据要求。

| 游戏 | Slug | 作者 | 标签 | 来源 | 发布状态 |
| ---- | ---- | ---- | ---- | ---- | -------- |
| Astro Ludo | `astro-ludo` | `xiaoling` | Board, Arcade | Seed 示例游戏 | public / published |
| Color Bloom | `color-bloom` | `emanfatima` | Puzzle, Generated | Create 流程生成并发布的示例，关联 `generation_jobs`、`agent_runs`、`job_artifacts` | public / published |
| Rail in Air | `rail-in-air` | `Majisok` | Runner, Physics | Seed 示例游戏 | public / published |

其中 `Color Bloom` 满足“至少 1 个由 Create 流程生成并发布”的要求。它在 seed 数据中具备以下证据：

| 证据 | 内容 |
| ---- | ---- |
| `generation_jobs` | `20000000-0000-0000-0000-000000000001`，状态为 `completed` |
| `game_versions` | `source_job_id` 指向上述生成任务 |
| `assets` | 包含 manifest 和 bundle 产物 |
| `job_artifacts` | 将生成任务与 manifest/final 产物关联 |
| `agent_runs` | 包含 planner、game_code、publisher 三个成功阶段 |

## 5. 环境变量

项目提供环境变量示例文件：

| 文件 | 用途 |
| ---- | ---- |
| `apps/api/.env.example` | 后端运行配置、数据库、Redis、MinIO、JWT、LLM、工作区和管理员配置 |
| `apps/web/.env.example` | 前端 API 地址和端口配置 |

说明：示例文件只应包含开发/测试默认值，不应提交真实生产密钥。当前 `JWT_SECRET`、`AI_CONFIG_ENCRYPTION_SECRET`、MinIO 默认账号和管理员密码均为本地测试值，部署或对外演示时必须替换。

### 5.1 后端环境变量

| 变量 | 用途 |
| ---- | ---- |
| `DATABASE_URL` | PostgreSQL 连接字符串 |
| `MINIO_ENDPOINT` | MinIO 服务地址 |
| `MINIO_ACCESS_KEY` | MinIO access key，本地测试默认 `minioadmin` |
| `MINIO_SECRET_KEY` | MinIO secret key，本地测试默认 `minioadmin` |
| `MINIO_BUCKET` | 存放游戏产物和上传文件的 bucket |
| `MINIO_PUBLIC_BASE_URL` | 生成公开访问 URL 时使用的 MinIO base URL |
| `REDIS_URL` | Redis 连接字符串 |
| `JWT_SECRET` | JWT 签名密钥，部署时必须替换 |
| `JWT_TTL_SECONDS` | JWT 有效期 |
| `WEB_BASE_URL` | 前端地址，用于 OAuth callback 和跳转 |
| `GOOGLE_CLIENT_ID` | Google OAuth client id，可为空表示未启用 |
| `GOOGLE_CLIENT_SECRET` | Google OAuth secret，可为空表示未启用 |
| `GOOGLE_REDIRECT_URI` | Google OAuth 回调地址 |
| `API_PORT` | 后端端口 |
| `AI_CONFIG_ENCRYPTION_SECRET` | 用户 LLM API key 加密密钥，部署时必须替换 |
| `CREATE_STATIC_GENERATION` | 是否启用静态测试生成；默认 `false`，真实 LLM 生成开启 |
| `CREATE_VALIDATE_LLM_CONFIG` | Create 前是否校验 LLM 配置 |
| `CREATE_RECENT_GAME_TTL_SECONDS` | 最近生成游戏缓存 TTL |
| `LLM_REQUEST_TIMEOUT_SECONDS` | LLM 请求超时时间 |
| `PLAY_STATS_FLUSH_INTERVAL_SECONDS` | 播放统计从 Redis flush 到 PostgreSQL 的间隔 |
| `CREATE_WORKTREE_ENABLED` | 是否为 Create run 创建 git worktree 隔离目录 |
| `CREATE_WORKTREE_BASE_REF` | worktree 基准 ref |
| `CREATE_WORKTREE_CLEANUP_POLICY` | worktree 清理策略 |
| `MAINTAINER_EMAIL` | 管理员账号邮箱，本地测试值 |
| `MAINTAINER_PASSWORD` | 管理员账号密码，本地测试值，部署时必须替换 |
| `MAINTAINER_DISPLAY_NAME` | 管理员显示名 |

### 5.2 前端环境变量

| 变量 | 用途 |
| ---- | ---- |
| `VITE_API_BASE_URL` | 前端请求后端 API 的 base URL，默认 `http://localhost:8080` |
| `WEB_PORT` | 前端开发服务器端口，默认 `1314` |

## 6. 系统设计文档

### 6.1 Architecture Overview

Yahaha MVP 是一个 AI 原生互动游戏平台，核心目标是让用户通过 Prompt 和可选图片输入创建、优化、发布可玩的 HTML5 小游戏。

系统采用前后端分离架构：

- 前端负责游戏浏览、播放、Create 流程、Profile、维护面板。
- 后端负责认证、游戏目录、播放 manifest、Create 任务编排、Agent run 记录、产物发布、维护接口。
- PostgreSQL 是业务事实源。
- MinIO 保存远端游戏产物、上传资源、run log、memory 对象。
- Redis 保存短期状态、JWT 活跃记录、SSE pubsub、Create memory/cache。
- Agent Runtime 通过自研策略层和 LangGraph 调用 OpenAI-compatible Responses API。

### 6.2 Architecture Diagram

```mermaid
graph TD
  User["User Browser"] --> Web["React/Vite Web App"]
  Web --> API["FastAPI Backend"]
  API --> PG["PostgreSQL"]
  API --> Redis["Redis"]
  API --> MinIO["MinIO Object Storage"]
  API --> Agent["Create Agent Runtime"]
  Agent --> Strategy["chat / react / plan / refine / decentralized"]
  Strategy --> LangGraph["LangGraph"]
  LangGraph --> LLM["OpenAI-compatible Responses API"]
  Agent --> Tools["JSON Tool Registry"]
  Agent --> Workspace["Isolated .worktrees/create-{runId}"]
  Agent --> SSE["Run Event Stream"]
  SSE --> Web
```

### 6.3 Core Interfaces

| Interface | Type | Description |
| --------- | ---- | ----------- |
| `/health` | REST | 后端健康检查 |
| `/games`, `/games/{game_id}` | REST | 游戏列表、详情、删除、标签、点赞收藏 |
| `/games/{game_id}/versions` | REST | 游戏版本列表 |
| `/games/{game_id}/versions/switch` | REST | 切换当前游戏版本 |
| `/play/{game_id}/manifest` | REST | 获取 iframe 播放协议 |
| `/events/play` | REST | 上报播放、开始、结束、加载失败事件 |
| `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/session` | REST | 邮箱认证和 JWT session |
| `/auth/google/start`, `/auth/google/callback` | REST | Google OAuth 路由，需配置 client 才能启用 |
| `/create/ai-config` | REST | 保存和读取用户 LLM 配置，响应不返回 API key |
| `/create/ai-config/test` | REST | 测试 OpenAI-compatible Responses API 连通性 |
| `/create/jobs` | REST | 创建异步 Create 生成任务，返回 `202 Accepted` |
| `/create/jobs/{job_id}` | REST | 查询生成任务状态 |
| `/create/jobs/{job_id}/publish` | REST | 发布生成任务产物 |
| `/create/runs/{run_id}/events` | SSE | 推送 step、LLM、tool、plan、decentralized、done/error 事件 |
| `/create/runs/{run_id}/steps` | REST | 查询结构化 run step |
| `/create/runs/{run_id}/plan-preview` | REST | 获取 plan 模式预览 |
| `/create/runs/{run_id}/plan-decision` | REST | 接受或拒绝 plan |
| `/create/runs/{run_id}/decentralized-previews` | REST | 获取去中心化三候选预览 |
| `/create/runs/{run_id}/decentralized-selection` | REST | 选择去中心化候选方向 |
| `/create/runs/{run_id}/decentralized-confirm` | REST | 确认或拒绝去中心化方向 |
| `/create/projects` | REST | 查询用户 Create 项目 |
| `/create/projects/{project_id}` | REST / DELETE | 查询或删除项目 |
| `/create/projects/{project_id}/preview` | REST | 获取项目当前可玩预览 |
| `/uploads` | REST | 上传输入图片/资源到 MinIO |
| `/profile/*` | REST | 用户活动、项目详情、run 反馈 |
| `/maintenance/*` | REST | 管理员查看失败任务、重试、审核、游戏和资产管理 |
| Agent tools | Tool Interface | `workspace.*`、`llm.*`、`memory.*`、`run_log.*`、`command.plan` 等统一 JSON 工具 |

### 6.4 Data Model

| Entity | Description |
| ------ | ----------- |
| `users` | 用户基础信息、角色、状态 |
| `auth_accounts` | 邮箱、Google、GitHub 等认证账户 |
| `user_sessions` | 数据库 session 记录 |
| `games` | 游戏主表，包含 slug、作者、可见性、发布状态、计数 |
| `game_versions` | 游戏版本、runtime、entry、manifest、构建和安全状态 |
| `tags`, `game_tags` | 游戏标签和关联关系 |
| `assets` | MinIO 或外部资源元数据 |
| `generation_jobs` | Create 生成任务、状态、错误、输入 payload |
| `job_artifacts` | 生成任务和产物资源的关联 |
| `agent_runs` | 早期 Agent 阶段记录 |
| `agent_projects` | 用户创作项目，支持 init/opt 生命周期 |
| `create_runs` | 单次 Create Agent run |
| `create_run_steps` | 结构化 run step、LLM call、tool call、错误和指标 |
| `agent_memory_index` | 持久记忆对象索引 |
| `agent_task_state_index` | TaskState checkpoint 和 resume 状态 |
| `agent_workspace_runs` | worktree/stub workspace 隔离记录 |
| `play_events` | 游戏播放行为事件 |
| `game_likes`, `game_favorites`, `game_comments` | 社交互动数据 |
| `moderation_reviews` | 审核记录 |
| `model_usage_events` | 模型 token、延迟、成本记录 |
| `audit_logs` | 审计日志 |

### 6.5 Agent Workflow

```mermaid
graph LR
  Input["Prompt + Optional Images"] --> CreateAPI["POST /create/jobs"]
  CreateAPI --> Job["generation_jobs"]
  CreateAPI --> Run["create_runs + TaskState"]
  Run --> Workspace["Isolated Workspace"]
  Run --> Memory["Redis + MinIO Memory"]
  Run --> Router["Strategy Router"]
  Router --> Chat["chat"]
  Router --> ReAct["react"]
  Router --> Plan["plan preview -> accept/reject"]
  Router --> Refine["refine existing project"]
  Router --> Decentralized["decentralized previews"]
  Decentralized --> Select["User selects candidate"]
  Select --> Final["Final game + cover generation"]
  ReAct --> Tools["JSON Tools"]
  Chat --> LLM["Responses API"]
  ReAct --> LLM
  Plan --> LLM
  Refine --> LLM
  Final --> LLM
  LLM --> Parser["Output Parser"]
  Parser --> Safety["MVP Safety Scan"]
  Safety --> Publish["Publish Artifacts"]
  Publish --> MinIO
  Publish --> PG["PostgreSQL Metadata"]
  Run --> SSE["SSE Progress Stream"]
```

当前支持的 Create 策略：

| Strategy | 状态 | 说明 |
| -------- | ---- | ---- |
| `chat` | 已实现 | 单次生成路径，适合基础 Create |
| `react` | 已实现 / 实验性 | ReAct 循环，可调用注册 JSON 工具，最多 4 轮 |
| `plan` | 已实现 / 实验性 | 先生成 plan preview，用户接受后继续生成 |
| `refine` | 进行中 | 用于已有项目的继续优化，结合项目 preview 和历史上下文 |
| `decentralized` | 已实现 / 实验性 | 先生成 3 个静态方向，用户选择确认后生成最终游戏和封面 |

说明：当前的Create采用Agent有两种形式，一是init游戏，这一环节有chat、react、plan和decentralized可以使用。二是continue optimize对已经生成的游戏进行迭代优化，新加入refine策略，但是当前的完成度不高。



### 6.6 Remote Artifact Protocol

AI 生成的游戏产物通过 PostgreSQL 元数据和 MinIO 对象存储共同发布。后端在生成完成后将 `index.html`、`manifest.json`、`source.json`、cover 等文件上传到 MinIO，并在 `assets`、`game_versions`、`games`、`job_artifacts` 表中记录 bucket、object_key、content_type、size、version、entry_file 等信息。

播放端通过 `GET /play/{game_id}/manifest` 获取运行协议，核心字段包括：

| Field | Description |
| ----- | ----------- |
| `id` | 游戏 ID |
| `title` | 游戏标题 |
| `version` | 游戏版本 |
| `entry` | 入口文件，通常是 `index.html` |
| `bundleUrl` | 游戏包或入口文档 URL |
| `documentUrl` | 可直接加载进 iframe 的 HTML 文档 URL |
| `assets` | 附属资源列表 |
| `runtime` | 运行时类型，如 `iframe-html5` / `iframe-srcdoc` |
| `sandbox` | iframe sandbox 权限，默认 `allow-scripts` |

前端播放页读取 manifest 后，将 `documentUrl` 或 `bundleUrl` 对应的 HTML 拉取为 `srcDoc`，再放入 sandboxed iframe 运行。生成产物必须遵守 `docs/ai-game-generation-guide.md`，不得包含远程脚本、密钥、local file API、eval、pointer lock 等高风险能力。

### 6.7 Security Design

| 安全点 | 方案 |
| ------ | ---- |
| 用户认证 | Email/password + JWT Bearer |
| Token 管理 | JWT `jti` 写入 Redis，logout 可删除活跃 token |
| 密码存储 | PBKDF2-SHA256，不明文保存密码 |
| LLM 密钥 | 用户 API key 后端加密保存，前端响应和 run log 不返回密钥 |
| 权限控制 | Create、Profile、Maintenance 等接口依赖登录用户；Maintenance 依赖管理员角色 |
| OAuth | Google OAuth 路由存在，使用 state 防 CSRF，需真实 client 配置 |
| iframe 沙箱 | 生成游戏放入 sandboxed iframe，默认只允许脚本执行 |
| 文件隔离 | Create run 使用 `.worktrees/create-{runId}`；启用 worktree 时创建独立 git branch/worktree |
| 工具治理 | Agent tools 统一 JSON envelope，声明 side effects 和 requires |
| 日志安全 | LLM call 记录摘要、token、计数和指标，不记录 API key |

### 6.8 Known Issues

| 问题 | 影响 | 后续处理 |
| ---- | ---- | -------- |
| 镜像仓库未发布 | 当前已支持本地全栈 Docker Compose 构建运行，但尚未推送预构建镜像到 GHCR/Docker Hub | 后续可增加 GitHub Actions 构建并发布 `api` / `web` 镜像 |
| 生产级安全扫描不足 | 当前是 MVP 扫描，复杂 HTML/JS 风险可能漏检 | 引入 AST/DOM 级扫描、外链白名单、敏感 API 黑名单 |
| Google OAuth 未配置 | 路由存在但默认不可用 | 配置真实 Google OAuth app |
| SQL init 替代 migration | 后续 schema 变更难追踪 | 引入 Alembic migrations |
| 独立 sub-agent worker loop 未完成 | `decentralized` 已有两阶段流程，但不是完全独立 worker 调度 | 设计队列、worker、重试、resume、可观测性 |
| 前端主文件偏大 | `apps/web/src/main.tsx` 承载大量页面逻辑 | 拆分页面、API client、hooks、组件 |

## 7. 技术栈说明

| 类别 | 技术栈 |
| ---- | ------ |
| 前端 | React 19, Vite 6, TypeScript, React Router 7, lucide-react |
| 后端 | Python 3.12+, FastAPI, Uvicorn, Pydantic Settings |
| 数据库 | PostgreSQL 16 |
| 对象存储 | MinIO |
| 缓存 / PubSub | Redis 7 |
| Agent 框架 | Custom Agent Runtime, LangGraph |
| Tool Interface | 自研 JSON Tool Registry，支持 workspace、llm、memory、run_log、command plan 等工具族 |
| 模型服务 | OpenAI-compatible Responses API，用户可配置 base URL、model、api key |
| 认证 | JWT, Redis token state, PBKDF2 password hashing, optional Google OAuth |
| 部署方式 | 支持完整 Docker Compose 一键启动，也支持 Docker 依赖服务 + 宿主机运行前后端的本机开发模式 |
| 测试 | Python script-style tests under `apps/api/tests` |

## 8. 测试脚本与验证结果

本轮验证时间：2026-06-21。后端写入类测试通过 `apps/api/tests/support/integration.py` 自动使用隔离资源：`DATABASE_URL=postgresql+psycopg://yahaha:yahaha@localhost:5432/yahaha_test`、`MINIO_BUCKET=yahaha-games-test`、`REDIS_URL=redis://localhost:6379/15`。运行前后会调用测试污染清理逻辑，避免写入默认开发库、默认 MinIO bucket 或 Redis DB 0。

验证前启动了本地依赖服务：

```powershell
docker compose up -d postgres minio redis
```

PowerShell profile 的执行策略警告只影响 shell profile 加载，不影响测试脚本执行结果。

### 8.1 后端测试脚本

| 脚本 | 说明 | 本轮结果 |
| ---- | ---- | -------- |
| `apps/api/tests/test_prompt_templates.py` | Prompt 模板字段、Responses payload、敏感字段过滤、默认 workspace fallback | 通过，输出 `prompt template checks passed` |
| `apps/api/tests/test_agent_strategies.py` | strategy registry、react/plan/refine/decentralized prompt 协议、parser normalization、多模态 prompt 脱敏 | 通过，输出 `agent strategy checks passed` |
| `apps/api/tests/test_llm_service.py` | OpenAI-compatible Responses adapter、错误分类、timeout、retry、token/prefix metrics | 通过，输出 `llm service checks passed` |
| `apps/api/tests/test_multimodal_helpers.py` | 多模态输入资产清理、敏感字段和 base64 脱敏 | 通过，输出 `multimodal helper checks passed` |
| `apps/api/tests/test_langgraph_react.py` | ReAct LangGraph loop、tool continuation 压缩、provider 502 recovery、token/log 记录 | 通过，输出 `langgraph react checks passed`；仅有 LangGraph 依赖 deprecation warning |
| `apps/api/tests/test_single_step_graph.py` | 单步策略图、工具调用续轮、大文件写入压缩、provider error | 通过，输出 `single-step graph checks passed`；仅有 LangGraph 依赖 deprecation warning |
| `apps/api/tests/test_multi_agent_orchestration.py` | multi-agent contract/stage metadata、TaskState checkpoint、run log 记录 | 通过，输出 `multi-agent orchestration checks passed` |
| `apps/api/tests/test_workspace_isolation.py` | stub workspace、git worktree opt-in 隔离、主工作区不被写入 | 通过，输出 `workspace isolation checks passed` |
| `apps/api/tests/test_create_llm_generation.py` | Create LLM、plan accept/reject、cover agent 降级、publish、manifest/document、安全扫描、失败路径 | 通过，输出 `create llm generation checks passed` |
| `apps/api/tests/test_decentralized_two_phase.py` | decentralized 三候选、选择/确认/拒绝、final game、cover、发布链路 | 通过，输出 `decentralized two-phase checks passed` |
| `apps/api/tests/test_smoke.py` | API 主流程 smoke：auth、games、play stats、Create、Profile、Maintenance、删除与 opt flow | 通过，输出 `api smoke checks passed` |
| `apps/api/tests/test_agent_tools.py` | Tool registry metadata、tool examples、权限错误 JSON 包装、prompt_render 工具 | 未通过。失败点是 `registry.run_examples()` 中 `workspace.file_read` 的 `read_api_main` 示例访问 `.worktrees/tool-demo-read/app/main.py`，该示例 fixture 路径不存在，返回 `TOOL_FILE_NOT_FOUND`。这属于工具示例测试 fixture/上下文问题，不是数据库污染问题 |

辅助文件 `apps/api/tests/support/integration.py` 不是独立测试脚本，作用是设置测试隔离环境、fail-fast 防护、测试污染清理和串行锁。

### 8.2 前端验证脚本

| 脚本 | 说明 | 本轮结果 |
| ---- | ---- | -------- |
| `apps/web/package.json` -> `npm.cmd run build` | TypeScript 编译和 Vite 生产构建 | 通过，生成 `dist/index.html`、CSS 和 JS bundle |

前端当前没有独立 `test` / `spec` 脚本；`dev` 和 `preview` 是运行服务命令，不作为本轮自动化测试结果统计。

### 8.3 配置与构建校验

| 命令 | 说明 | 本轮结果 |
| ---- | ---- | -------- |
| `docker compose config --quiet` | 校验 Compose 配置语法和服务定义 | 通过 |
| `git diff --check` | 检查 whitespace error | 通过，仅提示 Git 未来可能把 LF 转为 CRLF |
| `apps/api/.venv/Scripts/python.exe -m py_compile app/main.py app/config.py app/agents/framework/workspace.py` | 后端关键模块语法检查 | 通过 |
| `docker compose build api web` | 构建 API / Web 镜像 | 未完成。失败发生在拉取 `python:3.12-slim`、`node:24-alpine` 基础镜像 metadata 阶段，当前 Docker Desktop registry mirror `https://docker.xuanyuan.me/` 返回 `429 Too Many Requests`，不是项目 Dockerfile 或 Compose 配置错误 |

### 8.4 本轮测试结论

后端 12 个测试脚本中 11 个通过，1 个失败；前端生产构建通过；Compose 配置和关键 Python 模块语法检查通过。当前需要修复的测试项是 `test_agent_tools.py` 的工具示例 fixture/context，使 `workspace.file_read` 示例读取到真实存在的 `app/main.py` 或改为使用正确的 workspace root。

## 9. 完成度说明

### 9.1 已完成

| 模块 | 状态 | 证据 |
| ---- | ---- | ---- |
| 游戏首页/详情/播放 | 已完成 | `/games`、`/play/{game_id}/manifest`、sandbox iframe |
| Seed 数据 | 已完成 | 3 个公开示例游戏，含 1 个 Create 发布样例 |
| 邮箱注册登录/JWT | 已完成 | `/auth/register`、`/auth/login`、Redis JWT active state |
| 游戏互动 | 已完成 | 点赞、收藏、播放事件、播放统计 flush |
| 对象上传 | 已完成 | `/uploads` 写入 MinIO 并记录 assets |
| Create 异步任务 | 已完成 | `/create/jobs` 返回 `202 Accepted`，后台生成，SSE 推送 |
| LLM 配置 | 已完成 | `/create/ai-config` 保存加密 API key，`/test` 验证模型连通性 |
| ReAct 策略 | 已完成 / 实验性 | JSON tool call loop，最多 4 轮 |
| Plan 策略 | 已完成 / 实验性 | plan preview + accept/reject |
| Decentralized 策略 | 已完成 / 实验性 | 三候选静态预览 + 选择 + 确认后最终生成 |
| Refine 续作 | 进行中 | opt/refine、项目 preview、历史上下文已接入 |
| Profile | 已完成 | 最近播放、项目列表、run 反馈 |
| Maintenance | 已完成 | 失败任务、重试、审核、游戏和资产管理 |
| Worktree 隔离 | 已完成 / 进行中 | git worktree + stub fallback |
| 后端测试 | 已完成 / 持续扩展 | 本轮 12 个脚本中 11 个通过；`test_agent_tools.py` 因工具示例 fixture 路径缺失未通过，详见第 8 节 |
| 全栈 Docker Compose | 已完成 | `docker-compose.yml` 已编排 `web`、`api`、`postgres`、`minio`、`redis`，并新增 `apps/api/Dockerfile`、`apps/web/Dockerfile`、`apps/web/nginx.conf` |

### 9.2 未完成

| 模块 | 状态 | 说明 |
| ---- | ---- | ---- |
| 线上 Demo | 未完成 | 当前仅提供本地运行方式 |
| CI/CD | 未完成 | 未发现 `.github/workflows` |
| 独立多智能体 worker | 未完成 | 已有 decentralized 两阶段流程，但没有队列化 sub-agent worker |

### 9.3 Mock / MVP 部分

| 模块 | 类型 | 说明 |
| ---- | ---- | ---- |
| `CREATE_STATIC_GENERATION=true` | Mock / 测试模式 | 可生成确定性静态测试产物，不调用真实 LLM |
| Seed 游戏 bundle | MVP stand-in | 部分示例 bundle 通过后端 stand-in 路由提供 HTML |
| Safety scan | MVP | 已有基础扫描，但不是生产级 |
| Maintenance 审核策略 | MVP | 提供基础审核、重试、标记 reviewed，复杂策略待扩展 |
| Worktree cleanup | MVP | 成功自动清理、失败保留，后续可加入更完整生命周期管理 |

### 9.4 下一阶段迭代计划

| 分类 | 工作安排 | 产出 |
| ---- | -------- | ---- |
| 前端 | home界面的排版还可以优化，划分为四个板块：自己的游戏、推荐的游戏、关注作者的游戏和最热/最新游戏 | 首页信息架构更清晰，后续推荐和社区功能有明确入口 |
| 前端 | 创作者界面的创作流程显示优化，合并非LLM模块，并给LLM生成时添加计时器 | Create timeline 更聚焦，用户能看到 LLM 阶段耗时 |
| 前端 | 优化profile的显示，增加新的功能 | Profile 从记录展示扩展为创作者主页和管理入口 |
| 前端 | 对于admin账号监测失败创作、后台异常的显示优化，增加自动捕获和分类脚本/算法迭代优化流程 | Maintenance 页面能更高效地聚合失败创作、异常和迭代建议 |
| 前端 | 拆分 `apps/web/src/main.tsx` 中的 Create、Profile、Maintenance、API client、hooks 和通用组件 | 降低单文件复杂度，方便后续 UI 迭代和测试补充 |
| 前端 | 增加前端自动化测试脚本，例如组件渲染、Create timeline 状态机、Profile run detail、Maintenance 表格 | 形成独立于 `npm run build` 的前端回归验证 |
| 后端 | 解耦serve，拆分功能模块 | 后端服务边界更清晰，便于维护和团队协作 |
| 后端 | 优化搜索模块，用redis缓存用户和游戏信息，加快搜索，避免缓存三剑客问题 | 搜索和推荐查询更快，缓存穿透、击穿、雪崩风险更低 |
| 后端 | 增加LLM的api默认接口，充值服务等盈利能力服务 | 降低新用户配置成本，并为商业化能力预留接口 |
| 后端 | 正式上限换用go或java搭建后端，提高并发性能、稳定性和团队开发维护能力 | 为正式上线后的高并发和长期维护做技术栈准备 |
| 后端 | 修复 `test_agent_tools.py` 的工具示例 fixture/context，使 `registry.run_examples()` 在默认测试上下文下稳定通过 | 后端测试脚本恢复 12/12 通过 |
| 后端 | 将 FastAPI `BackgroundTasks` 升级为可靠任务队列或 worker 机制，补充任务持久化、超时、重试、并发控制 | Create 长任务和 LLM 调用更稳定，服务重启后可恢复 |
| Agent | 优化提示词，增加规则限制，同时在验证阶段设置强约束和反馈 | 减少 LLM 输出格式错误，并让失败反馈进入下一轮修复 |
| Agent | 新增局部修复工具 | 支持只修复生成游戏中的局部问题，降低整包重生成成本 |
| Agent | 封面智能体改为可选项 | 用户或策略可选择跳过封面生成，避免封面失败阻塞游戏发布 |
| Agent | 将Decentralized作为插件接入其他策略中，模拟中心化多智能体架构并且激发user创作潜力 | 去中心化创意能力可以复用于 React、Plan、Refine 等策略 |
| Agent | 自动生成潜在的创作方法做第一步引导 | Create 初始阶段给用户更多可选方向，降低空白 prompt 成本 |
| Agent | 完成 decentralized 的独立 sub-agent worker loop，并明确 Planner / Asset / GameCode / Build / Safety / Publisher 的输入输出契约 | 从 stage contract 进一步升级为可恢复、可审计的真实 multi-agent 编排 |
| Agent | 增强安全扫描，从字符串级规则扩展到 HTML/JS AST、DOM API、远程资源、CSP 和资源限制 | 降低生成游戏绕过 iframe/sandbox 安全边界的风险 |
| 前后端连接 | 创作时切换界面不会影响后端正常创作。 | Create 后台任务与前端页面生命周期解耦，刷新或切换页面后仍可恢复进度 |
| 前后端连接 | 添加关注、评论、分享等玩家社区功能 | 增强玩家社区互动和创作者传播能力 |
| 前后端连接 | 优化创作回滚，支持重复创作 | 支持版本回退、多次尝试和失败后继续创作 |
| 前后端连接 | 增加游戏标签、玩家标签、创作标签等多标签，用来为用户创作和主页推荐提供参考 | 为首页推荐、搜索、创作引导和用户画像提供结构化数据 |
| 前后端连接 | 增加 CI/CD，自动运行前端 build、后端 smoke、Agent tests，并发布 `api` / `web` 镜像到 GHCR 或 Docker Hub | 交付方和测试方可以用固定镜像启动，不依赖本机构建环境 |
| 前后端连接 | 配置线上 Demo、Google OAuth app、生产密钥和独立运行域名 | 提供可访问的演示地址，并降低本地环境差异带来的对接成本 |
| 前后端连接 | 处理 Docker registry mirror 限流问题，明确可用镜像源或预构建镜像分发方式 | 避免 `429 Too Many Requests` 阻断 Docker 首次构建 |
| 数据库 | 不断优化sql数据库中的索引效率 | 提升列表、搜索、Profile、Maintenance 和推荐相关查询性能 |
| 数据库 | 为新功能同步创建表 | 社区、标签、充值、默认 LLM 服务、创作回滚等功能具备正式数据结构 |
| 数据库 | 协同优化redis和sql | 明确 SQL 事实源与 Redis 缓存/队列/计数职责，减少一致性问题 |
| 数据库 | 引入 Alembic migrations，替代仅依赖 `apps/api/db/init/*.sql` 的 schema 初始化方式 | 后续 schema 变更可追踪、可升级、可回滚 |
| 数据库 | 继续完善测试数据库、MinIO bucket、Redis DB 的隔离校验和清理报告 | 避免测试污染真实开发数据，管理员视图更干净 |
