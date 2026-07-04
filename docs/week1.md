# Yahaha-MVP Week 1 改造计划

> 基于《Yahaha MVP 企业级化改造审查报告与计划.md》的阶段 1（安全与可靠性基线），拆解为 7 天可执行任务。

---

## Week 1 目标

完成阶段 1「安全与可靠性基线」的全部 6 项改造，实现"立即止血"。

---

## 项目现状

| 模块 | 现状 | 问题 |
|------|------|------|
| 前端 | React + Vite + TS (1314) | 单文件 `main.tsx` 巨型化，无组件拆分、无 ESLint/Prettier、无 ErrorBoundary、token 存 localStorage |
| 后端 | FastAPI + psycopg + Redis + MinIO (8080) | 同步端点、每请求新建 DB 连接（无连接池）、`create_service.py` 3876 行、`BackgroundTasks` 进程内执行 |
| 编排 | docker-compose | 默认密钥硬编码、镜像以 root 运行、无资源限制、单 uvicorn worker |
| 数据 | SQL init 脚本 | 无 Alembic 迁移、无连接池 |
| 测试/CI | 后端有 12 个测试文件 | 无 `.github/workflows`、无 ruff/mypy、前端零测试、无覆盖率 |

---

## Day 1：密钥启动校验 + 配置安全

**目标**：防止生产环境使用默认弱密钥

**任务清单**：
- [ ] 修改 `app/config.py`，在非 dev 环境校验 `JWT_SECRET` 和 `AI_CONFIG_ENCRYPTION_SECRET`
  - 校验规则：非默认值、长度 >= 32 字节
  - 启动时若校验失败，抛出 `ValueError` 并明确提示
- [ ] 校验 `AI_CONFIG_ENCRYPTION_SECRET` 必须为 32 字节（AES-256 要求）
- [ ] 添加 `ENVIRONMENT` 配置项（dev/staging/prod），仅在非 dev 环境执行严格校验
- [ ] 更新 `docker-compose.yml` 注释，提醒修改默认密钥

**产出文件**：
```
apps/api/app/config.py          # 修改
apps/api/docker-compose.yml      # 添加注释提醒
```

**验收标准**：
- [ ] `JWT_SECRET=dev-change-me` 在 staging/prod 环境启动失败
- [ ] `JWT_SECRET=my-32-char-secret-key-here!!!` 在 staging/prod 环境启动成功
- [ ] dev 环境保持宽松，方便本地开发

---

## Day 2：DB 连接池

**目标**：消除高并发下连接耗尽的隐患

**任务清单**：
- [ ] 引入 `psycopg_pool`（或迁 asyncpg），在 `database.py` 中初始化连接池
- [ ] 修改 `get_db()` 依赖，从连接池获取连接而非新建
- [ ] 配置连接池参数：min_size、max_size、max_idle_lifetime、max_lifetime
- [ ] 确认所有现有同步端点兼容连接池模式
- [ ] 添加连接池健康检查端点（供 `/readyz` 使用）

**产出文件**：
```
apps/api/app/database.py         # 重写，引入连接池
apps/api/app/config.py           # 添加连接池配置项
```

**验收标准**：
- [ ] `python -c "from app.database import get_pool; print(get_pool)"` 成功
- [ ] 连续 100 次 API 请求，连接数稳定在 max_size 以内
- [ ] 服务重启后连接池正确关闭，无泄漏

---

## Day 3：修复越权 + 修复 XSS

**目标**：消除安全漏洞

**任务清单**：
- [ ] 修复 `get_job` 端点越权：`apps/api/app/routers/create.py:266`
  - 添加 `Depends(require_user)`
  - 校验 job 归属：当前用户只能访问自己的 job
  - 返回 403 而非 404（避免信息泄露）
- [ ] 修复 `generated_game` XSS：`apps/api/app/main.py:49`
  - 对 `game_id` 做 HTML 转义（`html.escape`）
  - 或使用模板引擎（Jinja2）而非字符串拼接
- [ ] 检查其他路由是否存在类似越权问题（`get_plan_preview`、`get_generation_job` 等）
- [ ] 补充安全测试：越权访问返回 403

