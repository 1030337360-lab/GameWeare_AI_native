# Agent 生成实现

## 任务入口与双引擎

[`CreateService`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 把创建时的 `AGENT_ENGINE` 写入 `create_jobs.engine`；默认值在 [`application.yml`](../apps/api-java/src/main/resources/application.yml) 中是 `legacy`。运行中的任务不会随环境变量切换引擎。[`CreateWorker`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateWorker.java) 按该字段分流：旧引擎直接调用模型的 Responses 风格接口；新引擎调用 [`AgentScopeCreateEngine`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentScopeCreateEngine.java)。

| 模式 | 用户可见流程 | 代码边界 |
| --- | --- | --- |
| `chat` | 多轮访谈 → 游戏画像 → 用户明确确认 → `react` 生成 → 验证 → 预览/发布 | 独立 Chat 会话；不直接进入生成 Worker |
| `react` | 迭代编写并使用验证工具修复 | AgentScope 使用 Harness 工具循环；`legacy` 先规划，再通过 Responses 函数调用反复提交游戏 HTML 给校验工具，仍不具备 Harness 的完整任务管理能力 |
| `plan` | 先看规划，批准后再生成 | AgentScope 预览阶段必须调用官方 `agent_spawn` 分派 `planner`；批准状态写 MySQL |
| `decentralized` | 三个方向候选，选择并确认后生成 | AgentScope 必须分派 `concept-1..3`；候选与决定写 MySQL |
| `refine` | 基于同项目旧版本优化 | 只允许 `createType=opt`，读取旧 HTML 与已确认项目记忆；发布前保持旧公开版本 |

`plan` 和 `decentralized` 的预览/审批由 [`CreateService`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 与 Worker 共同维护。子智能体使用 AgentScope 的 `SubagentDeclaration`、`agent_spawn`、`agent_send`；项目没有自造智能体消息协议。

## Chat 访谈与 ReAct 交接

[`CreationChat`](../apps/web/src/components/CreationChat.tsx) 提供对话气泡、历史会话、当前画像和确认按钮；Chat 表示自然语言需求讨论，ReAct 表示生成阶段的推理与工具行动循环，不是 React 前端框架。用户可以直接选择 ReAct，也可以先 Chat 后确认。已有游戏的 Chat 会话保存本人项目 ID，确认后用 `createType=opt` 进入同项目优化，不替换原公开版本。

[`CreationChatService`](../apps/api-java/src/main/java/com/gameweare/api/create/CreationChatService.java) 与 [`CreationChatMapper`](../apps/api-java/src/main/java/com/gameweare/api/create/dao/CreationChatMapper.java) 保存 V14 的 `create_chat_sessions/create_chat_messages`。一次成功回复把用户消息、助手消息、读取过的技能 ID、模型返回用量及新画像同事务提交。模型调用在数据库事务外执行；MySQL 条件认领、独立租约 token 和画像 revision 防并发覆盖，五分钟租约到期后可恢复。失败不会留下半轮消息或占用券。请求 ID 用于重试幂等，不能复用来发送不同内容。

[`CreationGuideModel`](../apps/api-java/src/main/java/com/gameweare/api/create/CreationGuideModel.java) 每轮携带当前画像和最近六轮对话，通过现有出口校验的 Responses 接口调用模型。模型收到技能目录，可自主调用 `read_creation_skill`；服务端读取白名单技能并把内容作为 `function_call_output` 回传，再得到自然语言回复与结构化画像。该工具只读指导文本，不执行脚本、生成源码或任意读取文件。每轮最多四次模型请求，每次45秒；未成功结束的技能循环会明确失败。前端在等待期间显示回复状态，整轮完成后显示消息与画像。

画像包含名称、主题与玩家角色、类型、核心循环、操作、规则、胜负目标、美术与首版范围；未明确的字段保持为空，助手每轮优先问一两个关键问题。主题、循环、操作、规则和目标齐备后，页面允许用户确认；模型说“开始”不构成确认。`confirm` 持有会话行锁，验证 revision，按 `chat:<sessionId>` 创建一个 `agentMode=react` 任务并记下 job ID。任务、券预留、Outbox 和会话确认共享 Spring 事务；重复确认返回同一个任务。历史任务的 `chat` 模式仍可读取，但 `POST /create/jobs` 的新 `chat` 请求返回409，引导客户端使用 Chat API；省略生成模式时默认 ReAct。

### 维护创作技能仓库

技能在 [`creation-skills`](../apps/api-java/src/main/resources/creation-skills) 中随 API JAR 发布：`catalog.json` 保存 ID、名称、简介和标签，`<id>/SKILL.md` 保存指导内容。初始提供想法访谈、街机、解谜、视觉操作和已有游戏优化五项。增加技能时用唯一的字母/数字/短横线 ID，在目录中注册并添加对应文件，再重建 API；启动会校验重复 ID、缺失文件和12KB大小上限。用户消息不能修改仓库，模型工具参数只能引用注册 ID。不是 Codex 本机技能目录，也不需要把用户模型密钥写进技能文件。

对话费用使用创建会话时选择的 BYOK 或官方模型；官方模式每轮确认券仍可用，但不预扣券，最终确认才占券。对话每用户每分钟最多20次新建/发言，每会话最多30轮；实际调用次数与用量记录在消息表。当前未接入语音录音、任意技能上传、在线技能编辑或外部技能市场；自然语言访谈通过网页文字完成。

## AgentScope、记忆与沙箱

### 同一用户并行创建

新建游戏请求不传 `projectId`，`CreateService` 会为每个任务建立独立 `create_projects` 与 `create_jobs` 记录；因此同一用户可以同时提交多个不同游戏。只有对**同一个已有项目**执行继续优化时，才通过项目行锁和活动任务检查串行化，避免两个版本同时覆盖同一项目。一个 `jobId` 对应一个 AgentScope session、独立 workspace 和一个沙箱 slot；不能用 `userId` 作为沙箱隔离键。

`CreateWorker` 的 RabbitMQ 监听器默认在每个 API 实例启动 **2 个并发消费者**，可用 `AGENT_WORKER_CONCURRENCY` 调整；队列 prefetch 为 1，长任务不会把后续消息预取到忙碌消费者。多个 API 实例共享同一队列时，总运行上限大致是实例数乘每实例消费者数，还受数据库连接池、模型服务限流和 Kubernetes Pod 配额约束。任务级 Redisson 锁和 MySQL `lease_token` 继续防止同一任务被重复提交产物。`SandboxWarmPool` 模板预热 2 个沙箱，命名空间 Pod 配额 30；预热数量不是全平台并发上限，实际可调度数量还要看 controller 与集群资源。为避免耗尽数据库连接或模型额度，调大消费者数前应压测并监控 Rabbit 队列深度、Pod Pending、Agent 心跳与外部模型的 429/超时。

本地 `docker-compose.yml` 默认 `AGENT_ENGINE=legacy`，且项目的 k8s 模板不会自动安装 controller。要真正看到每个任务由 Kubernetes 沙箱 Pod 执行，需部署模板依赖的 agent-sandbox controller/CRD、运行时镜像与所需 RuntimeClass，配置 `AGENT_ENGINE=agentscope` 和 `AGENT_FILESYSTEM=kubernetes`，再检查 claim 与 Pod 的创建和回收。仅运行本地 k8s 基础节点不代表创作任务已经在 k8s 运行。

`AgentScopeCreateEngine` 建立 `HarnessAgent`，启用任务清单、用量中间件及 MySQL 分布式状态存储，`RuntimeContext.sessionId` 使用任务 ID。`agent_project_memory` 保存已验证版本的项目摘要，后续优化只读取同用户、同项目的有限历史；它不替代完整源码。每个任务的工作区独立，结束后清理临时目录。

`AGENT_FILESYSTEM` 选择 `local`、`docker` 或 `kubernetes`。本地 Docker 路径使用 AgentScope `DockerFilesystemSpec`，设置无网络、只读根文件系统、临时工作区及 CPU/内存限制。Kubernetes 路径使用 `KubernetesFilesystemSpec` 和 [`infra/k8s/agent-sandbox.yaml.template`](../infra/k8s/agent-sandbox.yaml.template)；生产启动守卫只接受 Kubernetes。`local` 模式仅用于受控开发，不提供同等级别的隔离。

模型密钥留在 API 控制面。[`AgentModelGateway`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentModelGateway.java) 以短期令牌提供仅回环可访问的 Chat Completions 代理，再按 [`LlmEndpointPolicy`](../apps/api-java/src/main/java/com/gameweare/api/create/LlmEndpointPolicy.java) 检查模型出口。沙箱不会直接拿到真实 API Key。代理允许 64 MiB 请求和 32 MiB 响应，单次读取等待 10 分钟、完整请求最多 20 分钟；这些是传输保护，不是模型上下文容量。AgentScope 引擎没有本地 Token 或工具迭代次数上限；模型服务商的额度、任务超时和资源限制仍然生效。若 Agent 在未交付时结束，服务端会继续提醒，只有连续重复同一无进展答复才以明确原因终止。

Worker 持有任务级 Redisson 锁时不设置固定租期，客户端看门狗自动续期；MySQL `lease_token` 仍是最终写入围栏。每 30 秒检查运行线程、分布式锁归属和最近进度，并仅在健康时续 MySQL 租约。AgentScope 模型代理每次请求和响应都会更新进度；默认 25 分钟无进度视为停滞，取消本实例请求并令租约到期，由重试恢复。这个检查监测 Java Worker 与模型交互，不能代替 Docker/Kubernetes 自身的容器健康探针；容器执行失败仍由 AgentScope 错误或超时反馈。配置为 `AGENT_STALL_TIMEOUT_MINUTES`。

## 游戏产物的硬门槛

游戏 Agent 必须写 `index.html`，调用 [`validate_game_html`](../apps/api-java/src/main/java/com/gameweare/api/create/GameValidationTool.java) 检查当前文件，修正逐条诊断，再调用 `deliver_artifact`。校验工具保存通过时的 SHA-256；交付回调再次比较文件字节，防止“校验后修改”。[`ArtifactValidator`](../apps/api-java/src/main/java/com/gameweare/api/create/ArtifactValidator.java) 只检查 HTML 包装、自包含资源和 JavaScript 语法，不执行游戏，也不能证明可玩性。Worker 在入库前会再次校验。

`legacy` 引擎的最终生成要求模型调用 `validate_game_html` 函数；服务端用同一 `GameValidationTool` 校验提交的完整 HTML，将 `FAIL` 诊断作为 `function_call_output` 回传，直到出现 `PASS` 才接受产物。每轮显式回传模型的原始输出项（包括思考项和函数调用）及工具结果，兼容不支持 `previous_response_id` / `store` 的无状态 Responses 接口。部分兼容接口会忽略强制工具调用：若返回普通文本，服务端仍通过相同的校验器检查完整 HTML；不合格时把诊断作为用户消息继续送回模型。连续重复同一无进展答复会报明原因。各轮用量累加；没有本地工具调用次数上限。规划预览仍为普通模型请求，因其不是游戏产物。
每次校验的通过或失败及具体诊断写入任务轨迹的 `game_validation_tool` 步骤，不保存候选源码。

新游戏的封面在游戏 HTML 验证后由独立的 [`CoverReActEngine`](../apps/api-java/src/main/java/com/gameweare/api/create/CoverReActEngine.java) 生成：把已验证的完整源码和原始需求传给封面 Agent，要求写 `cover.svg`、调用 [`validate_cover_svg`](../apps/api-java/src/main/java/com/gameweare/api/create/CoverValidationTool.java)，并交付相同版本的文件。SVG 不合格或阶段失败时记录原因并使用本地安全回退封面。优化旧游戏时不重新生成封面，沿用原封面。

模型逐调用用量记录在 `agent_model_calls`，任务汇总在 `model_usage_events`；响应丢失时状态可能变成 `unknown`，不能把它当成零成本。[`AgentUsageReconciliation`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentUsageReconciliation.java) 只标出待核对调用，不会凭猜测补写服务商账单。

## 验收边界与后续

本地 Mock 模型与 Docker 沙箱由 [`start-local-agentscope.ps1`](../scripts/start-local-agentscope.ps1)、[`e2e-verify.ps1`](../scripts/e2e-verify.ps1) 验证。真实 DeepSeek 工具调用、图片输入、跨实例恢复、真实 Kubernetes controller/RuntimeClass/NetworkPolicy、沙箱逃逸与提供方费用对账仍需分别验证。上线顺序见 [迭代路线](iteration-roadmap.md)；官方框架接口以 [AgentScope Java v2 文档](https://java.agentscope.io/v2/zh/docs) 为准。

Chat 独立回归由 [`chat-verify.ps1`](../scripts/chat-verify.ps1) 配合 `mock_llm.py` 验证：先返回不完整画像、第二轮补全，确认前没有任务；检查工具读取技能、重试不重复、越权404、旧画像409、确认只创建一个 ReAct 任务、最终校验与发布。单测另覆盖模型失败、独立租约 token、参数边界与白名单技能。Mock 不证明真实模型的访谈质量或提供方工具兼容性，正式上线仍需用目标模型验收。
