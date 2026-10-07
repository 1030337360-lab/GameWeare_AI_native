# 前后端对接契约

前端路由定义在 [`App.tsx`](../apps/web/src/App.tsx)，API 基址来自 `VITE_API_BASE_URL`（默认 `http://localhost:8080`）。[`useAuth`](../apps/web/src/hooks/useAuth.tsx) 保存不透明 Token；[`buildApiFetch`](../apps/web/src/services/api.ts) 在请求中加入 `Authorization: Bearer <token>`。后端路由以各 `*Controller.java` 上的注解为准。

| 页面 | 主要 API | 对接代码 |
| --- | --- | --- |
| 首页、详情、评论 | `GET /games?sort=latest|likes`、`/games/tags`、`/games/{slug}`、`/games/trending`、`/games/{slug}/comments` | [`Home.tsx`](../apps/web/src/pages/Home.tsx)、[`GameDetail.tsx`](../apps/web/src/pages/GameDetail.tsx) |
| 登录、注册 | `POST /auth/login`、`/auth/register`，`GET /auth/session`，`POST /auth/logout` | [`LoginPage.tsx`](../apps/web/src/pages/LoginPage.tsx)、[`RegisterPage.tsx`](../apps/web/src/pages/RegisterPage.tsx)、[`AuthController`](../apps/api-java/src/main/java/com/gameweare/api/auth/AuthController.java) |
| 创作工作区 | `/create/ai-config`、`/create/jobs`、`/create/runs/{id}/steps`、`/create/runs/{id}/events`、`/create/jobs/{id}/cancel`、`/create/jobs/{id}/publish` | [`Create.tsx`](../apps/web/src/pages/Create.tsx)、[`CreateController`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateController.java) |
| 试玩 | `GET /play/{slug}/manifest`、`/play/{slug}/document`，`POST /play/events` | [`PlayGame.tsx`](../apps/web/src/pages/PlayGame.tsx)、[`PlayController`](../apps/api-java/src/main/java/com/gameweare/api/play/PlayController.java) |
| 奖励 | `/checkins`、`/vouchers/me`、`/voucher-campaigns` | [`Rewards.tsx`](../apps/web/src/pages/Rewards.tsx)、[`voucher` 控制器](../apps/api-java/src/main/java/com/gameweare/api/voucher) |
| 管理后台 | `/maintenance/**` | [`MaintainerPanel.tsx`](../apps/web/src/pages/MaintainerPanel.tsx)、[`MaintenanceController`](../apps/api-java/src/main/java/com/gameweare/api/maintenance/MaintenanceController.java) |

## 认证与错误

受保护接口要求 Bearer Token。前端启动后用 `/auth/session` 恢复登录态；后端从 MySQL 会话摘要与 Redis 撤销/缓存判断有效性。管理路由还要求管理员或维护员角色，前端隐藏入口不构成权限控制。接口失败时应读取 HTTP 状态与响应体；[`readApiError`](../apps/web/src/services/api.ts) 会优先展示 `detail.llm.message`、`detail.message` 等具体原因，不应把不同生成失败合并成固定文案。
`POST /create/ai-config/test` 的 `ok=false` 响应在 `details.providerMessage` 返回脱敏、截断后的供应商错误，便于识别不支持的参数或模型；前端配置区直接展示该字段。

## 创建任务与进度

上传图片先调用 `POST /uploads`，然后把返回的资产 ID 传入任务；`files` 是旧兼容字段，非空会被拒绝。创建请求示例：

```http
POST /create/jobs
Authorization: Bearer <accessToken>
X-Idempotency-Key: <每次用户意图唯一的键>
Content-Type: application/json

{"prompt":"制作一个可玩的平台跳跃游戏","agentMode":"react","createType":"init","fundingMode":"byok","inputAssets":[]}
```

直接生成的 `agentMode` 支持 `react`、`plan`、`decentralized`；`refine` 仅用于 `createType=opt`。省略模式默认 `react`；新的 `chat` 请求返回409，须走下方访谈接口。`fundingMode=voucher` 时同时传 `voucherId`，由后端占券并使用官方模型。`POST /create/jobs` 返回 202 和任务信息。`GET /create/jobs` 用于侧栏，`GET /create/jobs/{id}` 用于详情；`GET /create/runs/{id}/steps` 与 SSE `/create/runs/{id}/events` 用于进度。`plan` 需要 `/plan-preview` 与 `/plan-decision`；`decentralized` 需要候选预览、选择和确认。完成后先预览，再调用 `/create/jobs/{id}/publish` 发布。优化任务发布前不会替换线上版本或原始封面。

