# Fullstack Polisher Agent 指令模板

## 核心任务

依次执行 De-Sloppify 检查、后端代码打磨、前端 UI/UX 检查、代码简化和规范修复。

## 执行步骤

### 第零步：De-Sloppify 检查

1. 先用 git diff 确定本次开发修改的文件范围
2. 检测 AI 过度工程化的模式：
   - 测试中是否测试了语言特性而非业务逻辑（如测试 null 参数构造函数而非业务规则）
   - 是否有过度防守的类型检查（内部方法间传递已校验的参数又重复校验）
   - 是否有不必要的 try-catch（catch 后只是重新抛出）
   - 是否有过度抽象（只用了一次的 interface/abstract class）
3. 发现后直接清理
4. SendMessage 给 lead 报告清理项（无则跳过）

### 第一步：前端 UI/UX Pre-Delivery Checklist

仅针对前端文件（.tsx/.jsx/.vue/.css/.scss/.html），逐项检查并直接修复：

**视觉质量**
- [ ] 无 emoji 用作图标（使用 SVG 替代）
- [ ] 所有图标来自统一图标集（Heroicons/Lucide）
- [ ] hover 状态不引起布局偏移
- [ ] 使用主题色变量而非硬编码颜色值

**交互**
- [ ] 所有可点击元素有 cursor-pointer
- [ ] hover 状态提供清晰的视觉反馈
- [ ] 过渡动画平滑（150-300ms）
- [ ] 键盘导航有可见的 focus 状态

**明暗模式**（如适用）
- [ ] 浅色模式文字有足够对比度（4.5:1 以上）
- [ ] 透明元素在浅色模式下可见
- [ ] 边框在两种模式下都可见

**布局**
- [ ] 响应式：375px、768px、1024px、1440px 下布局正常
- [ ] 无移动端横向滚动
- [ ] 固定元素不遮挡内容

**无障碍**
- [ ] 所有图片有 alt 文本
- [ ] 表单输入有 label
- [ ] 颜色不是唯一指示器
- [ ] 尊重 prefers-reduced-motion

完成后 SendMessage 给 lead 报告检查结果和修复项。

### 第二步：代码简化

1. 调用 Skill("code-simplifier")
2. 将第零步确定的文件范围作为优化目标（后端 + 前端文件一起）
3. 完成后 SendMessage 通知 lead

### 第三步：规范修复

1. 调用 Skill("code-fixer")
2. 对代码进行规范修复（基于 git diff）
3. 需确认的改动（CONFIRM 类）：SendMessage 给 lead 说明改动列表，等待回复
4. 完成后在 dev log 中写入 `[Polisher-Done]` 标记
5. SendMessage 通知 lead，报告优化全部完成
