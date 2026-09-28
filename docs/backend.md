# Java 后端：实现与一致性

本文以 [`apps/api-java`](../apps/api-java) 的当前代码为准。后端使用 Java 17、Spring Boot 4、Spring JDBC、Flyway、MySQL、Redis、RabbitMQ 和 MinIO；它是按业务包组织的单体应用。入口是 [`GameWeareApplication`](../apps/api-java/src/main/java/com/gameweare/api/GameWeareApplication.java)，配置入口是 [`application.yml`](../apps/api-java/src/main/resources/application.yml)。

## 认证、会话与权限

[`AuthService`](../apps/api-java/src/main/java/com/gameweare/api/auth/AuthService.java) 使用 BCrypt 保存密码哈希，签发随机不透明 Token；MySQL `user_sessions` 只保存 Token 的 SHA-256 摘要。Redis Lua 限制同邮箱的登录尝试，并保存短期会话缓存及退出撤销标记。会话有活跃续期和绝对有效期；请求通过 [`AuthFilter`](../apps/api-java/src/main/java/com/gameweare/api/auth/AuthFilter.java) 取得用户身份，数据操作还需按 `user_id` 校验归属。管理员接口由 [`SecurityConfig`](../apps/api-java/src/main/java/com/gameweare/api/auth/SecurityConfig.java) 和 [`MaintenanceController`](../apps/api-java/src/main/java/com/gameweare/api/maintenance/MaintenanceController.java) 限制角色。

登录响应中的 Token 由前端保存并作为 `Authorization: Bearer ...` 发送；它**不是 JWT**。Google OAuth 另由 [`GoogleOAuthService`](../apps/api-java/src/main/java/com/gameweare/api/auth/GoogleOAuthService.java) 处理，需要真实凭证和回调地址才能验收。

## 任务、消息和版本一致性

[`CreateService.create`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateService.java) 校验模式、项目归属、上传资产与付款方式，在一个事务中写 `create_jobs` 和 `outbox_events`。代码中的核心写入是：

```sql
INSERT INTO create_jobs (..., status, ..., engine, funding_mode, voucher_id, ...)
VALUES (..., 'pending', ..., ?, ?, ?, ...);
INSERT INTO outbox_events (..., event_type, ..., status, ...)
VALUES (..., 'job.created', ..., 'pending', ...);
```

[`OutboxPublisher`](../apps/api-java/src/main/java/com/gameweare/api/config/OutboxPublisher.java) 认领待投递事件，经 RabbitMQ publisher confirm/return 确认后标为 `sent`；超时和投递失败会回到 `pending`。[`CreateWorker`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateWorker.java) 用任务租约和 `lease_token` 条件更新防止多实例重复提交。消息允许重复投递，因此幂等键、租约、状态条件和唯一约束共同承担去重。`X-Idempotency-Key` 同用户同请求可返回已有任务，不同请求复用会冲突。

Worker 校验游戏文件后上传 MinIO，再在 MySQL 事务中建立 `game_versions`、`assets`、用量和任务终态。优化任务会生成新草稿；`POST /create/jobs/{id}/publish` 才把公开版本切过去。MinIO 与 MySQL 不共享事务，数据库提交失败可能留下孤儿对象，仍需要周期清理。用户删除任务通过 [`V12`](../apps/api-java/src/main/resources/db/migration/V12__hide_deleted_creation_tasks.sql) 的 `deleted_at` 隐藏记录和轨迹；已发布游戏及审计账本保留。

## 模型额度与生成券

新任务的 `fundingMode` 为 `byok` 或 `voucher`。BYOK 使用用户加密保存的配置；官方券使用服务端 `OFFICIAL_LLM_*` 配置。[`GenerationVoucherService`](../apps/api-java/src/main/java/com/gameweare/api/voucher/GenerationVoucherService.java) 在任务创建事务中条件占券，生成可玩版本后核销，失败/拒绝时返还。**新生成任务不按旧本地 Token 余额拒绝**；模型服务商 API 决定其额度，项目记录服务商响应中的用量。[`TokenBillingService`](../apps/api-java/src/main/java/com/gameweare/api/billing/TokenBillingService.java) 和旧账本仍用于历史数据与对账，不能把旧预留方案当成新任务流程。[`AgentUsageReconciliation`](../apps/api-java/src/main/java/com/gameweare/api/create/AgentUsageReconciliation.java) 将超时未结束的模型调用标为 `unknown`，提供方账单仍需外部对账。

