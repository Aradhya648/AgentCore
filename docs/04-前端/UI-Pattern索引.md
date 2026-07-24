---
status: reference
code: apps/desktop/src/renderer/components/ui/
related:
  - .cursor/rules/color-tokens.mdc
  - docs/04-前端/前端UX设计.md
skip_if:
  - 只改业务逻辑不涉及组件层
---

# UI Pattern 索引

> **状态**：✅ 已落地（primitive 层 + lint 门禁）
>
> 配色与布局硬规则见 `.cursor/rules/color-tokens.mdc`、`desktop-layout.mdc`；产品 IA 见 [`前端UX设计.md`](前端UX设计.md)。

## 三层结构

| 层 | 位置 | 职责 |
|---|---|---|
| **L1 Token** | `packages/design-tokens/src/tokens.css` | OKLCH 语义色、动画、侧栏/身份色板（desktop/mobile 共用包） |
| **L2 Primitive** | `apps/desktop/src/renderer/components/ui/` | Button、Card、Badge 等可复用原子组件 |
| **L3 Pattern** | 组合 primitive 的产品级壳（见下表） | 裁决卡、状态条、列表行等 |

## L2 Primitive 一览

→ 见代码 `components/ui/index.ts`

| 组件 | 用途 |
|---|---|
| `Button` / `IconButton` | CTA、工具栏图标（sm h-7 / md h-8）；`Button` 含 `destructive` 实心变体；`IconButton` 含 `primary` / `destructive` tone |
| `Card` | 面板/卡片容器（`rounded-xl`） |
| `Badge` | 状态 chip、pill 计数 |
| `Input` / `Textarea` | 表单、内联编辑 |
| `SearchField` / `SearchTrigger` / `TitleBarSearchTrigger` | 页内筛选；侧栏全局假入口 / TitleBar 假入口（见下节） |
| `SectionLabel` | 分组小标题（工具箱、设置） |
| `DecisionCard` | 裁决类卡片外壳（primary / neutral 两态；warning 变体已废除） |
| `SurfaceRow` / `SurfaceRowButton` | 列表行 chrome（file / sidebar variant） |
| `PatternCardHeader` | 时间线卡片头栏（标签 + badge + 时间戳） |

Radix overlay（dialog / popover / tooltip 等）仍在 `components/ui/`，与 primitive 并列。

## L3 Pattern 映射

| Pattern | 典型场景 | 实现指针 |
|---|---|---|
| **DecisionCard** | ask_user / plan_review / approval / escalation | `DecisionCard` + `Button`；`CheckpointCard` / `PlanReviewCard` / `ApprovalPrompt` / `EscalationCard` |
| **StatusStrip** | 协作图状态条 | `StatusStrip.tsx`（`InlineTeamGraph` 消费） |
| **PatternCardHeader** | 后台任务卡头栏 | `BackgroundTaskCard.tsx` |
| **SurfaceRow** | 侧栏对话项、文件树行 | `ConversationItem.tsx`、`FileTreeRow.tsx` |
| **ToolLine** | 过程时间线工具行 / 组 | `ToolLine.tsx`（`ProcessTimeline` 消费） |
| **FinishReasonChip** | 回合非正常收尾 chip | `finish-reason-chip.tsx` |
| **PanelShell** | 右侧面板、指挥台 | `SidePanel.tsx`、`CanvasDecisionPanel.tsx` |
| **SearchField** | 页内列表/树筛选、Popover 选项过滤 | `search-field.tsx`（`field` / `plain`） |
| **SearchTrigger** / **TitleBarSearchTrigger** | 全局搜索与命令面板入口（侧栏 / TitleBar 各一假输入，同开 `CommandPalette`） | `search-trigger.tsx` + `CommandPalette.tsx` |

新交互卡片应优先复用 **DecisionCard + Button**，并确保聊天与画布双视图可共用（见 `CanvasDecisionPanel.tsx`）。

## 搜索 / 筛选 / 查找（三层语义）

产品内三种「找东西」动作**用词与组件固定**，避免同一屏混用「搜索」：

| 层级 | 用户词 | 入口 | 组件 | 范围 |
|---|---|---|---|---|
| **全局发现** | 搜索 | `Ctrl/Cmd+K`；TitleBar=`TitleBarSearchTrigger`、侧栏=`SearchTrigger` | 二者 → `CommandPalette` | 对话 / 消息 / 项目 + 命令 |
| **页内缩小** | 筛选 | 当前列表或树上的输入框 | `SearchField` `variant="field"` | 仅当前视图已加载项（客户端子串） |
| **就地定位** | 查找 | `Ctrl/Cmd+F`（`FindBar`） | 专用浮条（非 `SearchField`） | 仅当前会话**已加载**消息 |

