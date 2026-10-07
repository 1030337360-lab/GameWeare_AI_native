# Java 后端：实现与一致性

本文以 [`apps/api-java`](../apps/api-java) 的当前代码为准。后端使用 Java 17、Spring Boot 4、MyBatis、Spring JDBC、Flyway、MySQL、Redis、RabbitMQ 和 MinIO；它是按业务包组织的单体应用。入口是 [`GameWeareApplication`](../apps/api-java/src/main/java/com/gameweare/api/GameWeareApplication.java)，配置入口是 [`application.yml`](../apps/api-java/src/main/resources/application.yml)。

## 分层与 SQL 位置

目前逐业务域迁移到 Controller → Service → DAO/Mapper → MySQL。MyBatis Spring Boot Starter 4.0.0 自动扫描标有 `@Mapper` 的接口；SQL 放在 Mapper 方法的 `@Select`/`@Insert`/`@Update` 注解旁，代码阅读时直接可见。评论域可作为完整范例：[Controller](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameCommentController.java)、[Service](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameCommentService.java)、[Mapper](../apps/api-java/src/main/java/com/gameweare/api/catalog/dao/GameCommentMapper.java)、[Entity](../apps/api-java/src/main/java/com/gameweare/api/catalog/entity/GameCommentEntity.java) 分开存放。认证、历史 Token 账本、游戏目录与社区、游戏游玩、生成券与秒杀、签到、个人资料、上传、Outbox、内置游戏初始化和外部产物入库均已有业务域 Mapper；例如 [AuthMapper](../apps/api-java/src/main/java/com/gameweare/api/auth/dao/AuthMapper.java)、[CatalogMapper](../apps/api-java/src/main/java/com/gameweare/api/catalog/dao/CatalogMapper.java)、[VoucherCampaignMapper](../apps/api-java/src/main/java/com/gameweare/api/voucher/dao/VoucherCampaignMapper.java) 和 [ArtifactMapper](../apps/api-java/src/main/java/com/gameweare/api/create/dao/ArtifactMapper.java)。

迁移是渐进的：任务创建/Worker 编排、Agent 用量审计和管理后台仍有 `JdbcTemplate` 调用，不能把整个项目称为“已全面改用 MyBatis”。这些 SQL 依然执行在同一 MySQL 数据源和 Spring 事务管理器中。复杂动态 SQL 可用 MyBatis XML 或 `<script>`，不把表名等 SQL 标识符直接交给客户端。以计费为例，`TokenAccountMapper.lockAccount` 保留原来的 `SELECT ... FOR UPDATE`，Service 的 `@Transactional` 覆盖查询、余额更新及流水插入。MyBatis 的 Map 查询可能把 MySQL 时间列返回为 `LocalDateTime`，认证映射按 UTC 显式处理这个类型。

