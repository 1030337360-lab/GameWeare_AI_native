---
name: fullstack-team
description: 全栈开发团队编排，先完成后端 API 再开发前端对接，共享 .plan/features.json。当用户说 "/fullstack-team" 时触发。支持后端（Java/Go/Node.js/Python）+ 前端（React/Vue3/Vue2）全栈场景。
---

# Fullstack Team - 全栈开发团队编排

Lead 亲自主导后端方案预研 + 前端设计系统生成、任务分解和计划写入，再通过 Agent Team 协调开发，实现"后端 API → 前端对接"的全栈流水线。

**与 backend-team / frontend-team 的核心区别**：两者合并为统一流水线，共享一个 .plan/features.json。.plan/task.md 中通过 `domain` 列区分 backend/frontend 任务，开发阶段先完成后端再完成前端，避免 mock 和联调问题。

## 团队架构

| 角色 | Agent 名称 | 类型 | spawn 模式 | 职责 |
|------|-----------|------|-----------|------|
| 团队负责人 | lead（自身） | - | - | Research & Reuse、后端方案预研、前端设计系统、任务分解、计划写入、全量验证、编排调度、用户沟通、决策 |
| 开发者 | developer | general-purpose | bypassPermissions | TDD 循环开发（先后端任务，再前端任务） |
| 打磨者 | polisher | general-purpose | bypassPermissions | 后端代码打磨 + 前端 UI/UX 打磨 |
| 构建修复者 | build-fixer | build-error-resolver（项目 agent） | - | 验证失败时自动修复 build/lint/type 错误 |
| 方案审查者 | plan-reviewer | code-architect（项目 agent） | - | 零上下文审查 .plan/task.md，挑战方案完整性和合理性 |
| 审查者 | reviewer | code-reviewer（项目 agent） | - | 上线前正式 CR，有完整代码上下文 |
| 盲审者 | blind-reviewer | code-reviewer（项目 agent） | - | 零上下文盲审，仅依据 PR 描述 + diff |
| 安全审查者 | security-reviewer | security-reviewer（项目 agent） | - | 安全审查，聚焦漏洞检测（条件触发） |

**设计说明**：
- lead 亲自执行方案预研 + 设计系统 + `/plan-init` + `/plan-write`：全栈方案的前后端协调是核心决策，lead 直接与用户交互，避免上下文丢失
- developer 按 domain 分两轮执行：先后端再前端，确保前端可以直接调用已实现的后端 API
- polisher 合并后端打磨 + 前端 UI/UX 检查：都是后处理，顺序执行
- reviewer / blind-reviewer / plan-reviewer 使用项目级 agent 定义（`agents/` 目录），不依赖外部 plugin

## 用户交互机制

| 阶段 | 交互方式 |
|------|---------|
| 阶段 0-2（lead 自己执行） | lead 直接用 AskUserQuestion 与用户交互，无需转发 |
| 阶段 1.5（plan-reviewer 执行） | plan-reviewer SendMessage 给 lead → lead 用 AskUserQuestion 展示审查结果 → 采纳的修改更新到 .plan/task.md |
| 阶段 3-4（teammate 执行） | teammate SendMessage 给 lead → lead 用 AskUserQuestion 询问用户 → lead SendMessage 转发答案 |
| 阶段 5（CR reviewer 执行） | reviewer SendMessage 给 lead → lead 汇总后用 AskUserQuestion 展示报告 |

**teammate 交互区分标准**：
- 关键决策（技术选型、架构方向、设计方向）：必须 SendMessage 给 lead 请求用户决策
- 非关键门控（代码探索确认、理解确认等）：teammate 自主判断，跳过门控继续执行

## 核心协议

**通用验证原则：** 每次检查/验收时，逐项确认每个方法/功能是否真正完整实现，而非仅写了兜底/stub/placeholder。除非用户明确声明"先留口子，后续开发"，才允许只写兜底方案。

### 阶段 0: 初始化 + 跳入点判断 + 语言/框架检测

**lead 操作：**