**Popover 内**（`@` 引用、草稿项目选择器等）用 `SearchField` `variant="plain"`（无外边框，宿主已有 shell）。

**FindBar 无命中**时弱引导「在全对话中搜索」→ `openSearch(query)` 预填并打开命令面板（全历史消息走 Tier 1 + `load-around`）。

**禁止**：侧栏放真搜索输入框（与全局入口重复）；页内 placeholder 写「搜索」（应写「筛选」）；`FindBar` 文案暗示能搜未加载历史。

→ 产品决策与 IA 见 [`前端UX设计.md` §十四](/docs/04-前端/前端UX设计.md)；技术契约见 [`前端技术与架构.md` §9.8](/docs/04-前端/前端技术与架构.md)。

## Lint 门禁

```bash
node scripts/check-ui-tokens.mjs --src apps/desktop/src/renderer
node scripts/check-ui-tokens.mjs --src apps/mobile/src
```

禁止：`rounded-md/sm/2xl`、自定义 px 字号（10/11/13）、Tailwind 调色板类、hex 任意色。已接入两端 `pnpm lint` 与 CI。

桌面 `pnpm lint` 另跑 `scripts/check-no-localstorage.mjs`（业务禁直碰 `localStorage`，统一走 `lib/uiStorage.ts`，见 [`前端技术与架构.md` §9.11](/docs/04-前端/前端技术与架构.md)）。

## design-tokens 同步清单

变更语义色 / 侧栏 / 身份色 / 语法高亮时：

1. 改 `packages/design-tokens/src/tokens.css`（desktop `:root` + `.dark`）
2. 若 mobile 映射需变 → 改 `mobile-light.css`
3. 跑两端 `check-ui-tokens` + 目视 dark/light
4. 更新 `.cursor/rules/color-tokens.mdc` 若分类或命名变

## 迁移策略

**touch-it-adopt-it 已完成**：renderer 内交互控件已统一为 `Button` / `IconButton` / `SurfaceRowButton` / `Switch`。新代码默认用 primitive。

### 不可改为 `<button>` 的例外（HTML 结构约束）

| 位置 | 原因 |
|---|---|
| `AgentNode` 图节点 | 复合块（icon + 多行 + badge），用 `div role="button"` |
| `ui/button.tsx` 等 | primitive 实现本身 |

`ConversationItem` 已采用方案 B：`SurfaceRow` + 标题区 `role="button"` + 并列 `IconButton`。

---

## 配色 token 规范

只用语义 token，颜色由主题统一定义。**禁止**硬编码任何具体颜色值。

### 单一定义源

OKLCH 语义色单源：**`packages/design-tokens/`**

| 文件 | 用途 |
|---|---|
| `tokens.css` | 桌面 `:root` + `.dark`（由 `globals.css` `@import`） |
| `mobile-light.css` | 手机用途映射浅色（由 `styles.css` `@import`） |

桌面 Tailwind 映射仍在 `apps/desktop/src/renderer/styles/globals.css` 的 `@theme inline`。需要新颜色 → 先加进 `packages/design-tokens/src/tokens.css`，再视需要映射 Tailwind 类。

### 语义 token

| 用途 | token | 典型类 |
|---|---|---|
| 品牌 / 主 CTA / 活跃 / 运行中 / 信息提示 | `primary` `primary-foreground` | `bg-primary` `text-primary` |
| 成功 / 已完成（绿） | `success` `success-foreground` | `text-success` `ring-success` |
| 警示信号（琥珀）——仅审查预警「待关注」/ 额度告警 / 未配置模型角标等真警示；**不再用于检查点 / 拍板类卡片**（2026-07 拍板：拍板类统一中性灰壳 + 蓝 CTA） | `warning` `warning-foreground` | `text-warning` `bg-warning/10` |
| 错误 / 失败 / 停止（红） | `destructive` `destructive-foreground` | `text-destructive` |
| 闲置 / 等待 / 次要文本 / 浅灰表面 | `muted` `muted-foreground` | `text-muted-foreground` `bg-muted` |
| hover 表面 / 选中底色（**中性，非状态色**） | `accent` `accent-foreground` | `hover:bg-accent` |
| 表面 / 文本 / 描边 | `background` `foreground` `border` | `bg-background` `border-border` |
| 卡片 / 浮层 | `card` / `popover`（→ `background`） | `bg-card` `bg-popover`；靠 `border` + `shadow` 分层 |
| 表单 / 焦点环 | `input`（→ `border`）`ring`（→ `primary`） | `border-input` `ring-primary` |
| 侧栏专属 | `sidebar` `sidebar-foreground` `sidebar-accent(-foreground)` `sidebar-border` | `bg-sidebar` `bg-sidebar-accent` |
| shadcn 兼容别名 | `secondary`（→ `muted`） | `bg-secondary` 等同 `bg-muted` |

