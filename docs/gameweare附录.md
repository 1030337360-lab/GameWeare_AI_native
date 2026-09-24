# Gameweare MVP 附录：系统设计补充说明

本文档作为 `gameweare.md` 的附录，单独展开系统设计中的总体架构、数据模型、Agent 编排、远端产物协议、安全隔离、失败恢复和可观测性说明。

## 1 总体架构

Gameweare MVP 采用前后端分离架构，并通过异步 Create 任务把用户创作请求、Agent 生成、对象存储发布和前端实时展示串联起来。

整体协作关系如下：

| 模块 | 主要职责 |
| ---- | -------- |
| 前端 Web | 负责 Home、Play、Create、Profile、Maintenance 等页面展示；Create 过程中通过 SSE 接收实时进度 |
| 后端 API | 负责认证、游戏目录、播放 manifest、Create job、Profile、Maintenance、上传和发布接口 |
| 异步任务 | `POST /create/jobs` 快速返回 job/run 信息，后台继续执行 LLM 生成、工具调用、封面生成、上传和发布 |
| Agent Orchestrator | 根据 `createType` 和 `agentMode` 选择策略，组织 Prompt、工具、记忆、运行日志和产物解析 |
| PostgreSQL | 作为业务事实源，保存用户、游戏、版本、素材、任务、Agent run、发布状态、播放事件和审计数据 |
| Redis | 保存短期状态、JWT 活跃状态、Create 进度缓存、SSE pub/sub、播放统计缓冲、AI config 热缓存 |
| MinIO | 保存游戏 HTML、manifest/source、封面、上传素材、run log、memory 对象等远端产物 |
| 运行时隔离 | Create run 使用 `.worktrees/create-{runId}` 或 stub workspace，避免生成代码污染主仓库 |

Create 主链路：

1. 用户在前端提交 Prompt 和可选图片素材。
2. 后端创建 `generation_jobs`、`create_runs`、TaskState 和 workspace。
3. 后端根据 `createType + agentMode` 选择 Agent 策略。
4. Agent 渲染 prompt，调用 LLM 或工具，并把关键步骤写入 `create_run_steps` 和 run log。
5. 生成结果通过 parser normalization 转换为标准游戏包。
6. 后端执行安全扫描。
7. 游戏 HTML、封面、manifest/source 上传到 MinIO。
8. PostgreSQL 写入 `games`、`game_versions`、`assets`、`job_artifacts` 等发布元数据。
9. 前端通过 SSE 实时展示生成流程，完成后跳转 Play 页面。

## 2 数据模型

Gameweare 的核心数据模型围绕用户、游戏、版本、素材、生成任务、Agent 日志和发布状态展开。

| 数据表 / 实体 | 建模说明 |
| ------------- | -------- |
| `users` | 用户基础信息、角色、状态、创建时间 |
| `auth_accounts` | 邮箱、Google 等认证账户；OAuth token 使用加密字段保存 |
| `user_sessions` | 登录 session 和 JWT 相关状态 |
| `user_ai_configs` | 用户 LLM 配置，保存 base_url、model、provider 和加密后的 API key |
| `games` | 游戏主表，保存 slug、标题、作者、可见性、发布状态、计数、当前版本、封面资产引用 |
| `game_versions` | 游戏版本表，保存 version_no、runtime、entry_file、manifest_url、document_url、安全状态和构建状态 |
| `assets` | MinIO 或外部资源元数据，包括 object_key、content_type、size、sha256、kind、width/height |
| `generation_jobs` | Create 任务，保存输入 payload、状态、错误、game_slug、project_id、run_id |
| `job_artifacts` | 生成任务和产物资产的关联关系 |
| `agent_projects` | 用户创作项目，支持 init/opt 生命周期和项目级状态 |
| `create_runs` | 单次 Create Agent run，保存策略、状态、summary、log object key、task id |
| `create_run_steps` | 结构化步骤日志，保存 lifecycle、LLM、tool、error、cover、plan、decentralized 等关键记录 |
| `agent_memory_index` | 持久记忆索引，指向 MinIO 中的 memory 对象 |
| `agent_task_state_index` | TaskState checkpoint 和 resume 状态 |
| `agent_workspace_runs` | worktree/stub workspace 运行记录 |
| `play_events` | 播放、开始、结束、加载失败等事件 |
| `game_likes` / `game_favorites` / `game_comments` | 玩家社区互动数据 |
| `moderation_reviews` | 管理员审核和处理记录 |
| `model_usage_events` | 模型 token、延迟、成本和调用指标 |
| `audit_logs` | 关键后台操作审计记录 |

发布状态主要由 `generation_jobs.status`、`create_runs.status`、`games.publish_status`、`game_versions.safety_status`、`game_versions.build_status` 协同表达。

## 3 Agent 编排

当前 Agent 编排采用自研策略层 + LangGraph 的方式，而不是直接引入完整的外部 Agent 产品框架。

### 框架选择