Docker 的 [后端 Dockerfile](../apps/api-java/Dockerfile) 在 Maven 构建阶段复制 `pom.xml` 与 `src`，将 MyBatis Starter 和 Mapper 类一同打入 Spring Boot JAR，再由 Java 17 运行镜像启动。开发、双实例和生产 Compose 都引用同一后端构建产物或镜像，不需要为 MyBatis 单独部署服务；它继续使用 Spring 配置的 MySQL 连接池。更新后端时重建 `api` 镜像并重建 API 容器，保留原有中间件容器与具名数据卷；详情见 [本地启动](../README.md#本地启动)。

## 认证、会话与权限

[`AuthService`](../apps/api-java/src/main/java/com/gameweare/api/auth/AuthService.java) 使用 BCrypt 保存密码哈希，签发随机不透明 Token；MySQL `user_sessions` 只保存 Token 的 SHA-256 摘要。Redis Lua 限制同邮箱的登录尝试，并保存短期会话缓存及退出撤销标记。会话有活跃续期和绝对有效期；请求通过 [`AuthFilter`](../apps/api-java/src/main/java/com/gameweare/api/auth/AuthFilter.java) 取得用户身份，数据操作还需按 `user_id` 校验归属。管理员接口由 [`SecurityConfig`](../apps/api-java/src/main/java/com/gameweare/api/auth/SecurityConfig.java) 和 [`MaintenanceController`](../apps/api-java/src/main/java/com/gameweare/api/maintenance/MaintenanceController.java) 限制角色。

登录响应中的 Token 由前端保存并作为 `Authorization: Bearer ...` 发送；它**不是 JWT**。Google OAuth 另由 [`GoogleOAuthService`](../apps/api-java/src/main/java/com/gameweare/api/auth/GoogleOAuthService.java) 处理，需要真实凭证和回调地址才能验收。

## 任务、消息和版本一致性

Chat 访谈先走 [`CreationChatService`](../apps/api-java/src/main/java/com/gameweare/api/create/CreationChatService.java)，V14 增加会话与消息表，数据库访问由 `CreationChatMapper` 承担。回复认领采用 revision CAS 与独立五分钟 token 租约；模型调用在事务外，完成时只允许当前租约提交，两条消息和画像一起提交。重试按 requestId 幂等，失败释放认领，过期请求不能覆盖新回复。全部会话操作按 `user_id` 限定；技能读取只接受资源仓库注册 ID，文本以 React 转义输出。

用户确认时锁会话行并核对 revision，构造 ReAct `JobRequest` 后调用 `CreateService.create`，会话确认、生成任务、占券及 Outbox 同事务提交。重复确认返回原 job ID，不重复扣券或投递。Chat 讨论期间只校验 BYOK 配置或官方券资格，不预留券；消息表记录成功返回的对话用量，不代表异常请求零费用。会话/限流/技能目录及模型兼容性边界见 [Agent 文档](agent.md)。

[`CreateService.create`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 校验模式、项目归属、上传资产与付款方式，在一个事务中写 `create_jobs` 和 `outbox_events`。代码中的核心写入是：

```sql
INSERT INTO create_jobs (..., status, ..., engine, funding_mode, voucher_id, ...)
VALUES (..., 'pending', ..., ?, ?, ?, ...);
INSERT INTO outbox_events (..., event_type, ..., status, ...)
VALUES (..., 'job.created', ..., 'pending', ...);
```

[`OutboxPublisher`](../apps/api-java/src/main/java/com/gameweare/api/config/OutboxPublisher.java) 认领待投递事件，经 RabbitMQ publisher confirm/return 确认后标为 `sent`；超时和投递失败会回到 `pending`。[`CreateWorker`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateWorker.java) 先获取任务级 Redisson 锁（不指定固定租期，由 30 秒看门狗自动续期），再用 MySQL 租约和 `lease_token` 条件更新防止多实例重复提交。消息允许重复投递，因此幂等键、锁、租约、状态条件和唯一约束共同承担去重。`X-Idempotency-Key` 同用户同请求可返回已有任务，不同请求复用会冲突。

Worker 校验游戏文件后上传 MinIO，再在 MySQL 事务中建立 `game_versions`、`assets`、用量和任务终态。优化任务会生成新草稿；`POST /create/jobs/{id}/publish` 才把公开版本切过去。MinIO 与 MySQL 不共享事务，数据库提交失败可能留下孤儿对象，仍需要周期清理。用户删除任务通过 [`V12`](../apps/api-java/src/main/resources/db/migration/V12__hide_deleted_creation_tasks.sql) 的 `deleted_at` 隐藏记录和轨迹；已发布游戏及审计账本保留。

本人终止创建时，[`CreateService.cancelJob`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 在事务中把待处理/生成/待确认任务改为 `canceled`、清除租约并返还预留；完成事务后通知本实例 Worker。跨实例 Worker 在租约续期时发现状态变化后中断本地线程。旧引擎在模型 HTTP 调用期间还会取消 OkHttp Call。Worker 提交游戏版本前再次核对租约；取消或提交失败的本次 MinIO 文件会清理，避免发布半成品。提供方已处理的请求可能仍产生费用，不能把本地取消等同于提供方零用量。

## 模型额度与生成券

新任务的 `fundingMode` 为 `byok` 或 `voucher`。BYOK 使用用户加密保存的配置；官方券使用服务端 `OFFICIAL_LLM_*` 配置。[`GenerationVoucherService`](../apps/api-java/src/main/java/com/gameweare/api/voucher/GenerationVoucherService.java) 在任务创建事务中条件占券，生成可玩版本后核销，失败/拒绝时返还。**新生成任务不按旧本地 Token 余额拒绝**；模型服务商 API 决定其额度，项目记录服务商响应中的用量。[`TokenBillingService`](../apps/api-java/src/main/java/com/gameweare/api/billing/TokenBillingService.java) 和旧账本仍用于历史数据与对账，不能把旧预留方案当成新任务流程。[`AgentUsageReconciliation`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentUsageReconciliation.java) 将超时未结束的模型调用标为 `unknown`，提供方账单仍需外部对账。

## 秒杀、签到与社区

[`VoucherCampaignService`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherCampaignService.java) 使用 Redis Lua 在同一脚本内检查活动时间、用户预留和库存，扣减预库存并写 Stream；预扣返回 `pending`，不代表已发券。[`VoucherClaimQueue`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherClaimQueue.java) 中继与消费 RabbitMQ 消息，MySQL 中条件扣库存、同场唯一约束和券发放决定最终结果；失败通过重试与对账补偿预留。Redis 不可用时停止新抢券，不能依据缓存值宣布到账。

[`CheckinController`](../apps/api-java/src/main/java/com/gameweare/api/voucher/CheckinController.java) 的每日唯一记录和奖励流水在 MySQL，Bitmap 只用于日历。关注关系由 MySQL 唯一约束决定；[`GameCatalogCache`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameCatalogCache.java) 使用 Cache Aside：Caffeine 作为容量 1 万、3 秒过期的 L1，Redis 作为随机 60–120 秒过期的 L2，另有 10 秒空值缓存和 Redisson 看门狗重建锁。写操作提交后删除 L2 并通过 Redis Topic 通知其他实例失效 L1；消息丢失时 L1 最多保留 3 秒。公开状态仍由 MySQL 判定。[`GameSlugBloomFilter`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameSlugBloomFilter.java) 在启动时扫描已公开 slug，并在新游戏发布前写入 Redis 布隆过滤器；只有初始化完成且 Redis 进程标识与初始化时一致的过滤器才拦截确定不存在的 slug；Redis 重启或故障时回退 MySQL，定时重扫公开游戏再启用。布隆过滤器可能误报存在，不负责权限或计费。[`GameTrendingService`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameTrendingService.java) 和 [`PlayUvService`](../apps/api-java/src/main/java/com/gameweare/api/play/PlayUvService.java) 使用 Redis 展示投影，UV 为近似统计。

[`GameCatalogController`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameCatalogController.java) 的 `sort=likes` 用 MySQL 点赞计数排序，点赞唯一键与计数在同一事务更新。[`GameCommentController`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameCommentController.java) 对公开游戏提供分页评论，内容和作者归属存 MySQL；发表、软删除与 `comments_count` 同事务，缓存于提交后失效。结构与索引见 [`V13`](../apps/api-java/src/main/resources/db/migration/V13__game_comments_and_like_order.sql)。

## 产物校验与安全边界

[`LlmClient`](../apps/api-java/src/main/java/com/gameweare/api/create/LlmClient.java) 对兼容 Responses API 的模型启用 SSE 流式输出，等待 `response.completed` 取得完整文本和用量；明确处理失败与未完成事件，避免长时间无响应的非流式请求被网关重置。
游戏校验工具的多轮请求由客户端显式回传原始模型输出项及工具结果，不依赖服务端保存响应；DeepSeek 官方无状态 Responses 接口和火山方舟的兼容接口共用此路径。AgentScope 的 Chat 网关仅针对 DeepSeek 模型移除非标准 `thinkmode` / `thinking_mode` 字段，并为 V4.1 Flash 移除不支持的惩罚参数；标准 `thinking` 和 `reasoning_content` 保留。
函数调用携带完整游戏 HTML 时，SSE 增量帧的累计传输量可能远大于最终文件；客户端按累计 128 MiB 设置流量保护，产物本身仍受 2 MB 校验上限约束。

[`ArtifactValidator`](../apps/api-java/src/main/java/com/gameweare/api/create/ArtifactValidator.java) 从模型回复中提取完整 HTML 文档，去除前后说明文字；再用 Jsoup 检查单文件 HTML 结构和外部资源，用 GraalVM `Context.parse` 检查内联 JavaScript 语法，**不会执行游戏脚本**。外部 Agent 可以先调用 `/create/artifacts/validate` 获得逐项诊断，再经 [`ArtifactService`](../apps/api-java/src/main/java/com/gameweare/api/create/ArtifactService.java) 提交待审草稿。试玩 HTML 经 [`PlayController`](../apps/api-java/src/main/java/com/gameweare/api/play/PlayController.java) 返回 CSP，并在前端 sandbox iframe 中运行。
对外部 HTTP URL 的诊断会指出所在行和 URL，供 Agent 修改并重新调用工具；入库前仍执行同一校验，不接受未经验证的模型正文。

[`ProductionConfigGuard`](../apps/api-java/src/main/java/com/gameweare/api/config/ProductionConfigGuard.java) 在 `prod` 启动时拒绝默认密钥、非 HTTPS 公网地址、私网模型入口和非 Kubernetes 文件系统。[`LlmEndpointPolicy`](../apps/api-java/src/main/java/com/gameweare/api/create/LlmEndpointPolicy.java) 限定模型主机、DNS 解析和连接地址；真实部署仍需要防火墙或出口代理作为网络层约束。生产密钥应由独立密钥系统提供，`AI_CONFIG_SECRET` 变更会使既有加密的用户密钥无法直接读取。MySQL 与 MinIO 应联合备份并演练恢复。

## 验证入口与未完成项

[`CI`](../.github/workflows/ci.yml) 执行 Maven 测试、前端构建、Compose 冒烟、双实例和秒杀故障注入；对应脚本在 [`scripts`](../scripts)。当前仍需真实模型工具调用、真实 Google OAuth、目标 Kubernetes 沙箱、持续负载、故障恢复和备份恢复演练。性能数字应取自新的压测报告，不沿用历史本机短时测试结果。

## 本机并发压测与简历指标

使用独立的 [`infra/benchmark/compose.yml`](../infra/benchmark/compose.yml) 启动两份 API 以及一次性 MySQL、Redis、RabbitMQ、MinIO 和模拟模型服务；它不挂载常规环境的命名卷。[`scripts/benchmark.mjs`](../scripts/benchmark.mjs) 只向这两份 API 轮流发送请求，以固定并发、闭环请求方式记录吞吐与延迟，并在压测后通过 MySQL 核对发券数量和用户唯一数。执行方式：

```powershell
docker compose -f infra/benchmark/compose.yml up --build -d
$env:BENCH_DURATION_MS = '10000'
$env:BENCH_OUTPUT = 'C:\temp\gameweare-benchmark.json'
node scripts/benchmark.mjs
docker compose -f infra/benchmark/compose.yml down
```

2026-09-29 本机样本：Docker Desktop 分配 **6 CPU / 1.86 GiB 内存**，两份 API，读取场景每档持续约 10 秒。热点游戏详情在 64 并发下完成 **10,737** 次请求，**1,072.54 req/s**、P95 **189.60 ms**，HTTP 非 2xx 为 0；登录态读取在 64 并发下完成 **28,262** 次请求，**2,820.59 req/s**、P95 **69.52 ms**，HTTP 非 2xx 为 0。100 个用户对库存 20 的活动发起 120 次并发请求（包含同用户重复请求），HTTP 202 有 40 次，其中重复请求复用原预留；HTTP 409 有 80 次，均为预期的库存/重复限制。最终 **20 张券发给 20 个不同用户**、MySQL 库存余 0、Redis 预留余 0，未出现超发。12 次并发任务提交全部接收并最终完成，提交 P95 **400.03 ms**；使用模拟模型，因此不代表真实 AI 生成吞吐。

这些是一次本机短时样本，未经过独立负载机、长时间稳态、故障注入或真实模型服务验证。秒杀的 120 次请求在 0.63 秒完成，属于突发处理时间，不能写成持续 191.81 req/s 的系统容量。热点详情在本次测试前发现内置游戏先于布隆过滤器完成发布时可能误判 404；[`BuiltInGameSeeder`](../apps/api-java/src/main/java/com/gameweare/api/catalog/BuiltInGameSeeder.java) 现于公开发布前登记 slug，并在启动时修复已存在的内置游戏。后续做简历量化应至少增加多轮重复、长时间稳态和目标部署环境测试，再使用其保守统计值。

### JMeter 秒杀链路阶梯测试

当前生成券业务没有“申请资格 Token → 携 Token 下单”的接口，也没有秒杀订单或分片订单库。真实链路是认证 → `POST /voucher-campaigns/{id}/claim` → MySQL 活动读取 → Redis Lua 预留及 Stream → RabbitMQ → MySQL 条件扣库存和发券；该券链路不使用任务 Outbox。JMeter 计划 [`infra/benchmark/seckill.jmx`](../infra/benchmark/seckill.jmx) 以 CSV 为每次请求分配一个独立账号 Token、轮流直连两份 API；[`scripts/benchmark.mjs`](../scripts/benchmark.mjs) 的 `BENCH_PREPARE_DIR` 模式生成一次性用户、活动和 CSV，[`scripts/benchmark-jmeter-report.mjs`](../scripts/benchmark-jmeter-report.mjs) 汇总原始 JTL。JMeter 使用官方 CLI 模式 `-n -t ... -Jcsv=... -Jcampaign=... -Jthreads=... -Jloops=... -Jramp=... -l ...`；活动库存等于该档用户数。负载机是 Windows 主机，服务端仍是 Docker Desktop 6 CPU / 1.86 GiB，两者共用一台物理机器。

| 场景 | 独立请求/用户 | JMeter 线程×循环，ramp-up | 入口结果 | P95 | 入口吞吐 | 最终业务核对 |
| --- | ---: | --- | --- | ---: | ---: | --- |
| 无效 Bearer 直打 | 1000 次 | 200×5，2 秒 | 403×1000 | 44 ms | 523.29 req/s | 活动库存 2000、发券 0 |
| 合法抢券 | 1000 人 | 200×5，10 秒 | 202×1000 | 154 ms | 101.04 req/s | 1000/1000 发券，入口结束约 4.6 秒后收敛 |
| 合法抢券 | 2000 人 | 200×10，2 秒 | 202×2000 | 438 ms | 713.52 req/s | 2000/2000 发券；结束 38 秒时仍差 55 张，之后收敛 |
| 合法抢券 | 5000 人 | 250×20，5 秒 | 202×5000 | 1368 ms | 469.62 req/s | 5000/5000 发券、库存 0；入口结束约 60.7 秒后收敛 |
| 合法抢券，未完成 | 10000 人目标 | 500×20，5 秒 | 已采集 5699 次：202×2399，SocketTimeout×3300 | 已采集部分约 20 秒 | 无效 | Docker Engine 同时返回 500，环境失稳；重启后 MySQL 有 1670 张券、剩余 8330 库存，无法完成该档端到端验收 |

该表的“用户档”指一次活动内的不同账号请求数，线程数和循环数另列；不同 ramp-up 会影响吞吐，不能仅凭表中 req/s 比较容量。202 只证明 Lua 预留被接受，不能算发券成功。5000 档入口结束约 2.6 秒后，MySQL 仅发券 177 张，Redis Stream 仍有 3877 条；RabbitMQ 主队列随后观察到约 2869 条待消费。Stream 约 23 秒清空时 MySQL 只发券 1735 张，说明后段消费者仍有积压；最终 60.7 秒收敛，死信与重试队列清空。RabbitMQ 容器曾占约 1 核 CPU，但现有监控缺少中继、发布确认、消费和 MySQL 事务的独立计时，不能把单一组件断言为唯一根因。若用户体验要求“10 秒内到账”，5000 档显然不达标；在完成更长稳态和独立负载机测试前，不宣称系统上限是 5000 或 10000 用户。

首次 100 人试跑还发现压测脚本把活动 UTC 时间误按本地时间解释，导致合法请求提前发出、全部得到 409；修正时间换算后重跑得到 100 次 202，该试跑不计入表中。所有活动均在一次性数据库内，未对真实用户发券。

10000 档的 JMeter 原始文件为**中止时的部分样本**。Docker 重启后，MySQL 库存与已发券数仍满足 8330+1670=10000，且 1670 张券属于 1670 个用户；但 JMeter 至少记录了 2399 次 202，RabbitMQ 仍有 2840 条待消费，而 Redis Stream 与键空间均为空。本次运行时的隔离压测配置关闭了 Redis RDB/AOF，重启后预留状态丢失；消费端需要该状态才能落库，因此不能把这些 202 视作最终成功。常规 Compose 的 Redis 已开启 AOF；压测 Compose 也在本次实验后改为开启 AOF，**表中的数字仍属于修改前的配置**，后续必须重新建立基线。Docker Desktop 还曾被旧 `dockerInference` socket 阻止重启，需把本机负载机/容器资源故障与应用瓶颈分开。压测数据文件和 JMeter HTML 仪表盘保存在本机 `.codex/outputs/gameweare-jmeter/`，没有放入项目仓库。下一轮应给 Docker 更多内存、把负载机与被测服务分开，增加入口/Stream/队列/消费者/数据库分段指标，再在相同 ramp-up 和 SLA 下重复多轮测量。当前 `/actuator/prometheus` 对匿名请求返回 403，需要有权限的采集配置；不能把未采集到的 Prometheus 指标写成实验依据。

### 12 CPU / 8 GiB / 4 GiB Swap 复测

2026-09-29 将 WSL 配置应用到 Docker Desktop 后，`docker info` 实际报告 **12 CPU / 8,326,950,912 字节内存**（容器中约 7.8 GiB），`free -h` 报告 **4.0 GiB Swap**。本轮使用相同的两份 API、同一 JMeter 计划和各档线程/循环/ramp-up，Redis AOF 已开启。Windows JMeter 仍与 Docker 共用一台物理机器，压测目标为独立的临时数据库和活动。

| 场景 | 线程×循环，ramp-up | 入口结果 | P95 / P99 | 入口吞吐 | 最终 MySQL 核对 |
| --- | --- | --- | --- | ---: | --- |
| 无效 Bearer 直打 1000 次 | 200×5，2 秒 | 403×1000 | 12 / 54 ms | 530.22 req/s | 无发券 |
| 合法 1000 人 | 200×5，10 秒 | 202×1000 | 7 / 8 ms | 101.21 req/s | 发券 1000、独立用户 1000、库存 0 |
| 合法 2000 人 | 200×10，2 秒 | 202×2000 | 7 / 9 ms | 1024.07 req/s | 发券 2000、独立用户 2000、库存 0 |
| 合法 5000 人 | 250×20，5 秒 | 202×5000 | 6 / 8 ms | 1006.24 req/s | 发券 5000、独立用户 5000、库存 0；入口结束约 27 秒后收敛 |
| 合法 10000 人，单独复测 | 500×20，5 秒 | 202×10000 | 8 / 10 ms | 2025.11 req/s | 发券 10000、独立用户 10000、库存 0；入口结束约 51 秒后收敛 |

首次连续执行 10000 档时，JMeter 收到 8636 个 202 和 1364 个 `java.net.BindException: Address already in use: getsockopt`；Windows 当时约有 15,700 个 `TIME_WAIT` 连接，接近默认 16,384 个动态 TCP 端口。该次 MySQL 最终发券 8636、库存余 1364，说明已进入后端的请求没有丢券。待 `TIME_WAIT` 降到约 60 后，另建 10000 库存活动单独复测，全部请求成功接收并最终发券；前一次的客户端建连失败不计作后端拒绝率。所有受测活动的券领取数与独立用户数相等，RabbitMQ 主队列、重试队列和死信队列最终均为空。

这些是单次本机突发样本：202 是预扣接受，P95 仅是入口 HTTP 延迟，不含异步到账的约 27/51 秒。当前证据表明该配置通过了 **10000 用户、5 秒 ramp-up** 的一次验收，不能据此宣称稳定吞吐上限为 2025 req/s 或生产环境容量。与前一轮相比，Docker 资源和 Redis 持久化设置都变化了，不能把差异归因于单一参数；仍需独立负载机、多轮重复、长时间稳态以及阶段性指标和故障注入，才能形成更可靠的简历指标。原始 JTL、汇总 JSON 和 10000 档 HTML 仪表盘存放于本机 `.codex/outputs/gameweare-jmeter/rerun-12cpu8g-2026-09-29/`。

### 20000 / 50000 用户扩展档

同日继续用 12 CPU / 8 GiB / 4 GiB Swap 的隔离环境测试。由于 Windows 默认只有 16384 个动态 TCP 端口，改为两个一次性 Linux JMeter 容器在 Compose 网络内分别直连 `api-a:8080` 和 `api-b:8080`；每个容器持有独立的网络命名空间和账号 CSV，合并两份 JTL 计算整档指标。JMeter 和被测服务仍共用 Docker 的 12 CPU / 8 GiB，**因此此表不能与上一表的 Windows 主机负载机结果直接比较**。Redis AOF 已开启；活动开始前建立 50000 个一次性账号，不把 BCrypt 注册耗时计入抢券结果。

| 场景 | 负载配置 | 入口结果 | 入口 P95 / P99 | 入口吞吐 | 最终一致性 |
| --- | --- | --- | --- | ---: | --- |
| 20000 独立用户 | 2×(250 线程×40 循环)，5 秒 ramp-up | 202×20000，其他错误 0 | 76 / 105 ms | 3633.06 req/s，持续 5.50 秒 | 发券 20000、独立用户 20000、库存 0；入口结束约 89 秒后全部落库 |
| 50000 独立用户 | 2×(250 线程×100 循环)，5 秒 ramp-up | 202×50000，其他错误 0 | 134 / 182 ms | 3196.52 req/s，持续 15.64 秒 | 发券 50000、独立用户 50000、库存 0；入口结束约 264 秒后全部落库 |

50000 档入口后，MySQL 逐步从 4884 张增长到 50000 张，RabbitMQ 主队列一度至少有 3244 条待消费；最终主队列、重试队列、死信队列和 Redis Stream 均为空。两档都没有超发或同用户重复领券；日志中未查到本轮错误。入口流量约 3200–3600 req/s，但后续到账要等待 89/264 秒，故不能把入口吞吐当成完整业务吞吐或系统极限。代码在每张券发放时会锁定同一活动的 MySQL 库存行，这与异步阶段收敛较慢相符；尚无事务、发布确认和消费者的分段耗时数据，不能断言它是唯一瓶颈。

本实验的 Redis 使用 AOF，RabbitMQ 使用 durable 队列并等待发布确认；MySQL、Redis、RabbitMQ 的压测数据位于临时匿名卷中，普通容器重启可保留，但 `docker compose down -v` 会删除。实验**没有**注入重启或故障来验证恢复。消费端当前使用 Spring AMQP 默认的 `AUTO` 监听确认，方法成功返回后由框架发送 ACK，未使用应用代码 `basicAck` 的 `MANUAL` 模式。要验收手动 ACK，需先改代码，然后分别注入事务提交前失败和提交后、ACK 前宕机，核对重投与幂等。

JMeter 的计时请求只有抢券接口；50000 档 JTL 中响应 `bytes` 为 560–564 字节，平均 563.8 字节，请求平均 `sentBytes` 约 326 字节。登录、游戏详情和大列表查询的响应体积与处理路径不同，不能沿用此 P95；需要按接口及响应大小分别测试。原始 JTL、汇总和 HTML 仪表盘位于本机 `.codex/outputs/gameweare-jmeter/large-20k-50k-2026-09-29/`。

### 持久化、手动 ACK 与混合业务链路复测

上面各表是对应配置下的历史实验，不能与本节混为同一基线。新实验使用 [`infra/benchmark/compose.yml`](../infra/benchmark/compose.yml) 的隔离命名卷：MySQL、Redis、RabbitMQ、MinIO 数据在容器重启和不带 `-v` 的 `compose down` 后保留。MySQL 设置 `innodb_flush_log_at_trx_commit=1`；Redis 同时启用 AOF `appendfsync everysec` 和 RDB 快照；RabbitMQ 发券主队列、延迟重试队列和死信队列均为 durable，发布消息设置 persistent 并等待 publisher confirm。消费者用 `@RabbitListener(ackMode = "MANUAL")`，事务提交或重试/死信投递确认后才 `basicAck`；基础设施异常时 `basicNack(requeue=true)`。配置和代码分别在 [`VoucherClaimQueue`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherClaimQueue.java) 与 [`VoucherQueueConfig`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherQueueConfig.java)。

[`infra/benchmark/realistic.jmx`](../infra/benchmark/realistic.jmx) 为每个独立账号执行游戏详情、活动列表、抢券、我的领取状态，另有 20% 的账号读取约 39 KiB 的真实内置游戏文档。它覆盖 541–39809 字节的响应，而非只请求 560 字节的抢券结果。两份 Linux JMeter 容器分别访问两份 API，用户档与实际并发线程分开记录。每档活动库存与用户数一致；1000/2000/5000/10000 档的每份负载机分别使用 50×10/100×10/125×20/250×20 线程与循环，ramp-up 分别为 10/2/5/5 秒。JTL 经 [`benchmark-jmeter-report.mjs`](../scripts/benchmark-jmeter-report.mjs) 汇总各接口 P95/P99 与响应体积；[`VoucherStageMetrics`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherStageMetrics.java) 通过 Prometheus histogram 记录认证、MySQL 活动读取、Redis Lua、Stream 中继、RabbitMQ 发布确认、消费事务、手动 ACK 和预留至到账时间，再由 [`benchmark-stage-report.mjs`](../scripts/benchmark-stage-report.mjs) 对两实例的前后快照求差、按桶插值估算 P95/P99。阶段 P95/P99 是桶插值估算值，精度低于 JTL 原始样本。

| 独立用户 | HTTP 请求数 / 历时 | 全部 HTTP P95 / P99 | 抢券入口 P95 / P99 | 预留至到账 P95 / P99 | MySQL 最终核对 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1000 | 4200 / 9.70 秒 | 10 / 18 ms | 9 / 13 ms | 1.03 / 1.07 秒 | 1000 张券、1000 用户、库存 0 |
| 2000 | 8400 / 3.12 秒 | 92 / 115 ms | 76 / 94 ms | 9.80 / 10.80 秒 | 2000 张券、2000 用户、库存 0 |
| 5000 | 21000 / 5.21 秒 | 41 / 55 ms | 37 / 50 ms | 23.31 / 27.57 秒 | 5000 张券、5000 用户、库存 0 |
| 10000 | 42000 / 7.67 秒 | 115 / 170 ms | 97 / 126 ms | 51.03 / 55.83 秒 | 10000 张券、10000 用户、库存 0 |

四档 HTTP 均为预期 200/202，重试、死信、主队列和 Redis Stream 最终无积压。主要组件耗时如下，单元格是 P95/P99，单位 ms；完整阶段结果还包括 Stream 读取与删除、MySQL 行锁和 Redis 预留核对。

| 用户 | Token 查询 | 活动 MySQL 读取 | Redis Lua | RabbitMQ 发布确认 | MySQL 发券事务 | 手动 ACK |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 3.20/6.99 | 0.85/1.92 | 2.18/4.19 | 1.90/4.13 | 12.67/18.41 | 0.14/0.27 |
| 2000 | 52.40/70.54 | 9.04/24.47 | 28.82/44.45 | 1.88/5.83 | 12.48/46.13 | 0.10/0.15 |
| 5000 | 17.67/26.69 | 4.92/8.48 | 13.38/24.47 | 1.65/3.79 | 12.52/27.61 | 0.10/0.43 |
| 10000 | 62.77/106.74 | 14.33/29.29 | 32.92/52.90 | 1.39/3.00 | 10.20/28.50 | 0.10/0.14 |

**入口成功不等于到账**：异步到账 P95 随活动规模升至 51 秒，不能将 10000 档约 5474 HTTP req/s 说成持续发券吞吐或系统容量上限。不同档使用不同 ramp-up 和线程数，组件耗时也不能仅按用户数解释。

本轮还发现两份实例的 Stream 中继都从 `0-0` 读取且没有消费者组，同一预留在删除前可被两实例重复发布。各档有效预留为 1000/2000/5000/10000，但消费事务计数达到 1794/2615/6439/16760。MySQL 唯一约束与幂等逻辑避免重复发券，但多余消息扩大队列及数据库负载；下一步应改为消费者组认领、处理 pending 与围栏，重新测异步收敛时间。该发现是当前容量判断的重要限制。

隔离环境的重启验证：Redis 写入探针后重启仍可读取；RabbitMQ 将 `delivery_mode=2` 的探针消息放入 durable 队列，重启后仍可消费；随后删除探针。四档发券数据也在 MySQL 中保留。这个验证只覆盖正常容器重启，不等于主机掉电、磁盘故障或多节点高可用；Redis `everysec` 仍有约一秒的数据丢失窗口。两份负载机与被测服务共用 Docker Desktop 的 12 CPU / 8 GiB / 4 GiB Swap，且只进行了一轮短时阶梯突发测试。完整 JTL、阶段快照及汇总位于本机 `.codex/outputs/gameweare-jmeter/durable-manual-realistic-2026-09-29/`；不含真实账号，使用一次性测试账号与隔离活动。

复现时先运行 `docker compose -f infra/benchmark/compose.yml up --build -d`，设置 `BENCH_PREPARE_DIR` 为仓库外的输出目录、`BENCH_USERS=10000`、`BENCH_TIER_STOCKS=1000,2000,5000,10000` 后执行 `node scripts/benchmark.mjs`，等待 `campaigns.json` 中的开始时间。每档各启动一份 JMeter CLI，以 `realistic-<人数>-api-a.csv`/`api-b.csv` 分别访问 `api-a`/`api-b`，并传入活动 ID、线程、循环和 ramp-up。待该档 MySQL 发券数达到库存且主队列与 Stream 清空，再采下一档前的 Prometheus 快照。JMeter 的 `-l` 原始 JTL 保存在输出目录，两份 JTL 合并时仅保留一份 CSV 表头，使用上述两份报告脚本汇总。测试结束只执行 `docker compose -f infra/benchmark/compose.yml down`，保留隔离命名卷以供对账；不要对压测卷运行 `down -v`。
