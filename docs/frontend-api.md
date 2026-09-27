# 前后端对接契约

前端路由定义在 [`App.tsx`](../apps/web/src/App.tsx)，API 基址来自 `VITE_API_BASE_URL`（默认 `http://localhost:8080`）。[`useAuth`](../apps/web/src/hooks/useAuth.tsx) 保存不透明 Token；[`buildApiFetch`](../apps/web/src/services/api.ts) 在请求中加入 `Authorization: Bearer <token>`。后端路由以各 `*Controller.java` 上的注解为准。

| 页面 | 主要 API | 对接代码 |
| --- | --- | --- |
| 首页、详情 | `GET /games`、`/games/tags`、`/games/{slug}`、`/games/trending` | [`Home.tsx`](../apps/web/src/pages/Home.tsx)、[`GameDetail.tsx`](../apps/web/src/pages/GameDetail.tsx) |
| 登录、注册 | `POST /auth/login`、`/auth/register`，`GET /auth/session`，`POST /auth/logout` | [`LoginPage.tsx`](../apps/web/src/pages/LoginPage.tsx)、[`RegisterPage.tsx`](../apps/web/src/pages/RegisterPage.tsx)、[`AuthController`](../apps/api-java/src/main/java/com/gameweare/api/auth/AuthController.java) |
| 创作工作区 | `/create/ai-config`、`/create/jobs`、`/create/runs/{id}/steps`、`/create/runs/{id}/events`、`/create/jobs/{id}/publish` | [`Create.tsx`](../apps/web/src/pages/Create.tsx)、[`CreateController`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateController.java) |
| 试玩 | `GET /play/{slug}/manifest`、`/play/{slug}/document`，`POST /play/events` | [`PlayGame.tsx`](../apps/web/src/pages/PlayGame.tsx)、[`PlayController`](../apps/api-java/src/main/java/com/gameweare/api/play/PlayController.java) |
| 奖励 | `/checkins`、`/vouchers/me`、`/voucher-campaigns` | [`Rewards.tsx`](../apps/web/src/pages/Rewards.tsx)、[`voucher` 控制器](../apps/api-java/src/main/java/com/gameweare/api/voucher) |
| 管理后台 | `/maintenance/**` | [`MaintainerPanel.tsx`](../apps/web/src/pages/MaintainerPanel.tsx)、[`MaintenanceController`](../apps/api-java/src/main/java/com/gameweare/api/maintenance/MaintenanceController.java) |

## 认证与错误

受保护接口要求 Bearer Token。前端启动后用 `/auth/session` 恢复登录态；后端从 MySQL 会话摘要与 Redis 撤销/缓存判断有效性。管理路由还要求管理员或维护员角色，前端隐藏入口不构成权限控制。接口失败时应读取 HTTP 状态与响应体；[`readApiError`](../apps/web/src/services/api.ts) 会优先展示 `detail.llm.message`、`detail.message` 等具体原因，不应把不同生成失败合并成固定文案。

## 创建任务与进度

上传图片先调用 `POST /uploads`，然后把返回的资产 ID 传入任务；`files` 是旧兼容字段，非空会被拒绝。创建请求示例：

```http
POST /create/jobs
Authorization: Bearer <accessToken>
X-Idempotency-Key: <每次用户意图唯一的键>
Content-Type: application/json

{"prompt":"制作一个可玩的平台跳跃游戏","agentMode":"react","createType":"init","fundingMode":"byok","inputAssets":[]}
```

`agentMode` 支持 `chat`、`react`、`plan`、`decentralized`；`refine` 仅用于 `createType=opt`。`fundingMode=voucher` 时同时传 `voucherId`，由后端占券并使用官方模型。`POST /create/jobs` 返回 202 和任务信息。`GET /create/jobs` 用于侧栏，`GET /create/jobs/{id}` 用于详情；`GET /create/runs/{id}/steps` 与 SSE `/create/runs/{id}/events` 用于进度。`plan` 需要 `/plan-preview` 与 `/plan-decision`；`decentralized` 需要候选预览、选择和确认。完成后先预览，再调用 `/create/jobs/{id}/publish` 发布。优化任务发布前不会替换线上版本或原始封面。

任务列表显示 `displayTitle`、中文状态与模式；完整提示词保留在详情。[`DELETE /create/jobs/{id}`](../apps/api-java/src/main/java/com/gameweare/api/create/CreateController.java) 仅允许本人删除终态任务，隐藏任务和轨迹，已发布游戏与审计数据保留。

## 外部 Agent 产物

这是一条不调用项目内 AI 的独立路径：

1. `POST /create/artifacts/validate` 提交 `{ "html": "<完整单文件 HTML>" }`；响应中 `ok=false` 时也可能是 HTTP 200，`diagnostics` 给出 `code/message/scriptIndex/line`。
2. 修复所有诊断后，`POST /create/artifacts` 提交 `{ "prompt", "html", "projectId?" }`；成功为 201，校验失败为 422。可带 `X-Idempotency-Key` 防止重复创建草稿。
3. 外部提交版本默认为待审，不会直接覆盖已公开版本。语法通过不表示浏览器运行或内容安全已通过。

## 游戏播放协议

`manifest.documentUrl` 指向受后端控制的 HTML 文档。前端在 `sandbox="allow-scripts"` iframe 中加载，不赋予同源权限；后端还附加 CSP。页面通过 `POST /play/events` 上报 `game_start` / `game_end` 等事件。公开目录、封面、版本切换和作者权限均由后端按 MySQL 状态判断。