1. 确认用户的需求描述（文字、MD 文件路径、飞书/语雀链接等），记录完整的原始输入
2. 如涉及参考其他项目代码，确认参考项目路径并记录
3. **后端语言检测**：检查项目根目录的构建文件

| 检测条件 | 判定语言 |
|----------|----------|
| `pom.xml` 或 `build.gradle` 存在 | Java |
| `go.mod` 存在 | Go |
| `package.json` 含后端框架（express/koa/nestjs/fastify） | Node.js |
| `requirements.txt` 或 `pyproject.toml` 或 `setup.py` 存在 | Python |
| 无法自动判定 | AskUserQuestion 询问用户 |

4. **前端框架检测**：检查项目的 `package.json`、配置文件

| 检测条件 | 判定框架 |
|----------|----------|
| `package.json` 含 `react` 依赖 | React |
| `package.json` 含 `vue` 依赖且版本 `^3.x` 或 `>=3` | Vue3 |
| `package.json` 含 `vue` 依赖且版本 `^2.x` 或 `<3` | Vue2 |
| `next.config.*` 存在 | React (Next.js) |
| `vite.config.*` 含 `@vitejs/plugin-vue` | Vue3 |
| `vue.config.js` 存在 | Vue2 |
| 无法自动判定 | AskUserQuestion 询问用户 |

5. 记录两个检测结果（后端语言 + 前端框架），后续阶段分别使用
6. 检查现有文件状态，确定跳入点：

| 文件状态 | 跳入阶段 |
|----------|----------|
| 无 `.plan/task.md`、无 `.plan/features.json` | 阶段 1（完整流程） |
| 有 `.plan/task.md`（无 JSON 任务列表）、无 `.plan/features.json` | 阶段 2（plan-init 标准模式 + plan-write） |
| 有 `.plan/task.md`（含 JSON 任务列表）、无 `.plan/features.json` | 阶段 2b（仅 plan-write） |
| 有 `.plan/features.json`、有 backend 未完成任务 | 阶段 3a（后端开发） |
| 有 `.plan/features.json`、backend 全完成、有 frontend 未完成任务 | 阶段 3c（前端开发） |
| 有 `.plan/features.json`、所有 `passes: true`、dev log 中无 `[Verification-Done]` 标记 | 阶段 3.5（全量验证） |
| 有 `.plan/features.json`、所有 `passes: true`、dev log 中有 `[Verification-Done]` 标记、无 `[Polisher-Done]` 标记 | 阶段 4（仅优化） |
| 有 `.plan/features.json`、所有 `passes: true`、dev log 中有 `[Polisher-Done]` 标记 | 阶段 5（CR） |

7. 根据跳入点：
   - 若进入阶段 1 或 2：lead 直接执行，无需创建团队（团队在阶段 3 才需要）
   - 若进入阶段 3、4 或 5：创建团队，spawn 对应 agent

---

### 阶段 1: 方案预研（合并后端预研 + 前端设计系统）

**lead 操作：**

**1a. Research & Reuse（5 分钟速查）**

在进入方案预研前，先搜索现有实现，避免重复造轮子：

- 如有参考项目：探索参考项目相关代码，提取可复用的模式和工具函数
- WebSearch 搜索是否有成熟的库/工具可以直接使用
- 检查项目现有代码库中是否已有类似实现可复用
- 将发现记录到 .plan/task.md 的 references 字段

**1b. 后端方案预研 + 任务分解**

1. 调用 `Skill("plan-init")` 执行后端方案预研和任务分解（plan-init 会根据输入清晰度自动选择深度模式或标准模式）
2. 将用户的完整原始输入和 Research 阶段的发现作为上下文传入
3. 如有参考项目：
   - 先探索参考项目的相关代码流程，理解其实现模式
   - 将参考项目的关键文件路径写入 .plan/task.md 任务的 references 字段
   - 在任务描述中说明与参考项目的差异点
4. skill 内的所有门控由 lead 直接与用户交互完成
5. 确认 `.plan/task.md` 已生成，含完整 `## 任务列表` JSON

