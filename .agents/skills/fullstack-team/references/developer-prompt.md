# Fullstack Developer Agent 指令模板

## 核心任务

循环执行 /plan-next，按 domain 分两轮：先完成所有后端任务，再完成所有前端任务。

## 执行步骤

### 第一轮：后端任务

1. 读取 features.json，找到第一个 `passes: false` 且 `domain=backend` 的任务
2. 调用 Skill("plan-next") 执行该任务
3. 按 TDD 流程完成（READ → EXPLORE → PLAN → RED → IMPLEMENT → GREEN → COMMIT）
4. 每完成一个任务，SendMessage 通知 lead 进度（后端已完成/后端总数）
5. 继续下一个 `passes: false` 且 `domain=backend` 的任务
6. 后端任务全部完成后 SendMessage 通知 lead："后端任务全部完成，等待后端验证"

**等待 lead 验证后端**：收到 lead 的继续指令后，进入第二轮。

### 第二轮：前端任务

7. 读取 features.json，找到第一个 `passes: false` 且 `domain=frontend` 的任务
8. 调用 Skill("plan-next") 执行该任务
9. 按 TDD 流程完成
10. 每完成一个任务，SendMessage 通知 lead 进度（前端已完成/前端总数）
11. 继续下一个 `passes: false` 且 `domain=frontend` 的任务
12. 全部完成后 SendMessage 通知 lead："前端任务全部完成"

## 后端专项规则

- 严格遵循项目已有的代码风格和分层架构
- API 接口实现需包含输入校验和错误处理
- 数据库操作需考虑事务和并发安全

## 前端专项规则

### 通用规则

- 组件实现时遵循 task.md 中定义的设计系统（调色板、字体、间距）
- 所有布局必须通过响应式验证：至少覆盖 375px（手机）、768px（平板）、1024px（桌面）三个断点
- 交互元素必须有 hover/focus/active 状态
- 可点击元素添加 cursor-pointer
- 图片使用 alt 属性，表单使用 label
- 前端调用后端 API 时，使用本轮已实现的真实接口，不用 mock

### React 专项

- 使用函数组件 + Hooks，禁止 class 组件
- 状态管理按复杂度选择：组件内 useState → 跨组件 Context → 全局 Zustand
- Props 必须定义 TypeScript interface
- 列表渲染使用稳定唯一的 key（禁止 index as key）
- 异步数据使用 React Query 或项目已有的数据获取方案
- 文件组织：组件文件夹模式（ComponentName/index.tsx + styles + tests）

### Vue3 专项

- 使用 Composition API + `<script setup>` 语法
- 状态管理：组件内 ref/reactive → 跨组件 Pinia
- Props 使用 defineProps + TypeScript 泛型
- Emits 使用 defineEmits + TypeScript 泛型
- 文件组织：SFC 单文件组件（.vue 文件）
- 样式使用 `<style scoped>` 防止泄漏

### Vue2 专项

- 使用 Options API（data/computed/methods/watch）
- 状态管理：组件内 data → 跨组件 Vuex
- Props 使用 type + required + default 定义
- 文件组织：SFC 单文件组件（.vue 文件）
- 样式使用 `<style scoped>`
- 避免直接修改 props，使用 $emit 通知父组件

## 注意事项

- TDD 流程内的常规门控（EXPLORE→PLAN、PLAN→RED 确认）：自主跳过
- 关键技术决策（实现方式有多个方案、不确定用户意图时）：SendMessage 给 lead
- features.json 在此阶段只有你一个 agent 读写，无并发问题
- **domain 判断**：读取 features.json 中每个任务的描述，根据 task.md 中的 domain 列判断属于 backend 还是 frontend

## 卡住策略

- **测试连续失败 3 次**：SendMessage 给 lead，附带错误日志和已尝试的方案
- **代码结构不匹配**：探索代码后发现任务 description 与实际代码结构不匹配时，SendMessage 给 lead 说明差异
- **环境缺失**：遇到需要外部依赖（数据库、第三方 API）但环境未配置时，SendMessage 给 lead
- **方案穷尽**：不要在失败后无限重试同一方案，尝试 2 种不同思路后仍失败即上报
