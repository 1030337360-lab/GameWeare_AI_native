# Gameweare MVP 企业级化改造审查报告与计划

> 范围说明：本次为只读审查，未修改任何文件。以下结论基于对 `apps/api`、`apps/web`、`docker-compose.yml`、Dockerfile、测试目录与 `docs/` 的通读。

## 一、项目现状速览

| 层      | 技术栈                                         | 现状                                                         |
| ------- | ---------------------------------------------- | ------------------------------------------------------------ |
| 前端    | React + Vite + TS (1314)                       | 单文件 `main.tsx` 巨型化，无组件拆分、无 ESLint/Prettier、无 ErrorBoundary、token 存 localStorage |
| 后端    | FastAPI + psycopg + Redis + MinIO (8080)       | 同步端点、每请求新建 DB 连接（无连接池）、`create_service.py` 3876 行、`BackgroundTasks` 进程内执行 |
| 编排    | docker-compose（postgres/minio/redis/api/web） | 默认密钥硬编码、镜像以 root 运行、无资源限制、单 uvicorn worker |
| 数据    | SQL init 脚本                                  | 无 Alembic 迁移、无连接池                                    |
| 测试/CI | 后端有 12 个测试文件                           | 无 `.github/workflows`、无 ruff/mypy、前端零测试、无覆盖率   |

---

## 二、企业级化差距（按严重度排序）

### 🔴 P0 — 安全与可靠性硬伤

1. **密钥默认值危险**：`docker-compose.yml` 中 `JWT_SECRET: dev-change-me`、`AI_CONFIG_ENCRYPTION_SECRET: dev-change-me-32bytes`，启动时无校验，生产可能静默使用弱密钥。
2. **DB 无连接池**：`database.py` 每次 `psycopg.connect()` 新建连接，高并发下连接耗尽/延迟飙升，是最大的可扩展性瓶颈。
3. **`get_job` 端点缺鉴权**：`apps/api/app/routers/create.py:266` `def get_job(job_id: str)` 无 `Depends(require_user)`，任何人凭 job_id 可读任务详情（越权）。
4. **HTML 注入风险**：`main.py:49` `generated_game` 用 `game_id` 直接拼入 HTML，未转义，潜在 XSS。
5. **无限流**：登录/注册/创建任务等敏感接口无 rate limit，易遭暴力破解/滥用。
6. **背景任务不可靠**：`BackgroundTasks` 进程内执行，进程重启即丢失，无重试、无持久化、无水平扩展能力。

### 🟠 P1 — 可观测性与运维

7. **无结构化日志 / 追踪**：无 request-id、trace-id，无统一日志格式，排障困难。
8. **健康检查过浅**：`/health` 仅返回 `ok`，不检查 DB/Redis/MinIO 就绪状态，K8s/Compose 探针无法真实反映健康。
9. **无指标**：无 Prometheus/OpenTelemetry，无法监控 QPS、延迟、LLM 调用耗时与 token 消耗。
10. **无全局异常处理**：未统一错误响应格式，异常堆栈可能直接外泄。
11. **`@app.on_event` 已废弃**：应迁移到 FastAPI `lifespan`。

### 🟡 P2 — 工程化与代码质量

12. **`create_service.py` 3876 行**：上帝模块，职责混杂（AI 配置、项目、运行、任务、发布、预览、去中心化），难以测试与维护。
13. **前端 `main.tsx` 单体**：所有路由、组件、状态、API 调用挤在一个文件，无组件拆分、无 Tanstack Query、无状态管理。
14. **无 API 版本化**：无 `/v1` 前缀，未来不兼容变更困难。
15. **无 CI/CD**：无 GitHub Actions，PR 无自动测试/lint 门禁。
16. **无 lint/type-check 配置**：后端无 ruff/mypy，前端无 ESLint/Prettier。
17. **同步端点做阻塞 I/O**：`def` 端点里同步查 DB，FastAPI 会用线程池兜底但吞吐受限；应统一为 `async` + asyncpg/psycopg async。

### 🟢 P3 — 部署与供应链

18. **镜像以 root 运行**：API/Web Dockerfile 无 `USER` 指令，违反最小权限。
19. **无资源限制**：compose 未设 `mem_limit`/`cpus`，单服务可拖垮整机。
20. **无多阶段构建（API）**：保留构建依赖增大镜像。
21. **无 TLS 终止/反向代理**：nginx 仅服务前端静态资源，未代理 API，生产无 HTTPS。
22. **单 uvicorn worker**：`CMD ["uvicorn", ...]` 单进程，未利用多核。
23. **无 Alembic 迁移**：仅靠 init SQL，schema 演进无版本控制、无回滚。

---

## 三、改造计划（分阶段，可独立交付）

### 阶段 1：安全与可靠性基线（1–2 周）