**产出文件**：
```
apps/api/app/routers/create.py   # 修改
apps/api/app/main.py              # 修改
apps/api/tests/test_security.py   # 新增（可选）
```

**验收标准**：
- [ ] 未登录用户访问 `/create/jobs/{job_id}` 返回 401
- [ ] 用户 A 访问用户 B 的 job 返回 403
- [ ] `game_id` 包含 `<script>alert(1)</script>` 时不执行脚本

---

## Day 4：限流

**目标**：防止暴力破解和 API 滥用

**任务清单**：
- [ ] 引入 `slowapi` 或自写 Redis 令牌桶中间件
- [ ] 对敏感接口限流：
  - `/auth/login`：5 次/分钟/IP
  - `/auth/register`：3 次/分钟/IP
  - `/create/jobs`：10 次/分钟/用户
- [ ] 限流响应：429 Too Many Requests，带 Retry-After 头
- [ ] 配置白名单（可选）：内部服务 IP 豁免

**产出文件**：

```
apps/api/app/middleware/rate_limit.py   # 新增
apps/api/app/main.py                     # 注册中间件
apps/api/app/config.py                   # 添加限流配置
```

**验收标准**：

- [ ] 连续 6 次登录失败，第 7 次返回 429
- [ ] 等待 60 秒后，登录恢复正常
- [ ] 正常用户操作不受影响

---

## Day 5：加密静态化 + 数据安全审计

**目标**：确保敏感数据存储安全

**任务清单**：

- [ ] 确认 Google access_token 落库前用 Fernet 加密
  - 检查 `app/services/auth_service.py`
  - 若未加密，添加加密逻辑
- [ ] 检查 `user_ai_configs` 表中的 `api_key` 存储方式
  - 当前使用 `pgp_sym_encrypt`，确认密钥来源安全
  - 检查解密后是否在日志中泄露
- [ ] 检查 Redis 缓存中的敏感数据
  - `_cache_ai_config` 是否明文存储 API key
  - 若明文，改为加密存储或只存引用
- [ ] 添加数据安全审计日志：敏感操作记录到 `audit_logs` 表

**产出文件**：
```
apps/api/app/services/auth_service.py    # 修改
apps/api/app/services/create_service.py  # 修改（Redis 缓存加密）
apps/api/app/audit.py                    # 新增（可选）
```

**验收标准**：
- [ ] 数据库中 `access_token` 字段为密文
- [ ] Redis 中 `api_key` 为密文或不存在
- [ ] 审计日志记录敏感操作（登录、配置修改、job 创建）

---

## Day 6：全局异常处理 + 错误响应统一

**目标**：防止异常堆栈外泄，统一错误格式

**任务清单**：
- [ ] 在 `main.py` 中添加全局异常处理中间件
  - `@app.exception_handler(Exception)`：返回 `{code: 500, message: "Internal Server Error", requestId: "..."}`
  - `@app.exception_handler(HTTPException)`：保留原有行为，但添加 requestId
  - `@app.exception_handler(RateLimitExceeded)`：返回 429
- [ ] 引入 `structlog` 或标准 logging，记录异常堆栈（仅服务端）
- [ ] 所有错误响应包含 `requestId`，方便排障
- [ ] 检查现有代码中的 `try/except`，确保不吞掉异常

**产出文件**：
```
apps/api/app/exceptions.py               # 新增
apps/api/app/main.py                     # 注册异常处理
```

**验收标准**：
- [ ] 访问不存在的路由返回 `{code: 404, message: "...", requestId: "..."}`
- [ ] 服务端日志包含完整堆栈
- [ ] 客户端看不到 Python 堆栈

---

## Day 7：lifespan 迁移 + 健康检查 + 回归测试

**目标**：完成阶段 1 收尾，确保服务稳定

**任务清单**：
- [ ] 迁移 `@app.on_event` -> `async with lifespan(app)`
  - 检查 `main.py` 中的 `startup` 和 `shutdown` 事件
  - 使用 FastAPI 的 `lifespan` 上下文管理器