## Chat 多轮访谈契约

全部接口要求 Bearer 登录，具体实现见 [`CreationChatController`](../apps/api-java/src/main/java/com/gameweare/api/create/CreationChatController.java) 和 [`CreationChat`](../apps/web/src/components/CreationChat.tsx)。

| API | 请求 / 结果 |
| --- | --- |
| `GET /create/chat/skills` | 可读取的技能 ID、名称、简介和标签 |
| `POST /create/chat/sessions` | `{id:<客户端UUID>,createType:"init",fundingMode:"byok"}`；官方模式加 `voucherId`，优化模式加本人 `projectId`；返回201和空会话 |
| `GET /create/chat/sessions` | 最近30个本人会话摘要，包括画像、状态、revision、费用来源与 jobId |
| `GET /create/chat/sessions/{id}` | 完整画像与有序消息，刷新或切换页面后恢复 |
| `POST /create/chat/sessions/{id}/messages` | `{message,requestId:<UUID>,revision:<当前版本>}`；整轮完成后返回更新后的会话 |
| `POST /create/chat/sessions/{id}/confirm` | `{revision}`；返回202和已创建的 ReAct `CreateJob`，重复确认返回同一个任务 |

会话状态为 `draft → replying → draft`，确认后为 `confirmed`。每轮成功 revision 加1，同时保存一条 user 和一条 assistant 消息；失败不提交半轮。回复中的 `skillIds` 是本轮真实读取过的技能，`requestId` 用于识别网络断线后的已完成请求。会话画像 `brief` 的字段为 `title/concept/genre/coreLoop/controls/rules/victory/artStyle/scope/questions`，`ready` 是服务端基于核心字段判定的可确认状态，不是模型授权。输入最多2000字符，画像每字段最多240字符；每会话最多30轮。正在回复或版本过时返回409，其他用户会话返回404，限流返回429，模型失败返回502且不暴露密钥。

确认前不建立 `create_jobs`、不占券；确认时服务端把存储的最新画像转为生成提示词，不接收客户端伪造的画像或模式。Chat 的图片输入不在本轮访谈协议内，直接 ReAct 的现有图片上传协议继续可用。用户查看并确认画像后，前端切换到现有任务进度、预览与发布页面。

任务列表显示 `displayTitle`、中文状态与模式；完整提示词保留在详情。[`DELETE /create/jobs/{id}`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateController.java) 仅允许本人删除终态任务，隐藏任务和轨迹，已发布游戏与审计数据保留。
本人可对 `pending`、`generating`、`planning`、`reviewing` 任务调用 `POST /create/jobs/{id}/cancel`。响应为 `status=canceled`；已完成任务返回 409。取消后 SSE 结束，任务轨迹保留，可再用 DELETE 隐藏。跨实例以 MySQL 状态和租约为最终判定，运行中的模型请求会尽快中断。

## 评论与点赞排序

`GET /games?sort=likes` 按点赞数降序展示公开游戏；省略 `sort` 时按发布时间。点赞继续使用 `PUT/DELETE /games/{slug}/like`，MySQL 唯一键避免重复计数。`GET /games/{slug}/comments?page=0&limit=20` 返回 `{items,hasMore,page,total}`；登录用户用 `POST /games/{slug}/comments` 提交 `{content}`（1–1000 字符），仅作者可用 `DELETE /games/{slug}/comments/{commentId}` 删除自己的评论。评论只在已公开游戏上可见，前端以普通文本呈现内容。

## 外部 Agent 产物

这是一条不调用项目内 AI 的独立路径：

1. `POST /create/artifacts/validate` 提交 `{ "html": "<完整单文件 HTML>" }`；响应中 `ok=false` 时也可能是 HTTP 200，`diagnostics` 给出 `code/message/scriptIndex/line`。
2. 修复所有诊断后，`POST /create/artifacts` 提交 `{ "prompt", "html", "projectId?" }`；成功为 201，校验失败为 422。可带 `X-Idempotency-Key` 防止重复创建草稿。
3. 外部提交版本默认为待审，不会直接覆盖已公开版本。语法通过不表示浏览器运行或内容安全已通过。

## 游戏播放协议

`manifest.documentUrl` 指向受后端控制的 HTML 文档。前端在 `sandbox="allow-scripts"` iframe 中加载，不赋予同源权限；后端还附加 CSP。页面通过 `POST /play/events` 上报 `game_start` / `game_end` 等事件。公开目录、封面、版本切换和作者权限均由后端按 MySQL 状态判断。
