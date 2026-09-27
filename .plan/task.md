# GameWeare Java 后端建设计划与复核

本计划对应当前 GameWeare 仓库；参考仓库仍是 `charlie11sun-netizen/yahaha`，两者不是同一个项目。`features.json` 中的 `passes=true` 只表示已有实现与相应验证，不能等同于生产可用。

## 已建设范围

| # | 模块 | 当前实现与证据 | 仍需验证或补充 |
| --- | --- | --- | --- |
| 1 | Python 归档 | 原后端置于 `archive/python-api` | 保留归档作为行为对照，不纳入新运行栈 |
| 2 | Spring Boot | Java 17、Spring Boot 4、模块化单体；Maven 测试与容器构建成功 | 生产配置基线 |
| 3 | MySQL | Flyway V1–V8，覆盖核心业务、审核、工作流、OAuth、外部产物摘要、AgentScope 引擎、逐调用用量与项目记忆 | 备份恢复与迁移回滚演练 |
| 4 | 登录 | BCrypt、MySQL 会话摘要、Redis 限流/缓存/撤销；双实例会话与撤销验证通过 | 真实 Google 回调、持续压测 |
| 5 | Token 计费 | 历史本地账本保留行锁、预留/结算/退款与对账；新建生成任务不预留或扣除本地 Token，记录模型 API 返回的实际用量，额度错误由模型服务商 API 决定 | 明确外部账单对账与异常用量告警 |
| 6 | 目录/上传/试玩 | MySQL + MinIO 实现；生成的 SVG 封面入库并在目录、个人页和任务结果展示，旧游戏显示安全回退封面；Mock LLM 端到端覆盖发布和试玩 | 真实图片输入与浏览器端到端测试 |
| 7 | 异步创建 | MySQL Outbox、RabbitMQ、Worker 租约；Mock LLM 端到端覆盖 chat、react、plan、decentralized、refine 及封面 | 真实服务使用量/超时与 MinIO 孤儿对象清理 |
| 8 | 维护/高级流程 | 维护与个人接口、plan 审批、decentralized 三选一；react 模式可生成；refine 读取上一版本并建立新草稿，发布时才切换公开版本 | 真实模型下的 ReAct 工具循环、refine 策略能力对齐 |
| 9 | Compose/CI | GitHub Actions 运行 Java 17 测试、前端构建、Flyway/登录/产物烟测及双实例一致性脚本；本地运行通过 | GitHub 托管首跑、容灾恢复 |
| 10 | 前端 | React 页面接入 Java API；当前 `npm run build` 通过 | 登录/创建/试玩的浏览器自动化 |
| 11 | 外部 Agent 产物 | 认证接收单文件 HTML，非执行式 JavaScript 语法校验返回诊断，MinIO 建立草稿版本，不调用模型与计费 | 浏览器运行测试、内容审核及多文件构建支持 |
| 12 | AgentScope Java | Harness 2.0.3、官方子智能体工具、MySQL 分布式状态、Kubernetes/Docker 沙箱、Java 沙箱运行时与模型网关已接入；本机 Docker 模拟模型 21 项端到端通过，浏览器完成 Canvas 试玩和方向键交互；默认 Compose 仍使用 legacy | 真实 Kubernetes controller/RuntimeClass、DeepSeek 工具调用、跨实例恢复、费用失败对账与隔离验收；见 `docs/agentscope-agent-rewrite-plan.md` |

复核开始时本地 `main` 与 GitHub `origin/main` 均指向 `d983d2c`；本轮改动尚未推送。Java 17 全量单测、前端构建、Compose 配置、容器烟测和双实例并发验收通过。CI 工作流尚待 GitHub 托管执行；真实 AI 与 Google OAuth 尚未联调。

## 一致性边界

1. MySQL 是用户、会话、游戏、任务、Token 余额和不可变账本的事务数据源；MinIO 只保存对象。Redis 用于短期会话缓存和登录限流，RabbitMQ 用于异步任务传输。
2. 创建任务和 Outbox 事件在同一 MySQL 事务提交。消息至少一次投递，Worker 以状态和租约去重。新任务不使用本地 Token 余额门槛，逐调用和任务总用量按模型服务商响应记录；旧任务的预留账本继续保留。
3. 同一项目在 `pending/generating/planning/reviewing` 状态只允许一个生成任务。本次复核补齐了等待人工决策状态的互斥检查及回归测试。
4. 游戏版本文件先写入 MinIO，随后数据库发布版本。若数据库提交失败，可能留下未引用对象，需要扫描与清理策略。
5. `LLM_ALLOW_PRIVATE_ENDPOINTS` 仅供本地 Mock 测试。生产配置强制密钥与精确 AI 域名白名单，AI HTTP 客户端连接到已校验的 DNS 地址，禁止重定向与环境代理；宿主级出口防火墙仍需部署。
6. 外部 Agent 接收路径只做自包含资源与 JavaScript 语法检查，不执行代码，也不扣 Token。通过后建立草稿版本；浏览器运行和内容安全是独立验收层。

## 下一阶段优先项

| 优先级 | 项目 | 完成标准 |
| --- | --- | --- |
| P0 | 生产网络硬边界 | 在部署平台配置 AI 出口防火墙或代理；验证容器运行身份、备份密钥与轮换流程 |
| P1 | CI 首跑 | 将当前变更推送后确认 GitHub Actions 绿灯；可再加入双实例脚本与完整 Mock LLM E2E |
| P1 | 故障测试 | Worker 崩溃/重投、Outbox 不可路由、数据库故障转移和 Token 对账告警均有自动化证据 |
| P1 | 外部能力验收 | 真实 AI 提供商、图片输入及 Google OAuth 走完端到端流程，记录 Token 用量与错误恢复 |
| P1 | 运维与可观测性 | readiness 检查 DB/Redis/RabbitMQ/MinIO，暴露任务积压、失败率、Token 对账告警；完成 MySQL/MinIO 备份恢复演练 |
| P2 | 策略与接口演进 | 当前暂停自动生成 Agent 的补齐；后续决定多文件产物构建、API 版本化与旧路径兼容期 |

`docs/java-backend-architecture.md` 是当前 Java 架构说明；`docs/system-design.md` 和 `docs/api.md` 已按现状更新。早期 FastAPI 企业级化报告保留为历史审查材料。