### 执行状态 → token（统一映射，勿再分叉）

| 状态 | token |
|---|---|
| `pending` / `ready` / `cancelled` | `muted` / `muted-foreground` |
| `running` | `primary`（品牌蓝） |
| `completed` | `success`（绿） |
| `failed` | `destructive`（红） |
| 检查点 / 待裁决（待放行 / 待你拍板） | `primary`（品牌蓝，「需要你」信号） |

### 分类色板（非状态语义，定义在 tokens.css）

除上表语义 token，`globals.css` 另有**分类用途**的裸 `--*` 变量（同一 OKLCH 亮度带，读作一个家族）——**仅供对应场景内联使用**（`var(--*)`），不进 `@theme inline`、不做 Tailwind 类：

- **代码高亮** `--syntax-*`：代码块着色。
- **角色身份** `--agent-1..8`：协作图队员头像的「身份色」，按角色名 hash 取一格（`lib/agentIdentity.ts`）。**身份 ≠ 状态**——身份只画在头像盘，运行状态仍走上表状态色。新增/调整 → 改 `packages/design-tokens/src/tokens.css`。
- **产物 / 目录分类** `--artifact-*` `--catalog-*`：工具箱创作工具磁贴、能力图鉴分类图标（`lib/catalogColors.ts`）。**分类 ≠ 状态**——仅启动器/目录层扫视识别，不进 Tailwind 类、内联 `var(--*)` + `color-mix`。
- **辩论阵营** `--debate-side-pro` `--debate-side-con`：正反 2 方固定红蓝对垒（`pro`=蓝 / `con`=红），仅 `debateSideColorVar` 在 `pro`/`con` key 时解析；多方仍走 `--agent-N` hash。**阵营 ≠ 状态**——彩度 0.11 介于 agent(0.07) 与 status(~0.18+) 之间，不用 `primary`/`destructive`。

### 跨端（桌面 + 手机）· 品牌不变量

两端是同一产品。token 层唯一的**硬约束 = 跨端品牌不变量必须一致**：

- **品牌色 hue 255**；状态色语义 hue 固定：成功 152 / 警告 65 / 错误 27 / 品牌蓝 255。精确 L/C 值以 **`packages/design-tokens/src/tokens.css`** 为准（桌面 `:root` + `.dark`；手机 `mobile-light.css` 仅浅色用途映射）。
- 改品牌 / 状态色 → **只改 `packages/design-tokens/`**，桌面与手机通过 `@import` 自动同步。
- **手机端暂不做暗色模式**（明确决策，非待办）：手机端是桌面减能力层的瘦客户端，浅色已满足当前需求，暗色为纯增量样式、需要再单独决策。故手机 `styles.css` 只维护 `:root` 一套浅色值、**不引入 `.dark` / `prefers-color-scheme` 分支**；桌面 `.dark` 不要求手机镜像。

实现方式两端不同（各自全新建，符合 `cross-platform-frontend`）：

| 端 | 配色实现 |
|---|---|
| 桌面 | Tailwind v4 + `@import @agentcore/design-tokens/tokens.css` + `globals.css` `@theme inline` |
| 手机 | `@import @agentcore/design-tokens/mobile-light.css` + 裸 `var(--*)` |

### 禁止

- **硬编码调色板与 hex**：`bg-blue-500`、`text-red-600`、`#3B82F6`、`bg-[#...]`。唯一彩色出口是上表 token。
- **`hsl(var(--…))` 包裹**：token 已是 OKLCH，`hsl()` 会产出非法值。内联样式直接写 `var(--primary)`；类名优先用语义工具类（如 `accent-primary` 而非 `accent-[…]`）。
- **拿 `accent` 当成功色**：`accent` 是中性 hover 表面。「已完成 / 成功」一律 `success`（曾误用为灰，已修正）。
- **绕过 token 新建散色变量**：先评估能否复用，必须新增则进 `packages/design-tokens/src/tokens.css`。

### 组件 tone 预设

L2/L3 共享的 Tailwind 类组合 → `apps/desktop/src/renderer/components/ui/tone-presets.ts`（`DecisionCard`、`Badge`、`CheckpointCard` 等消费）。改卡片色调优先改此文件。

## 桌面端布局规格

两级宽度梯度 + 统一 padding，所有页面必须归入其中之一。