- [ ] 深度健康检查
  - `/healthz`：liveness，始终返回 200（服务存活）
  - `/readyz`：readiness，检查 DB/Redis/MinIO 连接，全部通过返回 200
- [ ] 回归测试
  - 跑通所有现有测试（pytest）
  - 手动验证核心流程：注册 -> 登录 -> 创建 job -> 查看 job -> 播放
- [ ] 更新 `docs/` 文档，记录阶段 1 完成项

**产出文件**：
```
apps/api/app/main.py                     # 修改
apps/api/app/health.py                   # 新增
```

**验收标准**：
- [ ] `/healthz` 返回 200
- [ ] `/readyz` 在 DB/Redis/MinIO 全部正常时返回 200
- [ ] `/readyz` 在 DB 断开时返回 503
- [ ] 所有 pytest 通过
- [ ] 核心流程手动验证通过

---

## 文件变更总览

### 修改文件

```
apps/api/app/config.py                   # 密钥校验、连接池配置、限流配置
apps/api/app/database.py                  # 连接池化
apps/api/app/main.py                      # lifespan、异常处理、健康检查
apps/api/app/routers/create.py           # 越权修复
apps/api/app/services/auth_service.py    # access_token 加密
apps/api/app/services/create_service.py  # Redis 缓存加密
apps/api/docker-compose.yml              # 密钥注释提醒
```

### 新增文件

```
apps/api/app/middleware/rate_limit.py    # 限流中间件
apps/api/app/exceptions.py                # 全局异常处理
apps/api/app/health.py                    # 深度健康检查
apps/api/tests/test_security.py           # 安全测试（可选）
```

---

## 关键依赖关系

```
Day 1 (密钥校验)
  |
  |-> Day 2 (连接池) -> Day 7 (readyz 检查 DB 连接)
  |
  |-> Day 3 (越权/XSS) -> Day 7 (回归测试)
  |
  |-> Day 4 (限流) -> Day 6 (异常处理兼容 429)
  |
  |-> Day 5 (加密) -> Day 7 (回归测试验证)
       |
       Day 6 (异常处理)
       |
       Day 7 (lifespan + 健康检查 + 回归)
```

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 密钥校验导致本地开发受阻 | 高 | `ENVIRONMENT=dev` 时跳过严格校验 |
| 连接池与同步端点不兼容 | 高 | 先验证 `psycopg_pool` 与现有代码兼容，再全面替换 |
| 越权修复影响现有前端 | 中 | 检查前端是否依赖匿名访问 job，若有则添加公开 job 逻辑 |
| 限流误伤正常用户 | 中 | 限流阈值放宽，先监控再收紧；支持白名单 |
| access_token 加密后无法解密 | 高 | 先在测试环境验证加解密流程，再上线 |
| lifespan 迁移导致启动失败 | 中 | 保留旧 `@app.on_event` 作为 fallback，验证通过后再删除 |

---

## 验收标准（Week 1 结束）

- [ ] 生产环境启动时，默认密钥会导致服务拒绝启动
- [ ] DB 连接池稳定运行，高并发下无连接耗尽
- [ ] 未授权用户无法访问他人 job
- [ ] XSS payload 在 `game_id` 中不执行
- [ ] 暴力登录会被限流（429）
- [ ] access_token 在数据库中为密文
- [ ] 所有错误响应包含 `requestId`，不泄露堆栈
- [ ] `/readyz` 真实反映服务健康状态
- [ ] 所有 pytest 通过
- [ ] 核心流程手动验证通过

---

## 附录：阶段 1 原始清单对照

| 原始项 | 对应 Day | 状态 |
|--------|---------|------|
| 密钥启动校验 | Day 1 | 待执行 |
| DB 连接池 | Day 2 | 待执行 |
| 修复越权 | Day 3 | 待执行 |
| 修复 XSS | Day 3 | 待执行 |
| 限流 | Day 4 | 待执行 |
| 加密静态化 | Day 5 | 待执行 |
| lifespan 迁移 | Day 7 | 待执行 |
| 深度健康检查 | Day 7 | 待执行 |
| 全局异常处理 | Day 6 | 待执行 |