| 项           | 动作                                                         | 文件                                |
| ------------ | ------------------------------------------------------------ | ----------------------------------- |
| 密钥启动校验 | `config.py` 在非 dev 环境校验 `JWT_SECRET`/`AI_CONFIG_ENCRYPTION_SECRET` 非默认值且长度足够 | `app/config.py`                     |
| DB 连接池    | 引入 `psycopg_pool.ConnectionPool`（或迁 asyncpg），`database.py` 改为池化获取，`get_settings()` 初始化单例池 | `app/database.py`, `app/config.py`  |
| 修复越权     | `get_job` 增加 `Depends(require_user)` 并校验 job 归属       | `app/routers/create.py`             |
| 修复 XSS     | `generated_game` 对 `game_id` 做 HTML 转义或用模板引擎       | `app/main.py`                       |
| 限流         | 接入 `slowapi` 或自写 Redis 令牌桶中间件，覆盖 `/auth/login`、`/auth/register`、`/create/jobs` | 新建 `app/middleware/rate_limit.py` |
| 加密静态化   | 确认 Google access_token 落库前用 Fernet 加密（密钥来自配置） | `app/services/auth_service.py`      |

### 阶段 2：可观测性与运维（1 周）

| 项            | 动作                                                         |
| ------------- | ------------------------------------------------------------ |
| 结构化日志    | 引入 `structlog`，中间件注入 `request_id`（`X-Request-ID`），所有日志带 trace 上下文 |
| 深度健康检查  | `/health` 拆为 liveness（`/healthz`）+ readiness（`/readyz`，检查 DB/Redis/MinIO） |
| 指标          | 接入 `prometheus-fastapi-instrumentator`，暴露 `/metrics`；自定义 LLM 调用耗时/token 直方图 |
| 全局异常处理  | `@app.exception_handler` 统一 `{code,message,requestId}` 格式，隐藏堆栈 |
| lifespan 迁移 | `@app.on_event` → `async with lifespan(app)`                 |
| 后台任务队列  | 引入 `dramatiq`/`rq` + Redis broker（或 Celery），`create/jobs` 改投队列，worker 独立进程，支持重试与水平扩展 |

### 阶段 3：工程化与代码质量（2–3 周）

| 项         | 动作                                                         |
| ---------- | ------------------------------------------------------------ |
| 模块拆分   | `create_service.py` 按职责拆为 `ai_config_service`/`project_service`/`run_service`/`job_service`/`publish_service`/`decentralized_service` |
| 前端重构   | `main.tsx` 拆为 `routes/`、`components/`、`hooks/`、`api/`、`store/`；引入 `@tanstack/react-query` 管理服务端状态；token 改为内存 + httpOnly cookie 备选 |
| API 版本化 | 全部 router 加 `/api/v1` 前缀，老路径保留 301 一段时间       |
| Lint/Type  | 后端加 `ruff` + `mypy` 配置；前端加 `eslint` + `prettier` + `stylelint` |
| CI/CD      | 新建 `.github/workflows/ci.yml`：后端 ruff+mypy+pytest、前端 eslint+tsc+build、Docker 镜像构建；PR 必过 |
| 测试补强   | 前端引入 `vitest`+`@testing-library`；后端补 router 集成测试与覆盖率门槛（≥70%） |

### 阶段 4：部署与供应链（1 周）

| 项           | 动作                                                         |
| ------------ | ------------------------------------------------------------ |
| 镜像安全     | API/Web Dockerfile 加非 root `USER`；API 多阶段构建去掉构建依赖 |
| 资源限制     | compose 加 `deploy.resources.limits`；uvicorn `--workers 4`（或 gunicorn+uvicorn worker） |
| TLS/反代     | nginx 增加 `/api` 反代到 api 服务，启用 HTTPS（生产）；CORS 收敛为环境变量驱动 |
| Alembic      | 引入 Alembic，把 `db/init/*.sql` 转为版本化迁移，CI 自动 `alembic upgrade head` |
| Secrets 管理 | docker-compose 用 `secrets:` 或外部 Vault/SOPS，移除所有明文默认密钥 |

### 阶段 5：可扩展性深化（长期）

- LLM 调用统一抽象 + 重试/超时/熔断（tenacity），失败可恢复 resume
- 多 agent 去中心化执行从"注册契约"落地为独立调度 worker
- 生成的 HTML 沙箱安全扫描（CSP、外链脚本、文件大小、平台密钥访问）
- MinIO 预签名 URL + CDN，前端直传
- 多租户/配额/计费（若面向 SaaS）

---

## 四、建议优先级路线图

```
第1周: P0 安全与连接池 (阶段1)          ← 立即止血
第2周: 可观测性 + 异常处理 (阶段2 前半)  ← 可运维
第3周: 后台任务队列化 (阶段2 后半)       ← 可靠生成
第4-5周: 模块拆分 + CI + lint (阶段3)    ← 可维护
第6周: 部署硬化 (阶段4)                  ← 可上线
持续:   阶段5                            ← 可规模化
```

## 五、风险提示

- **连接池迁移**需确认 `psycopg_pool` 与现有同步端点兼容，或一并迁 async（工作量较大但收益高）。
- **后台任务队列化**会改变 `BackgroundTasks` 的即时性，需保证 SSE 事件链路不受影响。
- **API 版本化**与前端 token 存储改造需前后端协同发布。
- **create_service 拆分**涉及 3876 行高频引用代码，需先补集成测试再动刀，避免回归。

---

如需，我可以切换到 ACT MODE 按上述路线图从 **阶段 1（安全与连接池止血）** 开始落地实现。请确认从哪一阶段开始，或是否需要我先把本计划写入 `docs/enterprise-hardening-plan.md` 供团队评审。