**1c. 前端设计系统生成（集成 ui-ux-pro-max + frontend-design）**

1. 从用户需求中提取关键词（产品类型、行业、风格偏好）
2. 调用 ui-ux-pro-max 的 search.py 生成设计系统：

```bash
python3 skills/ui-ux-pro-max/scripts/search.py "<产品类型> <行业> <风格关键词>" --design-system -p "<项目名>"
```

3. 获取推荐的设计系统：样式、调色板、字体搭配、效果、反模式
4. 运用 frontend-design 的设计思考框架：
   - **Purpose**：界面解决什么问题？谁在使用？
   - **Tone**：选择明确的美学方向
   - **Constraints**：技术约束（检测到的框架、性能、无障碍）
   - **Differentiation**：什么让这个界面令人难忘？
5. 如用户有特定偏好，用 AskUserQuestion 确认或调整设计系统

**1d. 生成统一 .plan/task.md（含 domain 列）+ .plan/pr-description.md**

1. 综合 1b 和 1c 的结果，生成统一的 `.plan/task.md`：

```markdown
## 设计系统

### 调色板
{来自 ui-ux-pro-max 推荐}

### 字体
{来自 ui-ux-pro-max 推荐}

### 风格
{来自 ui-ux-pro-max 推荐 + frontend-design 美学方向}

## 技术方案

### 后端
- 语言/框架：{检测到的后端语言}
- 整体思路：{后端方案概述}

### 前端
- 框架：{检测到的前端框架}
- 整体思路：{UI 方案概述：页面结构、组件拆分、状态管理策略}

### 任务列表
| # | 任务 | domain | category | dependsOn | complexity |
|---|------|--------|----------|-----------|------------|
| 1 | 后端项目配置 | backend | config | - | S |
| 2 | 用户 API 实现 | backend | feature | 1 | M |
| 3 | 前端项目配置 + 设计系统基础设施 | frontend | config | - | S |
| 4 | 公共组件（Button/Input/Card等） | frontend | core | 3 | M |
| 5 | 用户列表页面 | frontend | feature | 4 | L |
```

**关键规则**：
- 后端任务序号排在前面，前端任务序号排在后面
- 每个任务 JSON 中必须包含 `domain` 字段（`backend` 或 `frontend`）
- 后端 API 任务需包含 `apiContracts` 字段，定义前端会用到的接口契约
- **dependsOn 只设编译级依赖**：前端任务不 dependsOn 后端任务（不同 domain，通过 apiContracts 约定接口即可并行开发）；前端任务间的 dependsOn 仅用于同 domain 内的编译依赖（如页面组件依赖公共组件）
- 前端 feature 任务通过 `implementationGuide.keyInterfaces` 引用对应后端任务 ID 的 apiContracts，无需 dependsOn

2. 生成 `.plan/pr-description.md`：

```markdown
## PR 标题
{一句话概括变更}

## 变更动机
{为什么要做这个改动，业务背景}

## 方案概述
{技术方案的核心思路，不含实现细节}

## 后端方案
{后端技术栈和核心设计}

## 前端设计方向
{设计系统的核心选择：风格、调色板、字体}

## 预期改动范围
{涉及的模块/文件类型，粗粒度}
```

来源：从 .plan/task.md 提取，**不含具体文件路径和代码细节**。

3. 确认 `.plan/task.md` 和 `.plan/pr-description.md` 已生成 → 进入阶段 1.5

---

### 阶段 1.5: 方案对抗审查（plan-reviewer）

**触发条件**（复杂度分层）：

| 任务分布 | 是否执行 |
|---------|---------|
| 全部 trivial/small，且任务数 ≤ 3 | 跳过，直接进入阶段 2 |
| 含 medium，或任务数 4-6 | 执行 |
| 含 large，或任务数 > 6 | 执行 |

**lead 操作：**

1. 读取 .plan/task.md 内容，统计任务数量和 complexity 分布
2. spawn plan-reviewer（`subagent_type: code-architect`（项目 agent）, `team_name: fullstack-team`），发送指令：

