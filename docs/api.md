# GameWeare Java API 速览

基础地址：`http://localhost:8080`。实现位于 `apps/api-java/src/main/java/com/gameweare/api`。个人与修改类接口使用 `Authorization: Bearer <accessToken>`；`/maintenance/**` 还要求 `admin` 或 `maintainer` 角色。Token 是随机不透明字符串，MySQL 仅保存摘要，不是 JWT。

## 认证

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register`、`/auth/login` | 邮箱密码注册/登录，返回 `accessToken` |
| POST | `/auth/logout` | 撤销当前 Token |
| GET | `/auth/session` | 当前登录态 |
| GET | `/auth/google/start`、`/auth/google/callback` | Google OAuth 登录；需要配置 Google 凭证 |
| GET | `/auth/google/link/start` | 登录用户关联 Google 账号 |

## 游戏、上传与试玩

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/games`、`/games/tags`、`/games/{slug}` | 已发布目录、标签、详情 |
| GET | `/games/{slug}/versions`、`/games/{slug}/cover` | 版本与封面 |
| POST | `/games/{slug}/versions/switch`、`/games/{slug}/remix` | 作者切换版本、复刻 |
| PUT/DELETE | `/games/{slug}/like`、`/games/{slug}/favorite` | 点赞/收藏状态 |
| DELETE | `/games/{slug}` | 作者软删除 |
| POST | `/uploads` | 上传图片到 MinIO，返回资产引用 |
| GET/DELETE | `/uploads/{assetId}/content`、`/uploads/{assetId}` | 读取/删除本人上传 |
| GET | `/play/{slug}/manifest`、`/play/{slug}/document` | 试玩清单与 sandbox HTML |
| POST | `/events/play` | 记录试玩事件（`/play/events` 为兼容路径） |

## 创建与生成

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/PUT | `/create/ai-config` | 查看非敏感配置/加密保存 AI 密钥 |
| POST | `/create/ai-config/test` | 测试 Responses API 连接 |
| POST | `/create/jobs` | 创建异步任务，建议传 `X-Idempotency-Key` |
| POST | `/create/artifacts/validate` | 接收 `{ "html": "..." }`，返回 `{ ok, format, diagnostics }`，供外部 Agent 修复编译错误 |
| POST | `/create/artifacts` | 接收 `{ "prompt", "html", "projectId?" }`，保存通过校验的单文件 HTML 草稿，返回 `jobId/projectId/gameId/versionId` |
| GET | `/create/jobs/{id}`、`/create/runs/{id}`、`/create/runs/{id}/steps` | 任务与运行步骤 |
| GET | `/create/runs/{id}/events` | SSE 进度流 |
| POST | `/create/jobs/{id}/publish` | 发布生成的游戏 |
| GET | `/create/projects`、`/create/projects/{id}`、`/create/projects/{id}/preview`、`/create/recent-game` | 项目与预览 |
| DELETE | `/create/projects/{id}` | 删除项目 |
| GET/POST | `/create/runs/{id}/plan-preview`、`/create/runs/{id}/plan-decision` | 规划预览与批准 |
| GET/POST | `/create/runs/{id}/decentralized-previews`、`/create/runs/{id}/decentralized-selection`、`/create/runs/{id}/decentralized-confirm` | 三候选方向选择 |

`POST /create/jobs` 的 JSON 包含 `prompt`、`agentMode`（chat、react、plan、decentralized，续作还支持 refine）、`createType`（init 或 opt）、可选 `projectId` 和至多三个已上传的 `inputAssets`。`files` 旧字段仅为兼容读取，非空会被拒绝；请先调用 `/uploads`。AgentScope 的 react 使用工具循环；plan 和 decentralized 会先返回待审方案或候选方向，用户确认后才继续生成。完成的任务返回版本号及仅所有者可读取的封面预览。续作生成新版本草稿；`POST /create/jobs/{id}/publish` 才切换公开版本和封面。`GET /games/{slug}/cover` 会为旧游戏提供安全 SVG 封面。

新建生成任务不设置项目内 Token 上限，也不检查本地虚拟余额。模型服务商 API 自行判断其账户额度；服务端持久化响应中的逐调用用量与任务总用量。旧任务的本地预留/退款账本仍保留以便审计。

外部 Agent 的接收路径需要用户 Bearer Token。先调用 `/create/artifacts/validate`；语法错误仍返回 HTTP 200 与 `ok=false`，`diagnostics` 含 `code/message/scriptIndex/line`。提交到 `/create/artifacts` 时建议使用 `X-Idempotency-Key`，相同用户和请求重复提交返回同一草稿，不同内容复用该键返回 409。提交未通过校验返回 422。该路径不会调用模型或扣费，`actual_tokens=0`。校验仅做 HTML 包装、自包含资源规则和 JavaScript 语法解析，不执行脚本；版本的 `safety_status` 为 `pending`，外部产物须完成独立安全审核后才能发布，已有已发布版本不会因新的待审核修订而下线。

传给 Agent 的校验调用示例：

```text
POST /create/artifacts/validate
{"html":"<!doctype html><html><head><title>Game</title></head><body><canvas></canvas><script>const score = ;</script></body></html>"}

{"ok":false,"format":"single-html","diagnostics":[{"code":"JS_SYNTAX","message":"...","scriptIndex":1,"line":1}]}
```

## 个人与维护

- `GET /profile/activity`、`GET /profile/projects/{id}`：仅本人可查看。
- `/maintenance/overview`、`/maintenance/jobs`、`/maintenance/create-runs/failed`、`/maintenance/games`、`/maintenance/assets`、`/maintenance/reviews` 及相应审核、重试、修改、删除操作：仅维护员或管理员。

健康检查：`GET /health` 与 `GET /actuator/health`。`/health` 仅表示进程响应；部署 readiness 仍需补充依赖检查。端到端验证脚本见 `scripts/e2e-verify.ps1`，当前覆盖的是 Mock LLM 环境。