| 方案 | 当前处理 |
| ---- | -------- |
| LangGraph | 已接入，用于 ReAct 和其他策略的图式执行、状态流转、工具调用和停止判断 |
| 自研状态机 | 已保留，用于 Create job、run step、TaskState、plan approval、decentralized selection 等业务状态 |
| OpenClaw / Pi Agent 等 | 当前未直接接入，主要原因是 MVP 需要更强的本地可控性、日志可审计性和与现有数据库/MinIO/Redis 的紧密集成 |
| Hermes | Agent 记忆系统参考 Hermes 的分层记忆思想，但没有直接依赖 Hermes 运行时 |

### 策略拆分

| 策略 | 编排方式 |
| ---- | -------- |
| `chat` | 单次生成，适合基础 Create |
| `react` | ReAct 单 Agent，允许 LLM 输出 JSON tool call 或 final，最多 4 轮，支持 provider 502 recovery |
| `plan` | 两阶段审批流，先生成 plan preview，用户 Accept 后继续生成，Reject 则取消但保留 run log |
| `refine` | 面向已有项目的继续优化，加载既有游戏、历史上下文和项目 preview |
| `decentralized` | 两阶段创意流，先生成 3 个静态方向，用户选择确认后生成最终游戏和封面 |

### Hermes 风格记忆系统

Agent 记忆系统参考 Hermes 的分层记忆设计，重点不是让模型无限保留上下文，而是把记忆拆成可压缩、可检索、可审计的多层结构：

| 记忆层 | Gameweare 中的对应实现 |
| ------ | ------------------- |
| 短期记忆 | Redis 中保存最近 Create 状态、recent history、SSE event、AI config 热缓存 |
| 长期记忆 | `agent_memory_index` 记录持久记忆索引，MinIO 保存 memory 对象和 run log |
| 情节记忆 | `create_run_steps` 和 run log 记录每次生成过程中的 LLM 调用、工具调用、错误、用户选择 |
| 语义摘要 | recent_8_history、persistent_memory_summary、Profile/Maintenance 中的脱敏摘要 |
| 程序性记忆 | strategy prompt、tool metadata、output parser、safety scan、normalization rules |
| 任务状态记忆 | TaskState checkpoint 保存 run 的 resume_status、plan approval、workspace 状态 |

这种设计的目的：

1. 减少每轮 LLM prompt 的上下文膨胀。
2. 让失败 run 能被管理员复盘。
3. 让后续 refine/continue 能读取已有项目和历史摘要。
4. 避免把 API key、base64、大 HTML、完整工具响应直接暴露给前端或 prompt。
5. 为后续 multi-agent 的共享状态、角色协作和冲突解决提供基础。

## 4 远端产物协议

生成游戏通过远端产物协议交付给 Play 页面，而不是直接把完整 HTML 固定在前端代码中。

### 文件结构

一次成功发布通常包含：

```text
games/{gameId}/versions/{versionNo}/index.html
games/{gameId}/versions/{versionNo}/manifest.json
games/{gameId}/versions/{versionNo}/source.json
games/{gameId}/versions/{versionNo}/cover.{png|webp|svg}
```

其中：

| 文件 | 说明 |
| ---- | ---- |
| `index.html` | 可运行的 iframe HTML5 游戏本体，是发布硬门槛 |
| `manifest.json` | 后端生成的播放协议，描述 entry、runtime、assets、sandbox 等 |
| `source.json` | 记录生成来源、prompt 摘要、strategy metadata、normalization warnings、token metrics |
| `cover` | 游戏封面资产，优先由 Cover Agent 生成，也可降级为默认封面 |

### Manifest 协议

Play 页面通过：

```text
GET /play/{game_id}/manifest
```

获取运行协议，核心字段包括：

| 字段 | 说明 |
| ---- | ---- |
| `id` | 游戏 ID / slug |
| `title` | 游戏标题 |
| `version` | 当前版本号 |
| `entry` | 入口文件，通常是 `index.html` |
| `bundleUrl` | 入口文档或 bundle URL |
| `documentUrl` | 可直接加载进 iframe 的 HTML 文档 URL |
| `assets` | 附属资源 URL 列表，包括 cover 等 |
| `runtime` | 运行时类型，如 `iframe-srcdoc` |
| `sandbox` | iframe sandbox 权限，默认只允许 `allow-scripts` |

前端 Play 页读取 manifest 后，将 `documentUrl` 对应 HTML 拉取为 `srcDoc`，再放入 sandboxed iframe 运行。

## 5 安全隔离

安全隔离覆盖上传素材、Prompt Injection、任意生成代码执行、密钥保护和资源限制。