```
你是方案审查者，负责用独立视角挑战全栈技术方案的完整性和合理性。

## 技术方案
{.plan/task.md 完整内容}

请从以下维度审查，只报告你认为**确实有问题**的点（没问题的不用列）：

1. **遗漏检查**：任务列表是否遗漏了必要的步骤？（如：改了接口没改调用方、加了功能没加测试、后端有 API 但前端没对接）
2. **前后端一致性**：后端 API 设计与前端页面需求是否匹配？是否有前端需要但后端未提供的接口？
3. **依赖顺序**：dependsOn 是否只包含编译级依赖？前后端不同 domain 间是否避免了不必要的 dependsOn？share/common 包的依赖是否正确设置？
4. **任务粒度**：是否有任务过大需要拆分？或过小可以合并？
5. **技术决策盲点**：已确定的技术选型是否有明显更优的替代方案未被考虑？
6. **验收标准可执行性**：每个任务的验收标准是否具体到可直接验证？
7. **设计系统一致性**：设计系统的选择是否与目标产品匹配？

输出格式：
- 每个问题：[维度] 问题描述 → 建议改进
- 如果方案没有明显问题，直接说"方案审查通过，无需调整"

完成后 SendMessage 给 lead。
```

3. **lead 处理审查结果：**

| 审查结果 | lead 处理 |
|----------|----------|
| "审查通过" | 直接进入阶段 2 |
| 有具体问题 | AskUserQuestion 展示问题清单，询问是否采纳 → 采纳的修改更新到 task.md → 进入阶段 2 |

4. shutdown plan-reviewer → 进入阶段 2

---

### 阶段 2: 计划写入（lead 自己执行）

**lead 操作：**

跳过条件：已存在 `.plan/features.json` 时跳过，直接进入阶段 3。

1. 调用 `Skill("plan-write")` 将计划写入项目文件
2. skill 内的门控处理：
   - 文件冲突（.plan/features.json 已存在）：选择"覆盖"
3. 确认 `.plan/features.json` 和 `.plan/dev-*.log` 存在 → 进入阶段 3

**优势**：lead 在阶段 1 亲历了后端预研和前端设计全过程，plan-write 阶段无需重复询问用户。

---

### 阶段 3: 任务开发（developer，分两轮）

**lead 操作：**
创建团队（如未创建），spawn developer（`subagent_type: general-purpose`, `mode: bypassPermissions`, `team_name: fullstack-team`），发送指令（详见 `references/developer-prompt.md`）：

```
请分两轮循环执行 /plan-next：先完成所有后端任务，再完成所有前端任务。

后端语言：{检测到的后端语言}
前端框架：{检测到的前端框架}
设计系统摘要：{.plan/task.md 中设计系统部分的关键信息}

第一轮：后端任务（domain=backend）
1. 读取 .plan/features.json，执行所有 domain=backend 且 passes: false 的任务
2. 按 TDD 流程完成
3. 每完成一个任务通知 lead 进度
4. 后端任务全部完成后通知 lead："后端任务全部完成，等待后端验证"
5. 等待 lead 验证通过的指令

第二轮：前端任务（domain=frontend）
6. 收到 lead 继续指令后，执行所有 domain=frontend 且 passes: false 的任务
7. 前端调用后端 API 时使用已实现的真实接口，不用 mock
8. 前端任务全部完成后通知 lead："前端任务全部完成"

注意事项：
- TDD 流程内的常规门控：自主跳过
- 关键技术决策：SendMessage 给 lead
- .plan/features.json 在此阶段只有你一个 agent 读写，无并发问题

卡住策略：
- 同一任务内测试连续失败 3 次：SendMessage 给 lead
- 代码结构不匹配：SendMessage 给 lead
- 环境缺失：SendMessage 给 lead
- 不要在失败后无限重试，尝试 2 种不同思路后仍失败即上报
```

**3a. 后端任务开发**

developer 执行所有 `domain=backend` 的任务。

