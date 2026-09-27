# GameWeare AgentScope Java 2.0.3 实施方案与验收记录

更新：2026-09-27。本文以 [AgentScope Java v2 官方文档](https://java.agentscope.io/v2/zh/docs) 和 v2.0.3 源码接口为准。`agent-sandbox` 的 Kubernetes CRD 以 [项目官方文档](https://agent-sandbox.sigs.k8s.io/docs/getting_started/) 为准。

## 目标与边界

- 保留现有 `chat`、`react`、`plan`、`refine`、`decentralized` 模式、Create API、游戏版本和 MinIO 产物。新建任务不使用本地 Token 预留，额度由模型服务商 API 判断；Spring Boot 的 MySQL 事务仍决定审批、用量记录和发布。
- 每个 `create_jobs.id` 对应唯一 AgentScope `sessionId`，沙箱 `IsolationScope.SESSION`。AgentScope Harness 在 API/Worker 进程编排和调用模型；不可信文件操作和命令由配置的 Docker 或 Kubernetes 沙箱执行。
- 子智能体由官方 `SubagentDeclaration` 定义，以 Harness 内置 `agent_spawn` 分派、`agent_send` 沟通；异步任务使用 `task_output` 或 `wait_async_results`。不自建 Agent 间消息协议。参见[官方子智能体文档](https://java.agentscope.io/v2/zh/docs/harness/subagent)。
- Kubernetes 使用 AgentScope `KubernetesFilesystemSpec` 对接 `agent-sandbox` 的 `SandboxTemplate`、`SandboxWarmPool`、`SandboxClaim`；不用 `batch/v1 Job` 假装框架沙箱。参见[官方沙箱文档](https://java.agentscope.io/v2/zh/docs/harness/sandbox)。

## 已完成的代码

| 部分 | 实现 |
| --- | --- |
| 引擎分流 | `create_jobs.engine` 固定任务创建时使用的 `legacy` / `agentscope` 引擎；`AGENT_ENGINE` 仅影响新任务，默认 `legacy`，避免旧审批任务中途切换。 |
| Harness | `AgentScopeCreateEngine` 用 `HarnessAgent`、`OpenAIChatModel`、`RuntimeContext(userId, sessionId=jobId)` 和 `MysqlDistributedStore`。模型请求走本机短期令牌网关，再由现有 `LlmEndpointPolicy` 校验域名和 DNS 答案。 |
| 多智能体 | `plan` 的 Planner、`decentralized` 的三个候选角色保留各自的持久子会话，但使用 `WorkspaceMode.SHARED` 共享当前任务的沙箱文件系统。AgentScope Java 2.0.3 仅在此模式下向子智能体传递父级沙箱后端。父 Agent 使用内置 `agent_spawn` / `agent_send`，同步分派由官方 `AgentSpawnTool.CTX_FORCE_SYNC` 控制。中间件记录分派目标，缺少要求的角色即拒绝预览。 |
| 沙箱与恢复 | `KubernetesFilesystemSpec` 指向指定 Namespace/WarmPool；本地可选官方 `DockerFilesystemSpec`，每个任务创建无网络、只读根文件系统和独立临时工作区的容器。`IsolationScope.SESSION`；分布式 store 自动注入 MySQL AgentState、JDBC 快照和执行锁。Windows 上对 Docker CLI 的 shell 参数采用 Base64 包装，避免 `write_file` 的命令替换被 Windows 参数转义破坏。实际 CRD 恢复仍需集群验收。 |
| 项目记忆 | 每次成功并通过校验的版本写入 `agent_project_memory`，下次仅按同一 `userId + projectId` 读取最近五条摘要，并标记为历史数据；会话与文件快照仍由 AgentScope 分布式 store 维护。 |
| 产物 | 模型在沙箱写 `index.html`，先调用 `validate_game_html`（复用 `ArtifactValidator`）检查同一文件，再用官方 `deliver_artifact` 交付；宿主核对任务 session、文件名、体积和已验证内容的 SHA-256。失败后可修改并重新验证，未验证或验证后又修改的文件不会接收。交付后才写 MinIO。 |
| 封面 | 所有游戏模式先交付并验证 `index.html`。新游戏之后启动独立 `CoverReActEngine`，用完整的已验证游戏源码作为首轮只读上下文，使用独立 session 和沙箱生成 `cover.svg`。`validate_cover_svg` 把具体解析与安全错误作为工具结果反馈给模型；模型修复后必须重新校验，且只能交付已验证的相同字节。优化现有游戏复用原始封面。封面阶段异常会记录降级原因并使用本地静态封面。 |
| 任务清单 | `HarnessAgent.enableTaskList(true)` 启用官方 `TodoTools.todo_write` 与 `TaskReminderMiddleware`，每轮推理提醒当前任务；system prompt 明确要求实现、验证、交付的顺序。 |
| 用量 | 官方 `MiddlewareBase.onModelCall` 接收 `ModelCallEndEvent`，将每次调用先记为 pending，再记录提供方回复和输入/输出 token；无用量则失败，由提供方 API 判断额度。 |
| 沙箱运行时 | 独立 Java 17 HTTP 服务实现官方要求的 `/execute`、`/upload`、`/download/{path}`、`/list/{path}`、`/exists/{path}`；镜像包含 POSIX shell、GNU 命令、Python 3（供框架 `edit_file` 工具调用），运行时自身不含模型或生产凭证。 |
| K8s 清单 | `infra/k8s/agent-sandbox.yaml.template` 包含 Namespace、Pod 安全上下文、专用 ServiceAccount、配额、SandboxTemplate/WarmPool、默认拒绝出口和限定入口；需用集群实际 RuntimeClass 与镜像 digest 渲染。 |
| 本机运行 | `scripts/start-local-agentscope.ps1 -Mock` 启动 Spring Boot、前端及 Docker 基础设施。首次初始化 MySQL 时额外创建 AgentScope 自用 schema；浏览器游戏文档只允许配置的前端 Origin 嵌入，其他 API 保留默认 `X-Frame-Options`。本机 MinIO 镜像使用 Git 忽略的 `.env` 固定社区镜像 digest，生产应使用经过审核的镜像源。 |

`plan` / `decentralized` 仍走已有 MySQL 预览和用户审批状态机。AgentScope 会话状态与沙箱文件快照由 MySQL 持久化，同一 `jobId` 的审批后调用应恢复状态；MySQL 账本继续防重。`refine` 从旧版本只读导入，模型写新文件；旧版本不在沙箱里原地修改。

## 本机验收（模拟模型）

- `./scripts/e2e-verify.ps1 -Engine agentscope -Filesystem docker -UseExistingApi -MockBaseUrl http://127.0.0.1:8090`：23 项通过，覆盖注册、模型配置、chat 生成、独立 ReAct 封面生成与错误修复、MinIO 存储、发布、试玩文档、优化时保留原封面、plan 审批、三个候选子智能体和 Token 账本。
- 浏览器打开 `/play/<slug>` 后，沙箱 iframe 显示 Canvas、持续增加分数；方向键使玩家方块移动。首次浏览器检查发现游戏文档的 `frame-ancestors 'self'` 与默认 `X-Frame-Options: DENY` 阻止跨端口嵌入，现已针对该文档修正。
- 这验证本机 Docker 路径和模拟工具调用，不代表真实 DeepSeek 协议或 Kubernetes 集群已经通过验收。

## 尚未完成的验收和风险

1. **集群实测**：当前开发机的 `kubectl` 没有 current context。需安装与锁定 `agent-sandbox` controller/CRD，提供 gVisor 或 Kata RuntimeClass、支持 NetworkPolicy 的 CNI 与镜像仓库。部署前把模板中的 `${AGENT_RUNTIME_IMAGE}` 换为 digest，`${SANDBOX_RUNTIME_CLASS}` 换为集群实际值。验证两任务并行时 Pod/文件/记忆不串，审批后跨 API 实例恢复，SandboxClaim 释放后资源回收，沙箱无法访问 API 以外网络、Secret 或 Kubernetes API。
2. **提供方协议**：新引擎调用非流式 OpenAI Chat Completions，旧引擎调用 Responses。已配置的 DeepSeek 地址/模型要跑真实 POC，确认工具调用、图片、用量和超时行为。模型返回 JSON、调用子智能体与交付文件依赖实际模型能力；输出会做结构校验，未达契约即失败。
3. **模型网络出口**：已接入仅接受回环地址和短期令牌的本机网关，真实 API Key 仅在控制面，网关使用项目现有的 DNS 校验、禁代理和禁跳转连接器。生产仍需用网络防火墙/出口代理做第二层限制，并在集群验证 DNS 重绑定、跳转、代理变量和请求超时。沙箱网络出口默认拒绝。
4. **计费失败窗口**：已新增逐调用 `agent_model_calls` 和未知用量状态，但已有 Worker 在生成异常时退款。提供方已计费但响应丢失、跨阶段重试或某子 Agent 用量缺失时，仍需人工/自动对账及明确的退款策略，才能生产灰度。
5. **事件与审计**：现有 `create_run_steps` 只记录少量阶段，不是逐事件 Agent 轨迹。应增加 append-only 运行事件与脱敏 SSE 重放，不把内部推理、API Key 或私人图片传给前端。
6. **沙箱 runtime 压测**：已做本地 HTTP 契约冒烟；需要在真实 controller 上验证 multipart、快照、并发命令、超时子进程、文件大小和 symlink 逃逸。尤其要确认 `SandboxTemplate` 的 `emptyDir` 加 JDBC 快照能在 Pod 重建后正确恢复。

## 启用顺序

1. 本地：`docker build -t gameweare-agent-sandbox-runtime:local apps/agent-sandbox-runtime` 和 `docker compose build api`；运行后端测试。
2. 集群：安装固定版本 controller/CRD；构建并推送 runtime 镜像；执行 `./scripts/render-agent-sandbox.ps1 -Image '<仓库>@sha256:<64位摘要>' -RuntimeClass '<集群实际名称>'` 生成清单，再应用到集群；核查 ServiceAccount RBAC、Pod Security、NetworkPolicy、RuntimeClass 和沙箱 HTTP 契约。
3. 联调：先使用受控测试账号和测试模型；覆盖五模式、审批/拒绝、图片、两个 API 实例、RabbitMQ 重投、提供方用量记录及 MinIO 试玩。
4. 安全和计费补齐后，才在测试/灰度环境设置 `AGENT_ENGINE=agentscope`。旧任务保持 `engine=legacy`，可通过将开关调回 `legacy` 回滚新任务。

生产验收标准：所有五种模式完成端到端试玩；每次生成有独立 SandboxClaim/Pod 或可验证的同任务恢复；跨任务不能读取文件/记忆；错误和重试后只提交一个有效版本并正确结算；受控模型出口、沙箱拒绝外网和密钥不可见均经真实集群测试。