| 风险 | 当前处理 |
| ---- | -------- |
| 上传素材 | 上传资源写入 MinIO，并在 `assets` 中记录 content_type、size、sha256、owner 等元数据；后续可扩展扫描策略 |
| Prompt Injection | Prompt renderer 不向 LLM 注入 `projectId/runId/taskId/api_key` 等后端索引和密钥；工具调用必须匹配 schema |
| 任意生成代码执行 | 生成游戏只能在 sandboxed iframe 中运行，默认 sandbox 为 `allow-scripts`，不使用 `allow-same-origin` |
| 远程脚本和危险 API | safety scan 拦截远程脚本、eval、localStorage、parent 访问、pointer lock、危险 URL 等高风险能力 |
| 密钥保护 | 用户 LLM API key 使用 PostgreSQL `pgp_sym_encrypt` 加密保存，前端响应、run log、SSE event 不返回明文 key |
| 日志脱敏 | LLM prompt 只记录 prefix、字数、token metrics；base64、authorization、secret、token 等字段会被脱敏 |
| 工具治理 | Agent tools 使用 JSON envelope，声明 inputSchema、outputSchema、requires、sideEffects，错误统一 JSON 包装 |
| 运行时文件隔离 | Create run 写入 `.worktrees/create-{runId}` 或 stub workspace，不写主仓库 |
| 资源限制 | safety scan 检查总大小、入口文件大小、artifact 数量等限制，避免超大产物进入发布链路 |

当前安全扫描仍是 MVP 级别，后续计划升级到 HTML/JS AST、DOM API、CSP、独立运行域和更完整的资源配额。

## 6 失败恢复

Create 流程把失败拆成可记录、可展示、可重试的阶段，而不是静默返回预设游戏。

| 失败类型 | 当前恢复 / 处理方式 |
| -------- | ------------------- |
| 模型连接失败 | LLM adapter 将 timeout、HTTP 502、invalid response 等归类为 providerError，写入 `llm_call` failed step |
| ReAct 第二轮 502 | ReAct 路径有 recovery payload，使用更小上下文尝试恢复；恢复失败才标记 run failed |
| 模型输出非 JSON | parser 尝试从 markdown fence、`type=final` wrapper、`output` wrapper 中恢复 JSON |
| 缺少 manifest/source | 只要有有效 `index.html`，后端可补齐 `manifest.json` 和 `source.json`，记录 normalizationWarnings |
| 缺少有效 index.html | 视为硬失败，不发布游戏，不回退静态模板 |
| 安全扫描失败 | 写入 `safety_scan` failed、`run_failed`、`job_failed`，不发布游戏 |
| Cover Agent 失败 | 当前可降级为已有封面或默认封面，避免封面失败阻断游戏发布 |
| Plan 被拒绝 | run/job 标记 `canceled`，清理 Redis 临时缓存，保留 create_runs/create_run_steps 给管理员复盘 |
| Decentralized 被拒绝 | 清理 preview/selection 缓存，保留 run log，不创建 published game |
| 上传 MinIO 失败 | run/job failed，不写入 published game，错误摘要进入 SSE 和 Maintenance |
| 发布 SQL 失败 | run/job failed，保留 run log 和错误摘要，避免前端出现半发布状态 |
| Play 加载失败 | `/events/play` 可记录加载失败事件，用于后续统计和维护分析 |
| 前端断线/刷新 | 前端可通过 `/create/runs/{run_id}/steps` replay 已有步骤，通过 SSE afterStepNo 去重恢复 |

管理员侧通过 Maintenance 查看失败 create、后台异常、token 消耗、tool call 摘要和 run 路径，用于后续自动捕获、分类和算法迭代优化。

## 7 可观测性

可观测性覆盖生成过程、Agent 输入输出、用户操作、错误日志和演示证据。

| 观察对象 | 记录方式 |
| -------- | -------- |
| Create 生命周期 | `create_run_steps` 记录 `run_created`、`prompt_rendered`、`llm_generation_started`、`safety_scan`、`run_completed/run_failed` 等阶段 |
| LLM 输入输出 | 每次 LLM 调用记录 prompt prefix、英文词数、中文字符数、output tokens、provider usage、输出摘要，不记录完整 key |
| 工具调用 | 每次工具调用记录 toolName、参数摘要、涉及文件、ok/error、响应摘要 |
| Agent run log | MinIO 中保存 JSONL run log，SQL 中保存结构化摘要 |
| Memory | Redis 保存短期 memory/cache，MinIO + `agent_memory_index` 保存长期 memory 索引 |
| 用户操作 | 登录、播放、点赞、收藏、发布、删除、审核等写入 SQL 或 audit 相关表 |
| 错误日志 | providerError、parser error、safety issue、tool error、upload/publish error 写入 run step 和 Maintenance 视图 |
| Token 成本 | `model_usage_events` 和 `create_run_steps.metrics` 记录 token、延迟、模型和 provider 信息 |
| 前端实时证据 | SSE 推送 step、llm_call、tool_call、done、error、heartbeat，Create 页面实时展示 |
| Profile 复盘 | 创作者 Profile 项目详情展示脱敏 run timeline、LLM 摘要、tool 摘要、错误和 token 指标 |
| Maintenance 复盘 | 管理员查看失败任务、失败 run、后台异常、重试和审核记录 |
| 测试证据 | `gameweare.md` 第 8 节记录后端脚本、前端 build、Docker build、Compose 校验等验证结果 |

当前可观测性已经能支持 MVP 演示和失败复盘；下一阶段需要增强自动异常分类、错误聚合、趋势统计、成本报表和 CI/CD 测试证据归档。