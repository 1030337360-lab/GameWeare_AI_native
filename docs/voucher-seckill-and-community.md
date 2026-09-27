# 生成券、签到与社区功能

## 实现边界

生成券用于支付一次游戏初创或优化任务，所有现有 Agent 模式共用券包。用户自带 API Key 的 `byok` 任务独立运行；用券任务读取服务端 `OFFICIAL_LLM_BASE_URL`、`OFFICIAL_LLM_MODEL`、`OFFICIAL_LLM_API_KEY`。这些变量不得写入前端、仓库或日志。未配置官方模型时，服务端拒绝用券任务。用券任务没有本地 Token 或工具调用次数上限，仍受提供方错误、任务状态和既有校验约束。

## 一致性路径

1. 管理员提前创建活动并设置时间与总库存。活动写入 MySQL，提交后以 `SETNX` 预热 Redis 库存。Redis 库存缺失时抢券失败关闭。
2. `POST /voucher-campaigns/{id}/claim` 调用单个 Lua 脚本。Redis 服务器时间决定活动窗口；脚本检查用户是否已有预留、库存是否大于零，再执行 `DECR`、记录独立的 `reservationId`、写入 Redis Stream。`remainingAfter` 是预扣瞬间的库存槽位快照，补偿后可能重复，因此仅 `reservationId` 用作幂等凭证。
3. API 返回 `202` 与 `status=pending`。页面显示“抢到名额，发放中”，可用活动 ID 和预留 ID 查询状态。
4. 定时中继读取 Stream，通过 RabbitMQ 发布确认投递，再删除 Stream 事件。重复转发允许发生。消费者在 MySQL 事务中锁定活动行，核对 Redis 预留状态，条件扣减库存，依靠 `(campaign_id,user_id)` 唯一约束，再发一张生成券。MySQL 的发券记录与剩余库存是最终依据。
5. RabbitMQ 短、长延迟队列负责失败重试。终态失败时，持有同一活动 MySQL 行锁核对未发券后才按 `reservationId` 补偿 Redis。补偿释放用户预留，但保留限时的预留归属与 `failed` 状态，供原用户按 ID 查询。十分钟以上的孤儿预留由定时对账扫描并补偿。已发券绝不退回预扣。
6. 一个创建任务在 MySQL 事务中条件占用券；可玩版本落库时核销。失败、取消或审批拒绝时返还；已过期券返还为过期状态。同券并发任务由条件更新限制为一个。

Redis AOF 和持久卷由 Compose 配置。Redis、RabbitMQ 或 MySQL 故障时，新的抢券不会伪装为到账；RabbitMQ 投递及消费会重试。Redis 完全丢失活动键后不会根据 MySQL 库存自动恢复进行中的活动，需人工核对，避免遗失的预留引起超发。

## 签到与社区

- 签到日期按 `Asia/Shanghai` 自然日。MySQL `(user_id,checkin_day)` 唯一约束和用户签到状态行锁决定连续天数；Redis Bitmap 供日历展示。
- 默认连续 7 天、30 天各一张，30 天有效。`checkin_awards` 记录里程碑和发券数量，每用户每自然月最多两张。管理员规则写入未来生效表，当前签到读取到时已生效的最新规则。
- 关注关系以 MySQL 唯一主键为准，Redis Set 仅加速共同关注；关注动态流仍由 MySQL 查公开游戏。热榜 ZSet、签到榜 ZSet、游玩 UV HyperLogLog 均是可重建的展示投影，不参与发券、授权或计费。
- 公开游戏详情使用 Cache Aside、60–120 秒随机 TTL、10 秒空值缓存和 10 秒热点重建锁。每次详情读取仍先由 MySQL 判断发布状态和公开可见性，个人点赞状态也从 MySQL 读取。

## 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/checkins/me`, `/checkins` | 签到日历、签到 |
| GET | `/checkins/leaderboard` | 连续签到榜 |
| GET | `/vouchers/me` | 券包 |
| GET/POST | `/voucher-campaigns`, `/voucher-campaigns/{id}/claim` | 活动与预扣 |
| GET | `/voucher-campaigns/{id}/claims/{reservationId}` | 本人预留进度 |
| POST | `/create/jobs` | `fundingMode=byok|voucher`；用券时传 `voucherId` |
| GET/PUT/DELETE | `/creators/{id}`, `/creators/{id}/follow` | 创作者、关注 |
| GET | `/creators/{id}/following/common`, `/feed/following` | 共同关注、动态流 |
| GET | `/games/trending` | 游戏热榜 |
| GET | `/maintenance/analytics/uv` | 近似游玩 UV |
| GET/POST | `/maintenance/voucher-campaigns` | 活动管理 |
| GET | `/maintenance/voucher-campaigns/{id}/reconcile` | 库存对账 |
| GET/PUT | `/maintenance/reward-rules` | 未来签到奖励规则 |

## 验收

- `apps/api-java`: `mvn test`；`apps/web`: `npm run build`。
- `scripts/ci-smoke.ps1` 覆盖登录、签到重复请求、券包、热榜和已有创建流程。
- `scripts/seckill-verify.ps1` 在两个 API 实例间发起并发抢券，验收库存为 1、最终只发 1 张、MySQL 库存对账及响应 P95。它只统计短时并发请求，不声称持续吞吐量。
- CI 的隔离 Compose 环境安排了 RabbitMQ 停机后 Stream 补投、重复 RabbitMQ 消息、消费者持续失败后的延迟补偿和 Redis AOF 重启验收。本机已分别通过这四项；生产上线前仍应观察 Stream 积压、死信、预留超时数和 MySQL 对账结果。

本机验收记录（2026-09-27）：两个 Java API 实例共享 MySQL、Redis、RabbitMQ，在库存为 1 的活动上发出 80 次并发抢券请求。响应 P95 为 **279 ms**，最终发券 **1**、MySQL 剩余库存 **0**、Redis 剩余库存 **0**；这个数值仅描述本次短时本机测试。另一轮同实例 40 次请求的 P95 为 120.8 ms。已用 mock 模型完成一次领券、创建游戏、发布、访问可玩 HTML 的流程；同券并发创建返回 HTTP 409。因旧版 8080 worker 同时消费过测试任务，终态券状态对账把已完成任务的券从 `reserved` 修复为 `used`。上线时应先排空旧 worker，再开启新版本消费。

重启电脑后的复验（2026-09-27）：恢复本地依赖和 API 后，发现活动 `DATETIME` 在本机时区写入、按 UTC 读取，导致活动开始后仍返回 409；现统一按 UTC 写入和读取。修复后，库存为 1 的 20 次并发请求最终仅发券 1 张，MySQL 与 Redis 剩余库存均为 0，P95 为 **160 ms**。RabbitMQ 重复投递没有再次扣库存；RabbitMQ 停机期间可以预留，恢复后 Stream 中继完成发券；Redis 重启后库存对账仍平衡。另在配置 mock 官方模型的容器 API 上，20 次并发抢券的 P95 为 **2139 ms**，随后验证同券第二个创建请求返回 409、游戏任务完成后券状态为 `used`、发布的游玩 HTML 返回 200 且包含 canvas。两轮 P95 都是短时本机数据，不能推断持续吞吐或生产延迟。

延迟补偿复验：测试活动库存为 1，预扣成功后通过测试专用 SQL 将活动标记为取消，使 MySQL 发券事务持续失败。RabbitMQ 重试耗尽后，原用户按 `reservationId` 查询到 `failed`；最终发券 0、MySQL 剩余 1、Redis 剩余 1，且无悬挂预留。第一次故障注入发现补偿后查询返回 404，已修复并重测通过。
