# Handoff Document 模板

agent 完成任务后，必须按此格式 SendMessage 给 lead，替代自由文本汇报。

## 格式

```
## Handoff: {agent-name} → lead

### 状态: DONE | BLOCKED | NEEDS_DECISION

### 摘要
{一句话概述完成了什么}

### 关键产出
- 文件变更: X files (+Y/-Z lines)
- 测试: X passed, Y failed

### 未解决项（如有）
- {具体问题描述}

### 建议下一步
{建议 lead 做什么}
```

## 状态说明

| 状态 | 含义 | lead 动作 |
|------|------|----------|
| DONE | 任务全部完成 | 推进到下一阶段 |
| BLOCKED | 遇到阻塞无法继续 | 展示未解决项给用户 |
| NEEDS_DECISION | 有选项需要用户决策 | AskUserQuestion 转发 |