### 宽度梯度

| 梯度 | Tailwind | 像素 | 适用场景 |
|---|---|---|---|
| **content** | `max-w-4xl mx-auto` | 896px | 详情、表单——居中线性阅读 |
| **canvas** | `max-w-[1200px] mx-auto` | 1200px | 探索、列表、文件管理——网格/多列 |

> **自有布局豁免**：对话页（见下）、文件页（分栏树）、**设置页**（左二级导航 + 内容分栏）、**真·全屏页**不走上表梯度。设置页内容是**左对齐**的 `max-w-3xl`（768px）阅读列（非居中 content 档）：左栏已是导航轴，内容左锚定贴分隔线读起来重心更稳，宽屏右侧留白是设置布局的常态。→ 见代码 `pages/MorePage.tsx`。真·全屏页（如 `工具箱 → 产品手册` `/toolbox/manual`）用 `fixed inset-0 z-50` 覆盖整窗（含应用 `TitleBar`），故页顶须**自绘窗口控件**（拖拽区 `[-webkit-app-region:drag]` + 最小化/最大化/关闭复用 `window.windowApi`，否则无边框窗口无法移动 / 关闭），内部自定义满宽布局（产品手册用左侧目录 + `max-w-3xl` 阅读列；图密集页可用 `max-w-[1400px]` 阅读容器 + 宽屏多列）并自带返回 / Esc 退出。→ 见代码 `pages/toolbox/manual/ManualShell.tsx`。

### 对话页特殊结构

对话页不走上面的梯度：消息滚动区与底部输入区**统一用 `max-w-3xl`（768px）**，分别用内层 wrapper 居中。768px 比 content 档（896px）窄一档，是为对齐 ChatGPT / Claude 的正文阅读行长——896px 在 14px 字号下英文/代码约 120 字符/行偏长，768px 更舒适。阅读区与输入区**同宽**（早期阅读区曾用 896px，因行长偏宽已收窄对齐）。

```
滚动容器(full-width) → 内层(max-w-3xl mx-auto, px-6 py-4) → messages
底部区域(max-w-3xl mx-auto) → error/approval/InputBar
```

滚动条保持在全宽容器边缘，内容居中。

### padding 规范

- 内容页横向：`px-6`（24px）
- 内容页纵向：`py-8`（32px）
- 对话页：上下 `py-4`，InputBar 自带 `px-4 pb-4 pt-2`

### 字体大小层级（严格 4 级）

| 级别 | Tailwind | 像素 | 用途 |
|---|---|---|---|
| caption | `text-xs` | 12px | 元数据、badge、时间戳、小按钮 |
| body | `text-sm` | 14px | 所有正文、表单、按钮、消息 |
| heading | `text-base` | 16px | 组件标题、导航项 |
| title | `text-xl` | 20px | 页面标题 |

**禁止**：`text-[10px]`、`text-[11px]`、`text-[13px]`、`text-lg` 及任何自定义像素值。

对话页空状态欢迎语（无消息时的引导 hero）使用 `text-2xl`（24px）为专用例外——空屏中唯一的视觉落点，需更强召唤力。其余场景一律不得超过 `text-xl`。

### 圆角层级（严格 3 级）

| 级别 | Tailwind | 像素 | 用途 |
|---|---|---|---|
| small | `rounded-lg` | 8px | 输入框、按钮、小卡片、tab |
| large | `rounded-xl` | 12px | 卡片、面板、气泡、弹窗 |
| pill | `rounded-full` | ∞ | 头像、badge、pill 标签、进度条 |

**禁止**：`rounded-sm`、`rounded-md`、`rounded-2xl`、`rounded-3xl`。

### 按钮尺寸（2 档）

| 档位 | 值 | 用途 |
|---|---|---|
| sm | `size-7` (28px) | icon-only 小按钮 |
| md | `size-8` (32px) | 标准交互按钮 |

导航项使用 `h-9`（36px）为专用例外。

### UI Primitive 层

交互按钮/图标按钮优先用 `components/ui/` 的 `Button` / `IconButton`（sm h-7 / md h-8），而非手写 `rounded-lg` 类。→ 见 [`UI-Pattern索引.md`](UI-Pattern索引.md) 与 `components/ui/index.ts`。

### 图标尺寸

| 场景 | lucide size | 像素 | 说明 |
|---|---|---|---|
| 主导航项 | `size={18}` | 18px | 配合 heading 级 `text-base` |
| body 级按钮/列表 | `size={16}` | 16px | 正文行内图标 |
| caption 级/辅助 | `size={14}` | 14px | 小按钮、元数据图标 |