**3b. 后端验证**

developer 通知后端任务完成后，lead 执行后端验证：

| 验证项 | Java | Go | Node.js | Python |
|--------|------|----|---------|--------|
| Build | `mvn compile` | `go build ./...` | `npm run build` | - |
| Lint | checkstyle/spotbugs | `go vet ./...` | `npm run lint` | `ruff check .` |
| Test | `mvn test` | `go test ./...` | `npm test` | `pytest` |
| API Verify | 调用 `Skill("backend-test")`（仅当项目含 HTTP 服务时） |

处理结果：

| 结论 | lead 处理 |
|------|----------|
| 通过 | SendMessage 给 developer 继续前端任务 |
| Build/Lint 失败 | spawn build-fixer 自动修复 → 重新验证 → 仍失败则 AskUserQuestion |
| Test 失败 | AskUserQuestion 展示失败项 |

**3c. 前端任务开发**

lead 通知 developer 继续，developer 执行所有 `domain=frontend` 的任务。

**3d. 前端验证**

developer 通知前端任务完成后，lead 执行前端验证：

| 验证项 | 命令 | 说明 |
|--------|------|------|
| Build | `npm run build` 或 `yarn build` 或 `pnpm build` | 编译无错误 |
| Lint | `npm run lint` 或项目配置的 lint 命令 | ESLint 无 error |
| Type Check | `npx tsc --noEmit`（TS 项目）或 `npx vue-tsc --noEmit`（Vue3 + TS） | 类型检查通过 |
| Test | `npm test` 或 `npx vitest run` 或 `npx jest` | 测试全部通过 |
| E2E | 调用 `Skill("frontend-test")` | 页面可访问、无控制台错误 |

处理结果同 3b。

- 全部 `passes: true` 且两轮验证通过 → shutdown developer → 进入阶段 3.5

---

### 阶段 3.5: 全量验证（lead 自己执行）

**触发条件**：developer 完成所有任务且两轮验证通过后、进入 polisher 前。

**lead 操作：**

1. **自动检测项目构建工具**，然后执行全量验证：

**后端构建工具检测**：
| 检测条件 | 语言 | Build 命令 | Lint 命令 | Test 命令 |
|----------|------|-----------|----------|----------|
| `pom.xml` | Java | `mvn compile` | checkstyle/spotbugs | `mvn test` |
| `build.gradle` | Java | `gradle build -x test` | checkstyle/spotbugs | `gradle test` |
| `go.mod` | Go | `go build ./...` | `go vet ./...` | `go test ./...` |
| `pyproject.toml` / `requirements.txt` | Python | - | `ruff check .` | `pytest` |

**前端构建工具检测**：
| 检测条件 | 构建命令 | Lint 命令 | Test 命令 |
|----------|---------|----------|----------|
| `package.json` 有 build script | `npm run build` | `npm run lint` | `npm test` |
| `vite.config.*` 存在 | `npx vite build` | `npm run lint` | `npm test` |
| `next.config.*` 存在 | `npx next build` | `npm run lint` | `npm test` |

优先使用 `package.json` 中 scripts 定义的命令（如 `build`、`lint`、`test`），比默认命令更准确。

**验证项**（按检测到的工具执行）：
| 验证项 | 说明 |
|--------|------|
| Build | 后端 + 前端编译构建 |
| Lint | 代码静态检查 |
| Test | 运行测试套件 |
| Coverage | 测试覆盖率（目标 80%） |
| Security | 硬编码扫描（`grep -rn` 检查 API key、password、secret 等） |
| Diff | `git diff --stat`（检查是否有意外修改的文件） |
| API 验证 | 调用 `Skill("backend-test")`（仅当项目含 HTTP 服务时） |

2. 输出验证报告：