## 秒杀、签到与社区

[`VoucherCampaignService`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherCampaignService.java) 使用 Redis Lua 在同一脚本内检查活动时间、用户预留和库存，扣减预库存并写 Stream；预扣返回 `pending`，不代表已发券。[`VoucherClaimQueue`](../apps/api-java/src/main/java/com/gameweare/api/voucher/VoucherClaimQueue.java) 中继与消费 RabbitMQ 消息，MySQL 中条件扣库存、同场唯一约束和券发放决定最终结果；失败通过重试与对账补偿预留。Redis 不可用时停止新抢券，不能依据缓存值宣布到账。

[`CheckinController`](../apps/api-java/src/main/java/com/gameweare/api/voucher/CheckinController.java) 的每日唯一记录和奖励流水在 MySQL，Bitmap 只用于日历。关注关系由 MySQL 唯一约束决定；[`GameCatalogCache`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameCatalogCache.java) 使用 Cache Aside、随机 TTL、空值缓存和重建锁，公开状态仍由 MySQL 判定。[`GameTrendingService`](../apps/api-java/src/main/java/com/gameweare/api/catalog/GameTrendingService.java) 和 [`PlayUvService`](../apps/api-java/src/main/java/com/gameweare/api/play/PlayUvService.java) 使用 Redis 展示投影，UV 为近似统计。

## 产物校验与安全边界

[`LlmClient`](../apps/api-java/src/main/java/com/gameweare/api/create/LlmClient.java) 对兼容 Responses API 的模型启用 SSE 流式输出，等待 `response.completed` 取得完整文本和用量；明确处理失败与未完成事件，避免长时间无响应的非流式请求被网关重置。
函数调用携带完整游戏 HTML 时，SSE 增量帧的累计传输量可能远大于最终文件；客户端按累计 128 MiB 设置流量保护，产物本身仍受 2 MB 校验上限约束。

[`ArtifactValidator`](../apps/api-java/src/main/java/com/gameweare/api/create/ArtifactValidator.java) 从模型回复中提取完整 HTML 文档，去除前后说明文字；再用 Jsoup 检查单文件 HTML 结构和外部资源，用 GraalVM `Context.parse` 检查内联 JavaScript 语法，**不会执行游戏脚本**。外部 Agent 可以先调用 `/create/artifacts/validate` 获得逐项诊断，再经 [`ArtifactService`](../apps/api-java/src/main/java/com/gameweare/api/create/ArtifactService.java) 提交待审草稿。试玩 HTML 经 [`PlayController`](../apps/api-java/src/main/java/com/gameweare/api/play/PlayController.java) 返回 CSP，并在前端 sandbox iframe 中运行。
对外部 HTTP URL 的诊断会指出所在行和 URL，供 Agent 修改并重新调用工具；入库前仍执行同一校验，不接受未经验证的模型正文。

[`ProductionConfigGuard`](../apps/api-java/src/main/java/com/gameweare/api/config/ProductionConfigGuard.java) 在 `prod` 启动时拒绝默认密钥、非 HTTPS 公网地址、私网模型入口和非 Kubernetes 文件系统。[`LlmEndpointPolicy`](../apps/api-java/src/main/java/com/gameweare/api/create/LlmEndpointPolicy.java) 限定模型主机、DNS 解析和连接地址；真实部署仍需要防火墙或出口代理作为网络层约束。生产密钥应由独立密钥系统提供，`AI_CONFIG_SECRET` 变更会使既有加密的用户密钥无法直接读取。MySQL 与 MinIO 应联合备份并演练恢复。

## 验证入口与未完成项

[`CI`](../.github/workflows/ci.yml) 执行 Maven 测试、前端构建、Compose 冒烟、双实例和秒杀故障注入；对应脚本在 [`scripts`](../scripts)。当前仍需真实模型工具调用、真实 Google OAuth、目标 Kubernetes 沙箱、持续负载、故障恢复和备份恢复演练。性能数字应取自新的压测报告，不沿用历史本机短时测试结果。
