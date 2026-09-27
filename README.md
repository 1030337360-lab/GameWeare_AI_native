# GameWeare — AI 游戏创作与游玩平台

本仓库是 [1030337360-lab/GameWeare_AI_native](https://github.com/1030337360-lab/GameWeare_AI_native) 的本地项目。此前用于对照的参考仓库是 [charlie11sun-netizen/yahaha](https://github.com/charlie11sun-netizen/yahaha)，两者不是同一个项目。

**命名约定：**产品统一称为 **GameWeare**；仓库是 AI 游戏创作与游玩平台。`apps/web` 是玩家与创作者使用的前端，`apps/api-java` 是 Spring Boot 后端 API，`apps/agent-sandbox-runtime` 是每次生成任务使用的隔离运行时。Docker Compose 的项目标识暂保留 `gameweare-mvp`，以继续使用现有 MySQL、Redis、RabbitMQ 和 MinIO 数据卷；它不是产品名称。

## 目录与架构

- `apps/web`：React + Vite 前端。
- `apps/api-java`：Java 17 + Spring Boot 4 后端。按 `auth`、`billing`、`catalog`、`play`、`storage`、`create`、`maintenance`、`profile` 业务模块组织。
- `archive/python-api`：原 FastAPI 后端完整归档，仅供对照与迁移，不参与当前启动。
- `archive/frontend-original-main.tsx`：早期前端入口备份，不参与当前构建。
- `apps/api-java/src/main/resources/db/migration`：MySQL Flyway 版本化表结构。
- `docker-compose.yml`：MySQL、Redis、RabbitMQ、MinIO 与应用服务。
- `docker-compose.prod.yml`：生产覆盖配置，要求显式密钥与 AI 域名白名单。
- `docker-compose.multi-instance.yml`：双 API 实例的并发验收环境。

MySQL 是用户、游戏、任务与模型用量的事务数据源；MinIO 保存封面和游戏 HTML 对象，并非关系型数据库。Redis 用于登录限流与短期会话缓存。RabbitMQ 处理异步生成任务。任务和 Outbox 在同一 MySQL 事务中创建，投递使用 publisher confirm 与 mandatory return；Worker 使用租约和幂等状态更新。新建生成任务不检查本地虚拟 Token 余额，由模型服务商 API 判断额度，后端记录服务商返回的实际用量。历史本地余额账本保留以便审计。

## 本地运行

需要 JDK 17、Maven、Node.js、Docker Desktop。先启动依赖：

```powershell
docker compose up -d mysql rabbitmq redis minio
```

默认宿主机端口是 MySQL `3307`、RabbitMQ `5673`（管理台 `15673`）、Redis `6380`、MinIO `9000/9001`；容器内部仍使用标准端口。若端口冲突，可通过 `MYSQL_HOST_PORT`、`RABBITMQ_HOST_PORT`、`RABBITMQ_CONSOLE_PORT`、`REDIS_HOST_PORT` 环境变量覆盖。

在 PowerShell 中配置本地后端环境并运行：

```powershell
$env:MYSQL_URL='jdbc:mysql://localhost:3307/gameweare?useUnicode=true&characterEncoding=utf8&serverTimezone=UTC'
$env:MYSQL_USER='gameweare'
$env:MYSQL_PASSWORD='gameweare'
$env:RABBITMQ_HOST='localhost'
$env:RABBITMQ_PORT='5673'
$env:REDIS_PORT='6380'
$env:AI_CONFIG_SECRET='replace-with-a-random-secret-at-least-32-chars'
cd apps/api-java
mvn test
mvn spring-boot:run
```

新终端运行前端：

```powershell
cd apps/web
npm ci
npm run dev
```

前端地址为 `http://localhost:1314`，后端健康检查为 `http://localhost:8080/actuator/health`。首次启动会执行 Flyway 迁移。生成游戏前，在创建页配置支持 OpenAI Responses API 的 HTTPS 提供商与密钥。开发环境的 Docker Compose 默认密码只适用于本机；公开部署前通过环境变量更换数据库、消息队列、MinIO 凭证和 `AI_CONFIG_SECRET`。

管理员工作台位于 `http://localhost:1314/maintenance`，展示任务、失败运行、游戏、资产、审核记录和 Agent 用量。只有数据库中 `role=admin` 或 `role=maintainer` 的已登录账号能访问；前端入口会随角色显示，后端 `/maintenance/**` 仍会独立验证角色。新环境应由数据库管理员通过受控流程为指定账号赋权，普通注册账号默认没有管理权限。

完整容器启动命令是 `docker compose up -d --build`。Java 和前端构建镜像默认使用可访问的 Public ECR，Java 运行镜像使用 Microsoft Container Registry；本机已完成完整容器构建和启动验证。

## 验证

```powershell
cd apps/api-java
mvn test
cd ../web
npm run build
```

本地 Mock LLM 端到端验证：

```powershell
$env:LLM_ALLOW_PRIVATE_ENDPOINTS='true'
docker compose --profile test up -d --build
./scripts/e2e-verify.ps1
Remove-Item Env:LLM_ALLOW_PRIVATE_ENDPOINTS
```

`LLM_ALLOW_PRIVATE_ENDPOINTS` 仅可在隔离的本地测试环境开启。Google 登录另需设置 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI`，并在 Google 控制台登记回调地址。

外部 Agent 目前只负责交付单文件 HTML 游戏。后端提供 `POST /create/artifacts/validate` 返回语法诊断，再由 `POST /create/artifacts` 接收并保存为草稿；这条路径不调用 AI，也不预扣 Token。详见 [API 契约](docs/api.md)。校验只证明 HTML 包装与内联 JavaScript 可以解析，不能代替浏览器运行测试或人工内容审核。外部产物默认待审核，暂不能直接公开发布。

生产部署的凭证和 AI 网络出口配置见 [生产安全说明](docs/production-security.md)。CI 定义在 [.github/workflows/ci.yml](.github/workflows/ci.yml)，执行 Java 17 单测与打包、前端构建、Flyway 和草稿接收烟测。双实例并发验收可运行：

```powershell
docker compose -f docker-compose.yml -f docker-compose.multi-instance.yml --profile test up -d --build mysql redis rabbitmq minio mock-llm api api-replica
./scripts/multi-instance-verify.ps1
```

已在 MySQL 8.4、RabbitMQ 4、Redis 7、MinIO 本地容器上验证注册、登录会话、退出、游戏列表，以及创建任务失败后的 Token 退回和幂等键复用。`scripts/e2e-verify.ps1` 配合 `--profile test` 的 Mock LLM 覆盖 chat、plan、decentralized 生成、发布、试玩与账本；真实 AI 服务及 Google OAuth 仍需使用自己的凭证联调。

## AgentScope Java 引擎

本机没有 Kubernetes context。可运行 `./scripts/start-local-agentscope.ps1 -Mock` 启动本地 Docker 沙箱环境，再执行 `./scripts/e2e-verify.ps1 -Engine agentscope -Filesystem docker -UseExistingApi -MockBaseUrl http://127.0.0.1:8090`。每个创建任务使用 AgentScope 官方 `DockerFilesystemSpec` 创建独立、无网络的容器；Windows Docker CLI 的 shell 参数兼容处理位于 `WindowsDockerSandboxClient`。本机已通过 21 项 AgentScope 端到端检查，覆盖生成、规划审批、三个候选子智能体、发布、浏览器试玩和 Token 账本。启动脚本把本地密钥和构建产物保存在 Git 忽略的 `.runtime/` 中；首次启动会在 Git 忽略的 `.env` 中固定本地 MinIO 镜像 digest。

真实模型可不带 `-Mock` 启动，并在“创建”页保存自己的模型 URL、名称和 API Key。新任务通过 `AGENT_ENGINE=agentscope` 使用 AgentScope Java 2.0.3 Harness；默认 Compose 配置仍是 `legacy`，任务创建时固定引擎。生产 Kubernetes 路径仍需部署 `agent-sandbox` controller、`SandboxTemplate` / `SandboxWarmPool`、隔离 RuntimeClass，并配置 API Pod 的 Kubernetes 身份。Java 沙箱运行时可用 `docker build -t gameweare-agent-sandbox-runtime:local apps/agent-sandbox-runtime` 构建；部署模板位于 [infra/k8s/agent-sandbox.yaml.template](infra/k8s/agent-sandbox.yaml.template)。真实 DeepSeek 和 Kubernetes 集群验收状态见 [技术方案](docs/agentscope-agent-rewrite-plan.md)。

## 当前范围

Java 后端已覆盖核心注册登录、Token 计费、游戏目录与交互、图片上传、游玩、异步创建、项目管理，以及 plan 审批和 decentralized 方向选择。`react` 当前实现两次模型调用的规划/生成流程，尚未达到归档 Python 的 ReAct 工具循环；`refine` 也尚未有独立策略。详细状态与下一阶段工作见 [.plan/task.md](.plan/task.md)，归档中的 Python 代码可用于逐项对照。
# 生成券与高并发功能

签到、生成券秒杀、官方券创建、创作者关注和游戏热榜的接口与一致性设计见
[生成券、签到与社区功能](docs/voucher-seckill-and-community.md)。启用官方券任务前，在服务端配置
`OFFICIAL_LLM_BASE_URL`、`OFFICIAL_LLM_MODEL`、`OFFICIAL_LLM_API_KEY` 并重启 API；仅配置用户个人 AI Key 不会启用官方券任务。