```
全栈验证报告
============

--- 后端 ---
Build:    [PASS/FAIL]
Lint:     [PASS/FAIL] (X warnings)
Test:     [PASS/FAIL] (X/Y passed)
Coverage: [X%] (目标 80%, 达标/不达标)
Security: [PASS/FAIL] (X issues)
API:      [PASS/FAIL]

--- 前端 ---
Build:      [PASS/FAIL]
Lint:       [PASS/FAIL] (X warnings)
Type Check: [PASS/FAIL] (X errors)
Test:       [PASS/FAIL] (X/Y passed)
Coverage:   [X%] (目标 80%, 达标/不达标)
Security:   [PASS/FAIL] (X issues)
E2E:        [PASS/FAIL]

--- 通用 ---
Diff:     [X files changed, +Y/-Z lines]

结论: [通过/不通过]
```

注：Coverage 不达标不阻断流程，但在报告中标注并提醒。

3. 将验证报告追加到 dev log，并写入 `[Verification-Done]` 标记

4. 处理结果：

| 结论 | lead 处理 |
|------|----------|
| 通过 | 进入阶段 4 |
| 不通过（Build/Lint/Type Check 失败） | spawn build-error-resolver（`subagent_type: build-error-resolver`（项目 agent））自动修复 → 重新验证 → 仍失败则 AskUserQuestion |
| 不通过（Test 失败） | AskUserQuestion 展示失败项（测试失败需人工判断） |
| 不通过（Security 失败） | AskUserQuestion 展示失败项（安全问题需人工确认） |

---

### 阶段 4: 代码优化（polisher）

**lead 操作：**
spawn polisher（`subagent_type: general-purpose`, `mode: bypassPermissions`, `team_name: fullstack-team`），发送指令（详见 `references/polisher-prompt.md`）：

```
请依次执行代码优化（后端 + 前端）：

前端框架：{检测到的框架}

第一步：UI/UX Pre-Delivery Checklist（仅前端文件）
- 逐项检查前端文件的视觉质量、交互、布局、无障碍
- 发现问题直接修复
- SendMessage 给 lead 报告检查结果和修复项

第二步：优先调用 Skill("simplify")，若 simplify skill 不可用则回退调用 Skill("code-simplifier")
- 先用 git diff 确定本次修改的文件范围（后端+前端），将文件列表作为优化目标
- 全部完成后按 Handoff 格式（详见 references/handoff-template.md）SendMessage 给 lead

第三步：调用 Skill("code-fixer")
- 对代码进行规范修复（基于 git diff）
- 需确认的改动（CONFIRM 类）：SendMessage 给 lead 说明改动列表，等待回复
- 完成后在 dev log 中写入 `[Polisher-Done]` 标记
- 按 Handoff 格式（详见 references/handoff-template.md）SendMessage 给 lead，报告优化全部完成
```

**lead 验证：**
- 收到 CONFIRM 类改动请求 → AskUserQuestion 询问用户 → SendMessage 转发答案
- 确认优化完成 → 标记任务完成 → shutdown polisher → 进入阶段 5

---

### 阶段 5: Code Review（reviewer + blind-reviewer + security-reviewer）

**lead 操作：**

1. 准备 CR 材料：
   - 执行 `git diff main...HEAD`（或合适的 base branch），保存 diff 内容
   - 读取 `.plan/pr-description.md`
   - **安全审查触发判断**：检查 diff 中是否包含安全相关关键词（`auth`、`login`、`password`、`token`、`secret`、`key`、`middleware`、`interceptor`、`filter`、`sql`、`query`、`exec`、`.env`、`config`、`cors`、`csp`、`cookie`、`localStorage`、`innerHTML`、`dangerouslySetInnerHTML`）

2. **CR 范围判断**（复杂度分层）：

   | 任务分布 | CR 范围 |
   |---------|--------|
   | 全部 trivial/small，且任务数 ≤ 3 | 仅 reviewer（跳过 blind-reviewer） |
   | 含 medium，或任务数 4-6 | reviewer + blind-reviewer |
   | 含 large，或任务数 > 6 | reviewer + blind-reviewer + security-reviewer（无论是否触发安全关键词） |

