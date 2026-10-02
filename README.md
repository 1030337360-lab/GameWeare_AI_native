# GameWeare — AI 游戏创作与游玩平台

GameWeare 让用户描述游戏、选择生成模式、查看任务轨迹，随后发布并游玩单文件 HTML5 游戏。当前代码是 React 前端与 Spring Boot 模块化单体；Java AgentScope 引擎已经接入，默认创建引擎仍为 `legacy`。本仓库是 [GameWeare_AI_native](https://github.com/1030337360-lab/GameWeare_AI_native)，与曾用于参考的 `charlie11sun-netizen/yahaha` 不是同一个项目。

## 从哪里开始

| 文档 | 内容 |
| --- | --- |
| [整体架构](docs/architecture.md) | 模块、数据流、数据归属与部署边界 |
| [Java 后端实现](docs/backend.md) | 类与表的对应关系、事务、并发、缓存、券和生产安全 |
| [前后端契约](docs/frontend-api.md) | 页面到 API 的映射、请求示例、任务状态与试玩协议 |
| [Agent 实现](docs/agent.md) | 双引擎、五种模式、沙箱、记忆、校验、封面及真实环境缺口 |
| [迭代路线](docs/iteration-roadmap.md) | 已完成与待完成工作的先后顺序，不按日期排期 |

## 代码结构

| 路径 | 职责 |
| --- | --- |
| `apps/web` | React + Vite 玩家、创作者、管理员界面 |
| `apps/api-java` | Spring Boot API、MyBatis/JDBC 数据访问、任务 Worker、Flyway 迁移 |
| `apps/agent-sandbox-runtime` | AgentScope Kubernetes 沙箱的 Java HTTP 运行时 |
| `infra` | MySQL 初始化与 Kubernetes 沙箱模板 |
| `scripts` | 本地启动与端到端、并发、秒杀验收脚本 |
| `archive/python-api` | 旧版 Python 后端源码，仅供迁移对照，不参与运行 |

## 本地启动

安装 Docker Desktop 后，在仓库根目录运行：

```powershell
docker compose up -d --build
docker compose ps
```

前端：<http://localhost:1314>；API 健康检查：<http://localhost:8080/actuator/health>。MySQL、Redis、RabbitMQ、MinIO 分别由 Compose 启动。首次启动会执行 Flyway 迁移，并把后端内部的 Java 面试知识闯关注册为首页可玩的内置游戏；重复启动不会重复创建。开发配置中的默认密码只适用于本机。

仅修改 Java 后端时，可在仓库根目录执行 `docker compose build api`，再执行 `docker compose up -d --no-build api web`。API 镜像会从 `apps/api-java/pom.xml` 编译并打包 MyBatis；Compose 继续使用现有 MySQL、Redis、RabbitMQ、MinIO 数据卷。用 `docker compose ps` 检查容器状态，再访问上述健康检查和 `/games?sort=latest`。镜像构建使用 `-DskipTests`，提交前仍需单独运行 `mvn -f apps/api-java/pom.xml test`。

创建游戏前，可在“创作”页配置自己的模型地址、名称和 API Key。官方生成券还需服务端配置 `OFFICIAL_LLM_BASE_URL`、`OFFICIAL_LLM_MODEL`、`OFFICIAL_LLM_API_KEY`。新建生成任务的模型额度由服务商 API 判断，项目不以旧版本地 Token 余额拒绝任务。

如需验证 AgentScope 的本地 Docker 沙箱，可运行 `./scripts/start-local-agentscope.ps1 -Mock`，再运行 `./scripts/e2e-verify.ps1 -Engine agentscope -Filesystem docker -UseExistingApi -MockBaseUrl http://127.0.0.1:8090`。真实 Kubernetes 路径需要另行部署 controller、沙箱模板和隔离运行时，不能把本地 Docker 通过视作集群验收。

## 构建与验证

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
docker compose config --quiet
docker compose build api web
```

CI 在 [.github/workflows/ci.yml](.github/workflows/ci.yml) 中运行 Java 测试、前端构建、Compose 冒烟和多实例一致性验收。更多脚本和边界见各专题文档。生产部署使用 `docker-compose.prod.yml`、独立密钥和 HTTPS；它仍需要实际网络出口策略、备份恢复演练与真实模型验收。

**命名兼容：**产品统一称 **GameWeare**。本机 Compose 项目标识仍是 `gameweare-mvp`，用于继续挂载已有数据卷；它不是产品名称。不要仅为改名删除这些数据卷。
