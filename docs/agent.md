# Agent 生成实现

## 任务入口与双引擎

[`CreateService`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 把创建时的 `AGENT_ENGINE` 写入 `create_jobs.engine`；默认值在 [`application.yml`](../apps/api-java/src/main/resources/application.yml) 中是 `legacy`。运行中的任务不会随环境变量切换引擎。[`CreateWorker`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateWorker.java) 按该字段分流：旧引擎直接调用模型的 Responses 风格接口；新引擎调用 [`AgentScopeCreateEngine`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentScopeCreateEngine.java)。

| 模式 | 用户可见流程 | 代码边界 |
| --- | --- | --- |
| `chat` | 描述 → 生成 → 验证 → 预览/发布 | 生成阶段由所选引擎执行 |
| `react` | 迭代编写并使用验证工具修复 | AgentScope 使用 Harness 工具循环；`legacy` 只做规划与生成两次模型调用，不等同完整 ReAct |
| `plan` | 先看规划，批准后再生成 | AgentScope 预览阶段必须调用官方 `agent_spawn` 分派 `planner`；批准状态写 MySQL |
| `decentralized` | 三个方向候选，选择并确认后生成 | AgentScope 必须分派 `concept-1..3`；候选与决定写 MySQL |
| `refine` | 基于同项目旧版本优化 | 只允许 `createType=opt`，读取旧 HTML 与已确认项目记忆；发布前保持旧公开版本 |

`plan` 和 `decentralized` 的预览/审批由 [`CreateService`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 与 Worker 共同维护。子智能体使用 AgentScope 的 `SubagentDeclaration`、`agent_spawn`、`agent_send`；项目没有自造智能体消息协议。

## AgentScope、记忆与沙箱

`AgentScopeCreateEngine` 建立 `HarnessAgent`，启用任务清单、用量中间件及 MySQL 分布式状态存储，`RuntimeContext.sessionId` 使用任务 ID。`agent_project_memory` 保存已验证版本的项目摘要，后续优化只读取同用户、同项目的有限历史；它不替代完整源码。每个任务的工作区独立，结束后清理临时目录。

`AGENT_FILESYSTEM` 选择 `local`、`docker` 或 `kubernetes`。本地 Docker 路径使用 AgentScope `DockerFilesystemSpec`，设置无网络、只读根文件系统、临时工作区及 CPU/内存限制。Kubernetes 路径使用 `KubernetesFilesystemSpec` 和 [`infra/k8s/agent-sandbox.yaml.template`](../infra/k8s/agent-sandbox.yaml.template)；生产启动守卫只接受 Kubernetes。`local` 模式仅用于受控开发，不提供同等级别的隔离。

模型密钥留在 API 控制面。[`AgentModelGateway`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentModelGateway.java) 以短期令牌提供仅回环可访问的 Chat Completions 代理，再按 [`LlmEndpointPolicy`](../apps/api-java/src/main/java/com/gameweare/api/create/LlmEndpointPolicy.java) 检查模型出口。沙箱不会直接拿到真实 API Key。AgentScope 引擎没有本地 Token 或工具迭代次数上限；模型服务商的额度、任务超时和资源限制仍然生效。

## 游戏产物的硬门槛

游戏 Agent 必须写 `index.html`，调用 [`validate_game_html`](../apps/api-java/src/main/java/com/gameweare/api/create/GameValidationTool.java) 检查当前文件，修正逐条诊断，再调用 `deliver_artifact`。校验工具保存通过时的 SHA-256；交付回调再次比较文件字节，防止“校验后修改”。[`ArtifactValidator`](../apps/api-java/src/main/java/com/gameweare/api/create/ArtifactValidator.java) 只检查 HTML 包装、自包含资源和 JavaScript 语法，不执行游戏，也不能证明可玩性。Worker 在入库前会再次校验。

新游戏的封面在游戏 HTML 验证后由独立的 [`CoverReActEngine`](../apps/api-java/src/main/java/com/gameweare/api/create/CoverReActEngine.java) 生成：把已验证的完整源码和原始需求传给封面 Agent，要求写 `cover.svg`、调用 [`validate_cover_svg`](../apps/api-java/src/main/java/com/gameweare/api/create/CoverValidationTool.java)，并交付相同版本的文件。SVG 不合格或阶段失败时记录原因并使用本地安全回退封面。优化旧游戏时不重新生成封面，沿用原封面。

模型逐调用用量记录在 `agent_model_calls`，任务汇总在 `model_usage_events`；响应丢失时状态可能变成 `unknown`，不能把它当成零成本。[`AgentUsageReconciliation`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentUsageReconciliation.java) 只标出待核对调用，不会凭猜测补写服务商账单。

## 验收边界与后续

本地 Mock 模型与 Docker 沙箱由 [`start-local-agentscope.ps1`](../scripts/start-local-agentscope.ps1)、[`e2e-verify.ps1`](../scripts/e2e-verify.ps1) 验证。真实 DeepSeek 工具调用、图片输入、跨实例恢复、真实 Kubernetes controller/RuntimeClass/NetworkPolicy、沙箱逃逸与提供方费用对账仍需分别验证。上线顺序见 [迭代路线](iteration-roadmap.md)；官方框架接口以 [AgentScope Java v2 文档](https://java.agentscope.io/v2/zh/docs) 为准。