3. 并行 spawn reviewer（审查标准详见 `references/reviewer-prompt.md`）：
   - 简化模式：仅 spawn reviewer
   - 标准模式：spawn reviewer + blind-reviewer
   - 完整模式：spawn reviewer + blind-reviewer + security-reviewer
   - 标准/简化模式下若触发安全审查条件：额外 spawn security-reviewer

**reviewer（Production CR）：**
spawn（`subagent_type: code-reviewer`（项目 agent）, `team_name: fullstack-team`），发送指令：

```
你是 Production Code Reviewer，负责上线前的正式全栈代码审查。
后端语言：{检测到的后端语言}
前端框架：{检测到的前端框架}

请执行完整的代码审查：
1. 运行 git diff main...HEAD 获取本次所有变更
2. 对每个变更文件，读取完整文件理解上下文
3. 按以下维度审查：

   通用维度：
   - 安全漏洞（硬编码密钥、注入、XSS、未校验输入）
   - 逻辑错误（边界条件、空指针、并发问题）
   - 性能问题（N+1 查询、不必要的重渲染、大列表未虚拟化）
   - 代码质量（嵌套过深、职责不清、缺少错误处理）
   - 测试覆盖（关键路径是否有测试）

   后端专项：
   - 数据库操作：事务完整性、SQL 注入防护
   - API 设计：RESTful 规范、入参校验、错误码一致性
   - 并发安全：锁粒度、死锁风险

   前端专项（参考 code-review/frontend.md）：
   - 组件架构、状态管理、TypeScript 质量、样式、竞态

   前后端联调：
   - API 路径是否前后端一致
   - 请求/响应数据结构是否匹配
   - 错误码处理是否前后端约定一致

4. 只审查 diff 中变更的代码

置信度过滤：
- 只报告置信度 >80% 的问题
- 相似问题合并

严重等级：CRITICAL / HIGH / MEDIUM / LOW
输出格式：[严重等级] 问题标题 → 文件:行号 → 问题描述 → 修复建议
审查结束附加摘要表和结论（APPROVE/WARNING/BLOCK）

完成后 SendMessage 给 lead。
```

**blind-reviewer（Blind CR）：**
spawn（`subagent_type: code-reviewer`（项目 agent）, `team_name: fullstack-team`），发送指令：

```
你是 Blind Code Reviewer，执行零上下文盲审。
你只有以下信息，禁止读取任何项目文件或探索代码库：

## PR 描述
{.plan/pr-description.md 内容}

## Code Diff
{git diff 输出}

请仅基于以上信息审查：
1. diff 中是否存在明显 bug、逻辑错误
2. 是否有安全风险（硬编码密钥、XSS、敏感数据暴露）
3. 代码变更是否与 PR 描述一致
4. diff 中是否有可疑的模式（硬编码、TODO/FIXME、空实现）
5. 变更的合理性（改动量是否与目标匹配）
6. 前后端数据契约是否一致（API 路径、请求参数、响应结构）

置信度过滤：
- 只报告置信度 >80% 的问题
- 相似问题合并

严重等级：CRITICAL / HIGH / MEDIUM / LOW
输出格式：[严重等级] 问题标题 → 文件:行号 → 问题描述 → 修复建议
审查结束附加摘要表和结论（APPROVE/WARNING/BLOCK）

完成后 SendMessage 给 lead。
```

**security-reviewer（Security CR，仅在触发条件满足时 spawn）：**
spawn（`subagent_type: security-reviewer`（项目 agent）, `team_name: fullstack-team`），发送指令：

