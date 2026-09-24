# Gameweare / GameWeare AI Native

本仓库是 [1030337360-lab/GameWeare_AI_native](https://github.com/1030337360-lab/GameWeare_AI_native) 的本地项目，不是同名参考仓库 `charlie11sun-netizen/gameweare`。

## 目录与架构

- `apps/web`：React + Vite 前端。
- `apps/api-java`：Java 17 + Spring Boot 4 后端。按 `auth`、`billing`、`catalog`、`play`、`storage`、`create`、`maintenance`、`profile` 业务模块组织。
- `archive/python-api`：原 FastAPI 后端完整归档，仅供对照与迁移，不参与当前启动。
- `apps/api-java/src/main/resources/db/migration`：MySQL Flyway 版本化表结构。
- `docker-compose.yml`：MySQL、Redis、RabbitMQ、MinIO 与应用服务。

MySQL 是用户、游戏、任务、Token 余额与账本的事务数据源；MinIO 保存封面和游戏 HTML 对象，并非关系型数据库。Redis 用于登录限流与短期会话缓存。RabbitMQ 处理异步生成任务。任务和 Outbox 在同一 MySQL 事务中创建，投递使用 publisher confirm 与 mandatory return；Worker 使用租约和幂等状态更新。Token 通过账户行锁、预留、结算与退回维护余额和账本一致性。

## 本地运行

需要 JDK 17+、Maven、Node.js、Docker Desktop。先启动依赖：

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

完整容器启动命令是 `docker compose up -d --build`。Java 和前端构建镜像默认使用可访问的 Public ECR，Java 运行镜像使用 Microsoft Container Registry；本机已完成完整容器构建和启动验证。

## 验证

```powershell
cd apps/api-java
mvn test
cd ../web
npm run build
```

已在 MySQL 8.4、RabbitMQ 4、Redis 7、MinIO 本地容器上验证注册、登录会话、退出、游戏列表，以及创建任务失败后的 Token 退回和幂等键复用。当前创建 Worker 需要真实 AI 服务才能验证成功生成；请使用自己的测试密钥并核对使用量。

## 当前范围

Java 后端已覆盖核心注册登录、Token 计费、游戏目录与交互、上传、游玩、异步创建和项目管理。旧版 Python 的图片输入及 `react`、`plan`、`decentralized` 专用 Agent 编排还未迁移；Java API 会明确拒绝不支持的模式，前端只展示已接通的 chat 创建流程。归档中的 Python 代码仍可用于逐项迁移对照。
