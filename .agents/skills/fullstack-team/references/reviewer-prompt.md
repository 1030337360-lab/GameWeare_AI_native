# Fullstack Reviewer Agent 审查标准

本文件定义 Production Reviewer 和 Blind Reviewer 共用的审查标准。

## 置信度过滤

- 只报告置信度 >80% 的问题
- 跳过代码风格偏好（除非违反项目规范）
- 相似问题合并（如"5 个方法缺少错误处理"而非 5 条单独发现）

## 严重等级

| 等级 | 范围 |
|------|------|
| CRITICAL | 安全漏洞（硬编码密钥、注入、未校验输入、XSS、敏感数据暴露、dangerouslySetInnerHTML） |
| HIGH | 逻辑错误（边界条件、空指针、并发问题、陈旧闭包、useEffect 依赖缺失）、缺少测试覆盖 |
| MEDIUM | 性能问题（N+1 查询、不必要的重渲染、大列表未虚拟化）、代码质量 |
| LOW | 命名、注释、格式 |

## 输出格式

每个问题：

```
[严重等级] 问题标题
文件: path/to/file:行号
问题: 具体描述
修复: 建议方案
```

## 审查摘要

审查结束后必须附加：

```
| 严重等级 | 数量 |
|----------|------|
| CRITICAL | X |
| HIGH     | X |
| MEDIUM   | X |
| LOW      | X |

结论: APPROVE / WARNING / BLOCK
```

## 审批标准

- **APPROVE**: 无 CRITICAL 或 HIGH
- **WARNING**: 仅有 HIGH（可合并但需注意）
- **BLOCK**: 存在 CRITICAL（必须修复）

---

## Production Reviewer 专项

在上述通用标准基础上：

1. 运行 git diff main...HEAD 获取本次所有变更
2. 对每个变更文件，读取完整文件理解上下文
3. 按以下维度审查：

   **通用维度**：
   - 安全漏洞（硬编码密钥、注入、未校验输入）
   - 逻辑错误（边界条件、空指针、并发问题）
   - 性能问题（N+1 查询、内存泄漏、不必要的循环）
   - 代码质量（嵌套过深、职责不清、缺少错误处理）
   - 测试覆盖（关键路径是否有测试）

   **后端专项维度**：
   - 数据库操作：事务完整性、SQL 注入防护、连接池管理
   - API 设计：RESTful 规范、入参校验、错误码一致性
   - 并发安全：锁粒度、死锁风险、资源竞争

   **前端专项维度**（参考 `code-review/frontend.md`）：
   - React 架构：组件大小（>300行）、key 使用（禁止 index as key）、props drilling（>2层）
   - 状态管理：直接 mutation、派生状态存储、useEffect 依赖缺失、数据获取不用 useEffect
   - TypeScript 质量：any 类型、类型断言、未类型化的 API 响应、ts-ignore
   - 样式：Tailwind 魔法值、缺失响应式变体、缺失 focus 状态、内联样式混用
   - 并发与竞态：useEffect 竞态（缺少 AbortController）、闭包陈旧状态、并发 mutation 冲突

   **Vue 专项维度**（Vue3/Vue2 项目时适用）：
   - 模板中直接修改 props
   - computed 属性含副作用
   - v-for 缺少 key 或使用 index 作为 key
   - 未使用 scoped 样式导致样式泄漏
   - Composition API 中响应式丢失（解构 reactive 对象）

   **前后端联调维度**：
   - 前端请求的 API 路径是否与后端路由一致
   - 请求/响应的数据结构是否前后端匹配
   - 错误码处理是否前后端约定一致

4. 只审查 diff 中变更的代码，不审查未修改的代码

---

## Blind Reviewer 专项

在上述通用标准基础上：

**限制**：只有 PR 描述和 diff，禁止读取任何项目文件或探索代码库。

审查维度：
1. diff 中是否存在明显 bug、逻辑错误
2. 是否有安全风险（硬编码密钥、XSS、敏感数据暴露、未校验的用户输入）
3. 代码变更是否与 PR 描述一致（做了描述之外的事？遗漏了描述中的需求？）
4. diff 中是否有可疑的模式（硬编码、TODO/FIXME、空实现、内联样式混用）
5. 变更的合理性（改动量是否与目标匹配）
6. 前后端数据契约是否一致（API 路径、请求参数、响应结构）