```
你是 Security Reviewer，负责从安全角度审查本次全栈代码变更。

请执行安全审查：
1. 运行 git diff main...HEAD 获取本次所有变更
2. 聚焦安全相关文件（认证、授权、输入处理、数据存储、配置）
3. 后端安全维度：凭证管理、输入校验、注入防护、认证授权、敏感数据、依赖安全
4. 前端安全维度：
   - XSS 防护（innerHTML、dangerouslySetInnerHTML、v-html）
   - 敏感数据暴露（localStorage 中存储 Token、前端代码暴露 API 密钥）
   - CSP 配置、CORS 配置
   - Cookie 安全属性（HttpOnly、Secure、SameSite）
5. 只审查 diff 中变更的代码

置信度过滤：
- 只报告置信度 >80% 的安全问题
- 已有框架级防护覆盖的问题可跳过
- 同类问题合并

严重等级：CRITICAL / HIGH / MEDIUM / LOW
输出格式：[严重等级] 问题标题 → 维度 → 文件:行号 → 问题描述 → 风险 → 修复建议
审查结束附加安全摘要表和结论（SECURE/WARNING/BLOCK）

完成后 SendMessage 给 lead。
```

3. **lead 汇总：**
   - 收集所有 reviewer 的报告（2 个或 3 个）
   - 合并去重，按严重等级排序（CRITICAL 优先）
   - 标注来源（Production / Blind / Security / 多方一致）
   - 多方一致的发现升级置信度标记（**高置信度**）
   - 汇总 verdict：取所有 reviewer 中最严格的结论（BLOCK > WARNING > APPROVE/SECURE）
   - 用 AskUserQuestion 展示汇总报告，询问用户处理决策
   - shutdown 所有 reviewer

---

### 阶段 6: 收尾

**lead 操作：**
1. 清理团队：`TeamDelete`
2. 向用户输出最终报告：

```markdown
## Fullstack Team 执行报告

### 执行概览
| 阶段 | 状态 | 执行者 |
|------|------|--------|
| 后端方案预研 | 完成 | lead |
| 前端设计系统 | 完成 | lead |
| 方案审查 | 完成/跳过 | plan-reviewer |
| 任务分解 | 完成 | lead |
| 计划写入 | 完成 | lead |
| 后端开发 | 完成 | developer |
| 后端验证 | 完成 | lead |
| 前端开发 | 完成 | developer |
| 前端验证 | 完成 | lead |
| 全量验证 | 完成 | lead |
| 代码优化 | 完成 | polisher |
| Code Review | 完成 | reviewer + blind-reviewer |

### 量化指标
| 指标 | 数值 |
|------|------|
| 后端语言 | {Java / Go / Node.js / Python} |
| 前端框架 | {React / Vue3 / Vue2} |
| 任务总数 | X（后端 Y + 前端 Z） |
| 变更文件数 | X |
| 新增/删除行数 | +X / -X |
| 验证结果 | PASS/FAIL |
| CR 结论 | APPROVE/WARNING/BLOCK |
| CR 发现 | CRITICAL:X HIGH:X MEDIUM:X LOW:X |

### 设计系统
- 风格：{选用的设计风格}
- 调色板：{主色/辅色}
- 字体：{标题字体 / 正文字体}

### 产出文件
- `.plan/task.md` - 全栈技术方案文档（含 domain 列）
- `.plan/pr-description.md` - PR 描述（阶段 1 生成）
- `.plan/features.json` - 任务状态（所有 passes: true）
- `.plan/dev-YYYY-MM-DD.log` - 开发日志
- 后端代码 + 前端组件/页面 + 测试文件

### 后续建议
- 运行 `/plan-archive` 归档本次开发
```

## 错误处理

| 错误类型 | 处理方式 |
|----------|----------|
| teammate 执行失败 | teammate SendMessage 通知 lead 错误详情 → lead 通知用户并请求决策 |
| agent 无响应/异常 | lead 重新 spawn 同名 agent，发送恢复指令 |
| 测试失败（plan-next） | developer 在 TDD 流程内自行处理；连续失败 3 次则上报 lead |
| 后端验证失败 | lead 用 build-fixer 自动修复或 AskUserQuestion 展示失败项 |
| 前端验证失败 | lead 用 build-fixer 自动修复或 AskUserQuestion 展示失败项 |
| 全量验证失败 | lead 用 AskUserQuestion 展示失败项，询问用户决策 |

中断恢复：重新执行 `/fullstack-team` 时，lead 根据文件状态自动判断跳入阶段（见阶段 0 的文件状态检查表）。
