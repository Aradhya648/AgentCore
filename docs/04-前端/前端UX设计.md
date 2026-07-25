---
status: blueprint
code: apps/desktop/src/renderer/
related:
  - docs/04-前端/前端技术与架构.md
  - docs/03-AI核心/辩论编排设计.md
skip_if:
  - 只改 Store/IPC（读前端技术与架构）
---

# 前端 UX 设计

> **状态**：已确定方向
>
> 本文记录**已落地现状 + 关键决策（含被否决方案）**。工作区/文件模型 → [`双模式工作区`](/docs/02-架构/双模式工作区.md)；`FileSource` 与桌面文件树 → [`前端技术与架构`](/docs/04-前端/前端技术与架构.md) §八。

---

## 核心设计理念

用户心智模型是「掌管一支由 AI CEO 带队的 Agent 团队」（你是老板，团队替你跑），UI 是用户感知这一心智模型的唯一窗口。设计需在「零门槛入门」和「差异化体验」之间取得平衡。设计原则（零门槛、渐进揭示、简单任务零噪音、放大态无损等）贯穿 §一。

---

## 一、全局布局与团队展示

全局采用 **侧栏 + 页面级自定义布局**（详见 [`前端技术与架构.md`](/docs/04-前端/前端技术与架构.md) §五）。核心对话页为单栏聊天区：

```
/conversations/:id（单栏聊天区）
  消息流（多 Agent 回合：助手消息内嵌 InlineTeamGraph）+ ApprovalPrompt（工具审批）
  └ MessageInput（空草稿态居中 / 会话中底部固定）
内嵌图状态条「在画布打开」→ 全屏回合详情页（`TurnDetailPage`，路由 `/conversations/:id/turn/:turnId`：协作图 / 辩论室 / 对比平级 tab）
点图节点 → 右侧 SidePanel 新开该 run 的详情 tab（被动下钻）；面板是一条扁平 tab 栏——固定首位「工作区」tab（文件/快照）+ 按需的 run 详情 tab。右上「侧面板」开关 / Ctrl+I → 显隐（冷启动落「工作区」tab），Ctrl+J → 直达「工作区」tab
```

**对话输入框落点（空态居中 / 会话中底栏 · ✅）**：对齐 ChatGPT/Claude——**仅空草稿态**（无消息）把 `MessageInput` 与空态引导（问候语 / starter chips）合成视口中央一块；发出首条消息后以 FLIP 过渡落到对话底栏，之后会话中永远底栏。平台代付、开箱即用后**无「未接入」态**——keyless 亦居中（不再有「中央 CTA + 底栏输入」的 needs_key 变体）。`TurnComposer` 统一核语义不变；画布 `CanvasCommandBar` 与放大态 `TurnDetailPage` 不受影响。→ 见代码 `components/chat/ChatView.tsx`、`hooks/useComposerDockFlip.ts`、`lib/onboarding.ts`（`shouldCenterDraftComposer`）。

**侧栏对话区（IA · 两区混合「方案 B」）**：分上下两区——

- **上·项目分组**（按项目可折叠）：组头左槽云/本地图标（hover 时 chevron 叠同一槽位折叠）、名称；组内对话标题与组头名称左对齐；右侧 hover「+」= 在该项目新建对话、hover「⋯」/ 右键 = 新建对话 / 查看全部对话 / 浏览文件 / **归档全部对话**（批量归档该项目下活跃对话，非 `Folder.archived`）/ **删除项目…**（单入口；两步确认——默认删容器并归档其下对话、云端文件约 30 天清理，链入第二步可彻底删除；与文件页共用 `DeleteFolderDialog`）；组内复用 `ConversationItem` 列 Top 5，超出走「更多」跳 `/conversations` 并聚焦该组。按近活跃排序、组数 ≤6（溢出走「查看全部对话」）；展开态按 `folderId` 持久化（`useSidebarStore`，显式切换优先；无记录默认折叠、唯含当前对话的组自动展开）。
- **下·裸聊扁平列表**（仅未归属项目的对话）：置顶优先、当前裸聊对话恒可见；**上限自适应**——无项目分组时独占侧栏给足 15、有分组时放宽到 10，溢出走「查看全部对话」（侧栏单层外滚，不另设嵌套滚动条）。
- **底部**：「查看全部对话」入口（归档等低频整理在页内左侧筛选「已归档」）。

**对话行操作**：hover 为整理主路径——重命名 + 归档 +「更多」（置顶 / 分享 / 导出 / 永久删除）；会话与项目出生定终身（不支持事后移入/「在项目中继续」）。归档成功 toast 5s 内可撤销；右键菜单同集。批量归档 / 永久删除与「30 天未活跃」快筛仅在 `/conversations`。

**归档 vs 删除**：归档可取消、仅从活跃列表隐藏；删除对用户为永久（后端 soft-delete 保留期不暴露回收站 UI）。

**项目 ⊥ 裸聊 · 干净二分零重复**：已归属对话只在其项目组里、**不**在裸聊区重复（**否决**跨区「最近」列表：双显噪音>收益）；裸聊只在下方扁平区（**否决**为裸聊单设「未分组」组：徒增空组噪音）；全部对话都已归属时裸聊区整体隐藏（0 对话走空状态）。**两区无文字标题**——组头（chevron + 图标 + 计数）与裸聊平铺行视觉已足够区分，两区并存以细分隔线隔开。

**决策**：侧栏保持轻量——裸聊 10/15 自适应、每组 Top 5、组数 ≤6，低频整理（完整列表 /「按项目筛选 / 页内搜索」）收敛到对话管理页 `/conversations`，项目生命周期归「文件」中枢 `/files`；分组逻辑下沉纯函数 `buildWorkspaceGroups`。**「对话」导航即「新建对话」**：点顶部「对话」入口默认开空白草稿（`Ctrl/Cmd+N` 同效），回到旧对话走侧栏列表 /「全部对话」；路由 `/` 是新草稿唯一真相。

→ 见代码 `lib/newConversation.ts`、`pages/ConversationPage.tsx`、`components/sidebar/RecentConversations.tsx`、`components/sidebar/WorkspaceGroups.tsx`、`components/sidebar/WorkspaceGroupHeader.tsx`、`components/folders/DeleteFolderDialog.tsx`、`hooks/useWorkspaceGroups.ts`、`stores/sidebar.ts`、`pages/ConversationsPage.tsx`。

**全局协作感知（跨对话 · ✅ 已落地）**：Agent 团队运行状态不再只在当前对话消息流内可见——

- **对话列表状态点**：执行中＝品牌蓝脉动；**「等你决策」＝实心点带光环**（覆盖热阻塞交互 + 任意 kind 暂停帧；判定谓词 `isAwaitingUserEntry`）。已知边界：数据源自打开会话时的 recovery 注入 / live 挂起收口，冷启动后未打开过的暂停会话暂不亮（全局扫描待做）。
- **跨对话完成通知**：用户不在某对话时，其团队完成 / 失败 / 需审批弹 Toast（跳转 action，按对话去重）；窗口失焦并发 Electron 原生通知；worker 亦可经 `desktop_notify` 工具主动触发本机通知。**挂起 ≠ 完成**：`finish_reason=paused` 弹「等你拍板」而非「已完成」。
- 纯派生自各 store（生成态 + InteractionStore + pausedTurns），不新增数据通路。→ 见代码 `services/teamActivityNotifications.ts`、`lib/teamActivity.ts`、`main/notification-service.ts`。

**团队展示并入「思考·正文·工具」时间线**：多 Agent 与单 Agent 回合走同一条内联时间线（`ProcessTimeline`，§一B）——多 Agent 委派时，一张协作图（`InlineTeamGraph`）**内嵌在 `delegate`/`debate` 步的时序位置**承载团队界面（图顶状态条折进原任务卡片职责；节点 face 只显角色 + 任务/输出 + 用时/工具，¥ / token 归 run 详情 §7.3B；点节点下钻右侧被动面板；「在画布打开」切放大态）。CEO 委派前后的思考/正文/自调工具围着团队工作按真序排列；单 Agent 回合不出图。**开工挂起期也不出图（✅ 2026-07）**：`run_plan` 已声明但**没有任何 run 启动过**时（开工卡挂起 / 开工即停止）内嵌图不渲染——图无运行事实可观测、队员名单与开工卡重复，决策注意力归续跑卡。**被替代**：旧「挂起期照常渲染全 pending 骨架图 + 运行态转圈条」——把「等你拍板」画成「正在协作」。仍渲染图的挂起场景（`plan_review` 波间、已有完成节点）状态条走静态 `PausedStrip`。live 与重载一致——`process[]` 持久化经 journal 回放。→ 见 [`前端技术与架构.md` §9.2–9.6](/docs/04-前端/前端技术与架构.md)。

### 一B、单 Agent「思考·正文·工具」内联时间线 `ProcessTimeline` ✅ 已落地

单 Agent 回合把**思考 · 正文 · 工具**按真实发生顺序交织为一条内联时间线（Cursor 式）；末段正文即最终答案（无独立底部答案区）。多 Agent run 详情复用同一 `ProcessTimeline`（§十）。→ 见代码: `components/chat/ProcessTimeline.tsx`

- **来源卡可信度徽标 ✅**：`citations.tier` 可选；缺=legacy 不渲染；显式 `weak` 必显；硬拦域名不挂卡。→ 见 [工具与能力系统 · 引用质量闸](/docs/03-AI核心/工具与能力系统.md)
- **回合证据台账与 `#rN` ✅**：独立 SSE `evidence_ledger`；主卡 `citations_event` 仅成稿引用集；辩论场级台账不占本通道；历史有 id 走 id、无 id 走池序。→ 见代码: `stores/projection/`
- **决策（为何全内联）**：ReAct 忠实时序优先；**否决**常驻吵闹工具卡。
- **决策（`ProcessToolGroup`）**：连续 ≥2 工具保序折叠摘要；纯渲染层 fold，**不动** journal/conformance；**否决**按类别归桶。→ 见代码: `lib/processTimeline.ts`
- **完成态整段过程折叠 ✅**：可见节点（正文/团队图/决策卡）绝不入折。→ 见代码: `ProcessTimeline.tsx`
- **复制两档 ✅**：仅交付（默认）/ 含过程；history 只用交付。→ 见代码: `lib/messageExport.ts`
- **本地同步态 `synced_pending` ✅**：静默成功、显式失败；不进 SSE。→ 见代码: `message-bubble/SyncStatusHint.tsx`
- **保序持久化**：`process_*` 渐进落 journal；纯散文不扩展。→ [执行引擎 §8.3](/docs/03-AI核心/执行引擎架构设计.md)
- **实时行 / 等待态 ✅**：transport-only，重载不保留。→ 见代码: `ToolLine.tsx`
- **结束原因 chip / 内联错误卡 ✅**：`max_rounds` / `degraded` / `unproductive` / `error` 等非正常收尾出中性灰 chip；**`cancelled` / `interrupted` 不出 chip**（正文定格或团队状态条「已停止」即终态，对齐主流对话 AI）。错误卡直播 SSE、重载自 `turn_end.error`；大众可见「复制诊断信息」。→ 见代码: `finish-reason-chip.tsx`、`lib/errors.ts`

| 形态 | 何时 | 职责 |
|------|------|------|
| 内嵌协作图（主） | 多 Agent 回合，随消息常驻、刷新可回看 | 状态条（进度/成本/救火）+ DAG + 节点用时/工具 |
| 画布放大态（按需） | 点内嵌图状态条「在画布打开」 | 切画布、就地放大该回合：大画布 + 回放 Timeline + 节点详情 |
| 右侧 SidePanel（被动） | 点图 worker 节点新开 run tab；画布点端点新开内容 tab | 一条扁平 tab 栏：固定「工作区」tab + 按需详情 tab（run 全文 / 端点提问·最终回答，可并存对比） |

> 信息分层（Layer 0–4 模型）：单 Agent 回合 = 一条内联「思考·正文·工具」时间线（§一B，思考/工具＝Layer 1–3、末段正文＝Layer 0 输出，按真实顺序交织）；多 Agent 回合 = 内嵌图（Layer 1–3 状态/进度/协作）+ 点节点进面板看 run 全文（Layer 4）。

**聊天特有元素**（检查点 / 非阻塞发问 / 结构化挂起 / 断连续跑 / 工具审批等）→ 见代码 `components/chat/`；消息载入契约见 [`前端技术与架构.md` §9.7](/docs/04-前端/前端技术与架构.md)。**已否决**：Slash 命令、Agent/Team 选择器、产物 Pill、常驻吵闹工具卡（每回合落点 pill 式噪音）、草稿期「存储位置 ⊥ 归入项目」双入口（合并为单一「在哪工作」选择器，见 §九）。

> 页面宽度 → 见 `.cursor/rules/desktop-layout.mdc`；对话页 / 文件页自有布局除外。

---

## 二、新用户首启与空态引导 ✅ 已落地

新用户激活 = **首次成功跑完一个真实回合**（不是注册完成、不是配置完成）；产品的差异化 aha = 第一次亲眼看到团队分工协作。**形态 = 平台代付、开箱即用**：部署层 `billing_mode=platform`，新用户注册即有平台额度，未配 key 也能直接发起对话——**不存在「先接入模型才能对话」的门**（后端计费/额度语义见 [成本配额与计费](/docs/05-平台与运维/成本配额与计费.md)）。BYOK 降级为「设置·模型配置」里的**可选升级**（自担费用）。发首条消息若真遇后端拒绝（如 byok 部署的 402 `LLM_KEY_REQUIRED`）仍保留「错误驱动」兜底（横幅「去配置」直达模型配置），但不再前置为主动接入门。

**首启入口 = 草稿空态**（已删除一次性全屏价值介绍页 `OnboardingFlow` / `OnboardingGate` 及其 skip 持久化）：新用户打开即见草稿页，无全屏接管、无「开始使用」门。

- **移除「接入门」判定**：不再有 `hasModelAccess` 前端闸门（原 `configured || billing_mode==="platform" || free_tier_active`）——平台代付默认给额度，**keyless 视同有 access**，首启与空态一律不看模型接入。`GET /users/me/llm-providers` 顶层的 `billing_mode` / `free_tier_active` 仅供 **Usage / 配额面**消费（`UsageSettings` 月度条、配额耗尽错误分流；见 [`前端成本呈现.md`](/docs/04-前端/前端成本呈现.md)），**组合选择器不读这两字段**（§十三）。
- **判定纯客户端推导，否决服务端 onboarding 状态 / DB 列**：空态两态从对话列表推导，不新增漂移面；情境提示 seen 落本地 `uiStorage`。
- **BYOK 表单只在「设置·模型配置」**：`ModelKeyForm`（厂商预设 / Key / Base URL / 默认模型）仅作设置里的可选升级入口，保持单一真相源、禁止第二份配置逻辑。
- **否决强制配完才能进**（form gate 反模式）：keyless 直接落草稿页 starter_chips 空态开聊，无 needs_key 拦路。

**草稿空态两态 `DraftEmptyState`**（平台代付后由三态收敛，删除「未接入」态）：0 对话 →「今天想解决什么问题？」+ 协作气质副句 + 3 枚**首启任务 chips**（内容设计为天然触发多 Agent 分工的真实任务，点击仅填入**居中**输入框、不自动发送）+ 输入框与引导合成中央块；老用户（已有对话）→ 单句问候 + 居中输入框。**keyless 直接落 starter_chips**（无「先连接你的模型」态）。发出首条消息后输入框过渡落底（见 §一「对话输入框落点」）。登录 / TitleBar / 侧栏 / 关于字标统一 `BrandMark`；品牌句权威 → [产品定位与品牌](/docs/01-产品/产品定位与品牌.md)，Pattern → [UI-Pattern · BrandMark / 桌面 UI 统一](/docs/04-前端/UI-Pattern索引.md)。

**免费额度耗尽（429 `FREE_TIER_EXHAUSTED`）**：转化语义而非「等重置」——错误条展示后端文案（「本月免费额度已用完——接入自己的模型即可不限量继续」，后端 `message` 单一来源）+「去设置」CTA 直达模型配置（手机端文案仍为「去配置」；`errorActionForCode` 按共享 `KEY_CONFIG_ERROR_CODES` 目录分流）；既有 `QUOTA_EXCEEDED`（等窗口重置、不给重试）语义不动。「免费额度」文案仅出现在 **UsageSettings 月度条**（`free_tier_active` 时「本月免费额度」）与上述错误条——**不**进 `ModelPicker` 徽标。

- **决策修订（2026-07）**：原「空态只留一句提问；场景模板卡片否决（与手机端、宣传素材对齐）」修订为**仅新用户可见的首启 chips**——空白画布冻结是 Agent 产品激活的头号杀手，chips 让首跑直达多 Agent 差异化时刻；原否决的关切（日常噪音）由「产生第一个对话后永久消失」保住，老用户与宣传素材所见空态不变。
- Composer 角标为组合选择器（§十三）：选本会话模型组合或「跟随账号默认」；「管理组合…」进设置。

**首次协作情境提示 `ContextualTip`**（非 Tour）：首次出现内嵌协作图时一枚一次性浮层（「点节点可看每个 Agent 的实时工作」）——可随手关闭、本地记 seen、总量 ≤3。渐进披露的延伸，**否决**多步 Tour / 教程墙 / 轮播弹窗。

- **拍板面提示已撤销（2026-07）**：现状仅保留协作图一枚；原「首次出现拍板面」浮层（`decision_card`）删除，因开工卡 / 审批卡自身的标题、副标题与按钮已充分表达「需你拍板、确认后团队才继续」，横幅与卡片语义冗余；且其「检查点与审批会出现在这里」是空态解释语气，却只在卡片已出现时才挂出，时态错位。

**帮助可发现性**：空态副链接 + 侧栏用户菜单补「产品手册」入口（工具箱首卡、命令面板既有入口不变）；功能现场 `?` 深链——检查点拍板卡 / 工具审批卡 / 协作图工具条 / 辩论室「怎么看」/ 自主度设置 / 升级卡六处，HelpCircle 图标 + tooltip 深链到手册对应节（统一走 `components/ManualHelpLink.tsx` 登记，节 ID 消费手册 `sectionIds.ts`，禁手写路由）。

**激活漏斗（日志埋点）**：`auth.register` / `llm_provider.created` / 首回合成功（沿用既有回合完成日志）三事件在 `logs/dev.jsonl` 可查漏斗；开发期不建分析面板。

**Mobile 最小 parity**：聊天空态与桌面对齐——**无「先连接你的模型」接入门**，keyless 直接进「开始新对话」欢迎态（BYOK 仍在「更多 → 模型配置」作可选升级）。发送若真遇 `LLM_KEY_REQUIRED` / 配额类错误仍保留错误条带「去配置」/「接入自己的 Key」兜底（`errorActionForCode` 按共享 `KEY_CONFIG_ERROR_CODES` 目录分流）。任务 chips 桌面验证后再下放。

→ 见代码 `components/onboarding/`（`DraftEmptyState` / `ContextualTip`）、`lib/onboarding.ts`；离线预览 `#/preview/onboarding` + `pnpm -C apps/desktop shoot:onboarding` 截图自检。

---

## 三、内嵌协作图与状态条（现状）

多 Agent 回合的团队界面是内嵌进助手消息的协作图（`InlineTeamGraph`，→ 见代码 `components/chat/InlineTeamGraph.tsx`）：图顶一条**状态条**按 `execution.status` 分四态渲染，下方是可折叠的协作图（`GraphView` 内嵌形态），状态条「在画布打开」进入全屏回合详情（`TurnDetailPage`，就地放大该回合）。状态条吃下了原任务卡片的全部职责（AgentCore 聊天界面与普通对话 AI 的核心视觉差异点）：

- **执行中**：进度 + 慢工具 transport-only 阶段文案；**协调等待一行化**——成员细节归图节点。**否决**状态条逐行成员列表。→ 见代码: `TeamSynthesisPreviewLine.tsx`
- **已完成**：一行战绩；部分失败 + 救火行。**后台托管不误收口**：`message_end` 不塌 completed，等 `runsAllSettled`。→ 见代码: `stores/execution/store.ts`
- **已停止 / 失败**：战绩或 FailureStrip + 救火行。

救火行（`RecoveryActions`）由失败条、部分失败的已完成条、已停止条共用——**行内文字链接**（贴着停止/失败状态，不堆按钮卡）：

| 场景 | 唯一动作 |
|---|---|
| 部分失败（有 worker `failed`） | **重试失败项** → `runRetryFailed`（后端 `retry-failed`，复用已成功 worker） |
| 整轮失败 / 已停止 | **重试** → `runRegenerate` |

不堆叠「全部重新生成」与「重试失败项」；**无显式「忽略/放弃」**——用户发起新 turn 时隐式收口（`recovery_ignored` 审计 + `clearExecution`）。**否决**「已决策·执行中断」救火「继续」/ 无帧 `continueAfterDecision`（用户停止 = 本轮结束；续聊走输入框新消息）。**否决**消息级空 `interrupted` 救火「重试」（无正文时不挂 regenerate 文字链——对齐主流：重说/发新消息；`cancelled` / `interrupted` **不出** finishReason chip）。

状态条尾部为一级图标按钮：执行中给「停止」、已完成/已停止给「回放」（切画布放大态自动播放时间轴），外加常驻的折叠 /「在画布打开」；不设 `[···]` 菜单——整轮重新执行统一交给消息级「重新生成」与救火行。内嵌图块在 `run_plan` 首次挂载时播放一次入场动画（`animate-task-card-enter`，遵循 `prefers-reduced-motion`，见 `styles/globals.css`）。

**协作图默认展开（✅ 已落地）**：内嵌协作图默认一直展开（含完成 / 取消 / 失败与辩论回合），保留状态条折叠按钮；用户手动切换后以其选择为准，且**按对话持久化**（`usePersistentDisclosure`，键 `{messageId}:inline-graph`，与画布 graph-fold 互不相通；持久化架构见 [`前端技术与架构.md` §9.11](/docs/04-前端/前端技术与架构.md)）。辩论正文仍归画布放大态「辩论室」（§4.2），聊天侧图展开不替代赛事页。→ 见代码 `InlineTeamGraph.tsx`。

**幕序列渲染（✅）**：按幕分段 + 拓扑列分带；能力表幕级取用；旧无 `act` → fold 单幕零变化。→ 见代码: `components/graph/`

**多幕 LOD（✅）**：≥2 幕 = 幕摘要卡链 + **恰好一幕**展开 DAG；单幕零变化。**否决**默认全展开与「DAG 全归画布」。→ 见代码: `components/graph/actLod.ts`

**face 徽标预算 +「待你拍板」行动条（✅ · 方案 C）**：功能徽标同屏 ≤2（待拍板 > 异常 > 过程性）；行动条**仅 ≥2 项待决**出现、只导航不建卡。**否决**只加行动条不减徽标。→ 见代码: `components/graph/agentNode/faceBudget.ts`

**救火行 `RecoveryActions`（✅ · 克制形态）**：按场景只出一条文字链接（重试失败项 XOR 重试）；经 `userMessageIdForAssistant(ExecutionScope)` 锚定本回合用户消息（找不到才回落 `lastUserMessageId()`）。放弃语义改隐式：`sendTurn` 入口调用 `dismissRecoverableExecutions`（`acceptRunOutcome(..., reason: recovery_ignored)` + `clearExecution`）。→ 见代码 `StatusStrip.tsx`、`services/turns/dismissRecovery.ts`；后端契约见 [执行引擎 §retry-failed](/docs/03-AI核心/执行引擎架构设计.md)

**续写可发现性（✅ · 无语法糖按钮）**：**否决**消息下「继续生成」一键按钮（只是替用户发字面「继续」）。末条助手消息为 `cancelled` / `interrupted`（有正文）/ `max_rounds` 时，输入框 placeholder 提示「可输入「继续」接着说…」；空 `interrupted`（无正文）**不**挂消息级「重试」——续聊走输入框新消息（与主流一致）；**`cancelled` / `interrupted` 不出 finishReason chip**（正文定格即终态；团队回合另有状态条「已停止」）。**否决**「已授权 · 执行中断 / 一键继续」无帧续跑（`InterruptedAfterDecision` / `continueAfterDecision` / 本地 `salvage_retain_open`）：用户停止 = 本轮正常结束并保留已产出；还想接着干 → 输入框发新消息。`RunConfirmPrompt` / `RetryBanner` / run-redirect 保留不动。

**出现时机规则**（核心决策）：

| 场景 | 行为 |
|------|------|
| 简单任务（CEO 直接回答，无 plan） | **不出图**，直接流式输出，体验同 ChatGPT |
| 多 Agent 任务（CEO 调用 `delegate`） | `run_plan` 到达时**自动内嵌**于助手消息上方 |
| 跨回合同图追加（`append_to_execution_id`） | 新回合只渲染 `graph_append` 锚点条（「已往上方协作图追加 N 名成员」）；生长帧按 `execution_id` / `host_message_id` 归属**上方旧图**并重新展开流式；旧图完成态跟 execution 自身收口，不随新回合 `message_end`。刷新：旧消息 journal 含完整生长，新消息仅锚点。契约向量 `multi_agent_cross_turn_append`；后端见 [`编排器与CEO主Agent.md` §自选粒度](/docs/03-AI核心/编排器与CEO主Agent.md) |
| 任务完成 | 状态条**收缩**为一行战绩摘要 |
| 用户停止任务 | 状态条转「已停止」，在跑节点冻结，提供重试 |
| 用户发新消息 / 刷新 | 每条回答各持自己的执行槽（按 `messageId` §9.3），历史图保留，刷新后从 `message.runs` 回放 |
| 用户运行中打字（插话 ✅） | composer **不禁发**（废除 `isGenerating` 一刀切拦截）：单一输入框，生成中发送键（「发送插话」）与停止键并存，Enter 即插话；系统按后端 SSE 呈现——协调 turn 内消息以插话形态渲染进 team 块时间线（`UserInterjectionsPanel` / `user_interjection`），徽标「已传达给团队」；CEO 判定无关转排队后同条目翻转为「已排队」+ 处置说明；经典路径 / 单 Agent 运行中则先收 `turn_queued`（排队位次），drain 后**同一 SSE 连接**续流整回合（发送即有流；202 JSON 已退役）。**插话可带附件 ✅**：复用正常发送的驻留 + `OutgoingAttachment` 序列化，徽标下附件名 chips（路径只在线上供团队自取，UI 不展示）。热路挂起仍走决策区，不可绕过 |

**为何无「规划中」态**（决策）：CEO + `delegate` 架构下 `run_plan` 同步到达，无独立规划空窗；「系统在思考」由 CEO reasoning 气泡覆盖；`tool_use_start(delegate)` 前无法预知是否组团，故状态条不设「规划中」态。→ 见代码 `runtime/delegate/`、`runtime/engine/`。

**中间可见性（✅ Phase 1 + Phase 2a 均已落地）**：并行 worker 产出经 `run_output_delta` fold 到 `agent.outputChunks` + per-run `process[]`；协作图节点 `AgentNodeActivity` 显示 `livePreview`；侧栏 `RunDetailBody` 主体为与 CEO 气泡同款的 `ProcessTimeline`（流式交错）。**审查预警**：`lib/reviewConcern.ts` 解析 `7/10`、方向类措辞 → 节点「待关注 / 方向风险」琥珀/红徽章。**一键下钻**：点协作图节点（`GraphArea` `onNodeSelect` → `showRunDetail`）打开该 worker 侧栏（状态条不再设「查看进行中」快捷入口，避免与节点自解释重复）；`RunDetailBody` 进行中提示流式更新 +「记下改法」预填输入框 +「停止整轮」。**跑一半改方向（`run_redirect` ✅）**：`RunDetailBody`「立即改此人」→ 单人 cancel + 热续写 / 冷接手 + 忽略收口（Step 1–4 全 ✅，见 [`多轮编排与同人续派.md` §十](/docs/03-AI核心/多轮编排与同人续派.md)）。**团队便签**：协作图下 `TeamNotesPanel`（可折叠便签墙，运行中有活跃便签默认展开）（见 [`Agent协作模式.md` §便签墙](/docs/03-AI核心/Agent协作模式.md)）。

→ 见代码：`lib/reviewConcern.ts`、`StatusStrip.tsx`、`RunDetailBody.tsx`、`agentNode/*`、`TeamNotesPanel.tsx`。

**检查点卡片（已落地 · 挂起即收口 Phase 3）**：CEO 调 `ask_user`（默认 `blocking=true`）暂停回合、请用户拍板。**内联 `CheckpointCard` 只渲染已决记录**（pending 即 finalize 回合、内联不渲染，CEO 正文保持可见），可操作面统一落在下方 `ResumePrompt`（复用同一 `AskUserCard` 答题体）。**语气**：卡壳统一中性灰（`neutral`，被动记录姿态）、行动信号收敛在 Footer 主 CTA（品牌蓝）；kickoff 走 V2 Brief+Choose（选项 `primary` 选中态）。原「途中味琥珀 `warning`」已随 warning 语义槽位退役（见 `ui/tone-presets.ts`）。历史回合只读。

**开工提案卡瘦身（✅）**：开工提案卡（`ask_user` 开场形态；勿与 `team_preview` 开工卡混称，两卡区分见[术语表](/docs/01-产品/术语表.md)）= **带预填的短表单**，选项必须默认全部可见；渐进披露只用于过目型材料。决策材料紧凑单行；非决策材料（brief/计划 chips/补充框）收纳折叠。**否决**：题目 accordion（曾落地当日回滚）、大内容外置侧栏、Wizard 一题一答。→ 见代码: `ask/AskCommenceKickoff.tsx`

**专用拍板卡两变体（`intent` 判别，2026-07 阶段 3 第 3 件）**：同一 `checkpoint_required` 管线按 `intent` 渲染专用形态，不新增交互 kind——**方案挑选卡**（`intent=proposal_pick`）：候选以「方案墙」卡片阵呈现（方案名 + 一行取舍 + 推荐徽章），单选提交；**风险确认卡**（`intent=risk_ack`）：勾选清单，解析 label 的「[高]/[中]/[低]」前缀做严重度强调（无前缀回退普通行），多选提交，选中项由 CEO 转定向修订。未知 / 缺省 intent 完全走既有 kickoff/decision 渲染；移动端不做专用 UI，自然降级为普通选择卡。

→ 见代码 `components/chat/CheckpointCard.tsx`（`AskUserCard`）；语义与 API 见 [`编排器与CEO主Agent.md` §四/§五](/docs/03-AI核心/编排器与CEO主Agent.md)。

> **为何两态而非三态**（决策理由）：「继续/调整」效果同一，合并为「提交」；保留「停止」安全阀。详见 [`编排器与CEO主Agent.md` §四](/docs/03-AI核心/编排器与CEO主Agent.md)。

**非阻塞发问卡片 `NonBlockingAskCard`（✅ 已落地）**：CEO 调 `ask_user(blocking=false)` 时**不挂起回合**——语气取**品牌蓝 `primary`**，展示问题 + 默认假设 + 选项文案（**无回填 chip**；改口在下方输入框自述即可）。从不挂起、无 pending/resolved 态。

→ 见代码 `components/chat/NonBlockingAskCard.tsx`；语义见 [`编排器与CEO主Agent.md` §四](/docs/03-AI核心/编排器与CEO主Agent.md)。

**结构化挂起卡片 `PlanReviewCard`（✅ 已落地 · 挂起态降级 ✅ 2026-07-21 · 方案 C · resolved 单行折叠 ✅）**：DAG step 带 `checkpoint_after` 时，调度器在**波间**暂停——区别于 CEO 主动 `ask_user`（`kind=plan_review`）。**内联卡为被动记录**：pending 降级为**单行极简标记**（`PendingDecisionMarker`：「等你拍板 · 计划复核 · 入口在下方拍板卡」，不再渲染带「等待确认」标题 + 步骤明细的完整灰卡——完整上下文归 ResumePrompt 拍板中心）、resolved 留痕与 `team_preview` 同壳（`ResolvedDecisionRecord` · `neutralCollapsible`：默认一行「结论 · 角色」，展开见步骤摘要与备注）；**继续 / 调整 / 停止** 的可操作面统一在下方 `ResumePrompt`（`adjust` 备注注入未跑下游，仅备注非空时可点）。`team_preview` 挂起态同一降级形态（「等你拍板 · 开工授权（N 名队员）/ 辩论开赛（N 方）」），resolved 留痕维持折叠一行结论。

→ 见代码 `components/chat/PlanReviewCard.tsx`；语义见 [`编排器与CEO主Agent.md` §四](/docs/03-AI核心/编排器与CEO主Agent.md)。

**统一团队时间线 · 卡片落点（✅）**：过程块按真实时序内联在 `ProcessTimeline`（§一B），**不**堆气泡底。**标记时刻 = 事件发生时刻**；resolve 只更新槽、不另发标记。**升级四态独立落标**（多次分先后）；**否决**「raised 留图不进时间线」与旧「执行级归属槽」。热审批/委派授权 pending 仅决策区可操作、时间线只留 resolved 痕迹；委派授权与开工卡同属「放行开工」族（排协作图前）。**不变量**：有交互卡必有时间线标记（零 live-only 豁免）；查询键 = 投影键。回合级汇总（来源/产物）仍留答案下方。→ 见代码: `lib/processTimeline.ts`

**续跑卡片 `ResumePrompt`（✅ · 唯一可操作面）**：挂起期间仅此处表达「等你拍板」；冷路三 kind 操作面均由此承载。→ 见代码: `components/chat/ResumePrompt.tsx`；语义见 [执行引擎 · 暂停与恢复](/docs/03-AI核心/执行引擎架构设计.md)、[编排器 §四](/docs/03-AI核心/编排器与CEO主Agent.md)。

> **勿与近邻混淆**：工具审批是另一套；CEO `ask_user` 与 DAG `checkpoint_after` 机制不同、UI 相似。

**决策区统一形态（✅）**：结构化决策卡统一 `DecisionCard` 壳，Chat/画布经 `ConversationDecisionPrompts` **单挂载互斥**。**否决**消息流再堆可操作入口。

**阶段推进卡 `StageCard` + Dock（✅）**：跨回合 pending 常驻 Dock；进 process 时间线。→ 见代码: `components/chat/StageCard.tsx`

**统一交互模型 `InteractionStore`（✅）**：8 种问用户卡收口单一 store；SSE + journal + recovery 三路合一；冷路权威在 `pausedTurns`。→ 见代码: `stores/interactions/`；生命周期见 [执行引擎 §8.2](/docs/03-AI核心/执行引擎架构设计.md)。

---

## 四、辩论/审查范式

> ✅ **已落地**：辩论从「`stance`/`round` 展示标记 + CEO 手搓 DAG」升级为「**主持人（Moderator）驱动的逐轮交锋 → 决策简报 + 交锋叙事线双产物**」。完整编排（主持人循环 / 三形态 / 收敛 / 逐轮交互 / 补轮 / 站队会话内态）见 [`辩论编排设计.md`](/docs/03-AI核心/辩论编排设计.md) §六–§七；本节聚焦**前端呈现**。
>
> ✅ **前端重构已落地（2026-07-06）**：交锋叙事前端从「IM 群聊单流」**重建为「辩论室：赛事页」**——记分牌 + 阶段化剧本主列 + 终审舞台三层结构；live 与收场仍是同一条 `toDebateModel` 归一流、无 phase 切换。主视图 `DebateArena`，右坞「辩论裁判台」已解散。行为契约见 §4.1，组件去向见 §4.1b。

### 4.1 辩论室：赛事页（✅ 已落地）

把整场辩论呈现为**体育赛事直播页 + 法庭记录**——三层纵向结构，入口为全屏回合详情「辩论室」tab（状态条**「打开辩论室」CTA** → `TurnDetailPage?view=debate`）。

| 层 | 组件 | 职责 |
|---|---|---|
| **记分牌** | `arena/Scoreboard` | 页首记分牌（**随内容滚动**，不占 sticky 屏）：辩题 / 形态 / 轮次进度 / 章节锚点；正反 VS 阵营 + **模型徽章（全页仅此一处常驻）** + 累计比分 + momentum 微图；红队风险盘口 / 圆桌阵营平铺；**布局开关 `LayoutToggle`**（并排 / 单栏，仅正反）+ **站队控件** `StanceControl` |
| **庭前取证** | `arena/PretrialSection` | 开赛后、首轮前的固有取证阶段区块（✅ 2026-07-21，形态对标证人席）：各队取证员进度 + 场级台账计数；快速档 / 案卷充分显示「已跳过」；协作图上取证员在辩论 compound 内平铺、经边连到本方主辩（`group=pretrial:investigators:{side}`，不入 `debate:` 参与者命名空间、compound 内不嵌套子队盒——2026-07-22 假分带根治）。消费 `debate_pretrial_*`（权威 = completed），设计见 [`辩论编排设计.md §二之二`](/docs/03-AI核心/辩论编排设计.md) |
| **剧本主列** | `arena/Transcript` | **正反辩论**：逐轮 `SectionHeader` → `SpeakerBlock`（立论/续辩/答问/结辩）→ `JudgeNote` → `CrossExamSection`（质询 Q→A，仅 `form=debate`）→ 常驻 `SteeringPanel`。**红队**：交互单元 = **finding**——轮内主列改 `FindingThreads` 英雄区（刺→回应→复核三拍；thorough 另含复攻拍），**不**渲染 `CrossExamSection` / 结辩区块（后端 `form_profile.closing=False`）。**圆桌**：`ThreadTurns` 英雄区（点名串行）。发言格身份色轨 + 阶段词，**无模型徽章** |
| **终审舞台** | `arena/FinaleStage` | 强分隔进入舞台区，内容恒 `max-w-3xl` 居中（split 并排下同样收窄）：「主持人终审」头（**模型徽章** + 收场原因，身份行即钻取）→ **三区 BLUF**（2026-07 重排）：① 裁决卡（正反＝倾向/置信；红队＝门决评定，无加固建议进卡）→ ② 战果对照（正反 `brief/SideOutcomeCompare`；红队 = finding 台账摘要 + 方案方回应，旧 RiskBoard 仅无 findings 时降级；圆桌 = 光谱先行 + 综合观察）→ ③ 留给你的（红队加固建议落此处；按 kind 三种异质形态：value / fact / question，见 [`辩论编排设计.md §4.1`](/docs/03-AI核心/辩论编排设计.md)） |

**已确认决策（沿用）**：

| 维度 | 决策 | 要点 |
|---|---|---|
| **布局** | 赛事页 `max-w-7xl`；正反两方默认**左右并排**（正方左 / 反方右）、记分牌「布局」开关可切 `max-w-3xl` 单栏；红队 / 圆桌恒单栏 | 对抗感靠**阵营色 + 身份色轨 + 记分牌 VS 对垒 + 引用回复**（`ReplyQuote`）；正反另提供**可选左右并排**（仅逐轮发言分栏，轮头 / 质询 / 裁判札记通栏），偏好持久化、长文可随时切单栏 |
| **单流** | 直播与收场同一条流，轮次=章节锚 | 收场 = 主列跑完追加 `FinaleStage`，不是另一个视图 |
| **结论** | 流末「主持人终审」= 唯一结论面 | 记分牌提供「终审 ↓」锚滚动至 `FinaleStage` |
| **落点** | `TurnDetailPage` 平级 tab「辩论室」 | 辩论回合默认落辩论室；「协作图」「对比」同为顶栏平级 tab（§6.5） |
| **记分牌滚动** | 不 sticky | 长文阅读优先：记分牌随剧本滚走；章节 chips / 比分回顶可见，放大态顶栏仍保留任务摘要 |

> **阵营色 = 辩论对立 token（决策·2026-07）**：正反 2 方按语义 key 定死红蓝对垒（`pro=蓝` / `con=红`），专用 token 独立于 `--agent-N` 身份色板；多方（圆桌 / 红队 / subject）仍按名字 hash 分色。→ `debate/model.ts` `debateSideColorVar`（`Scoreboard` / `SpeakerBlock` / `brief/` 同源消费）。

**行为契约（赛事页）**：

| 概念 | 呈现 |
|---|---|
| 辩手发言 | `SpeakerBlock`：左 3px 身份色轨 + 名字 + 阶段词 + 流式/异常态；完成态经 `parseSpeechArguments` 按 `### ` 切**论点大纲**（`ArgumentRow` 逐条折叠 + 「展开全文」回全篇），切不出时回落全宽 `Markdown evidence` + `CollapsibleSpeech` 折叠；发言正文由后端两阶段成稿保证干净（检索笔记不进卡片，见 [辩论编排设计 §4-2.5](/docs/03-AI核心/辩论编排设计.md)），前端**不再**做 preamble 剥除；**无头像圈、无模型徽章** |
| 轮次 | `SectionHeader`：轮号 + 焦点 + 章节锚 |
| 主持人小结 | `JudgeNote`：法槌标 + 小结 + 收敛/交锋信号 + 逐轮净分 chip |
| L3 交锋 | `ReplyQuote`：反驳方发言顶部「↩ 回 X：要点」 |
| 质询 | 仅正反：`CrossExamSection` Q→A（默认折叠）；红队三拍取代质询，圆桌不走通用质询 |
| finding（红队） | `FindingThreads`：每条刺攻/应/复核（+ thorough 复攻）+ 严重度/生命周期徽章（`debate/findings.ts`）；终审台账与门决见 `brief/`；wire 只带结构、全文靠 `run_id`（见 [辩论编排 §三](/docs/03-AI核心/辩论编排设计.md)）；无 findings 旧载荷降级 RiskBoard；**手机端不下沉**线程/地图（极简摘要，同质询/结辩先例） |
| 证人质询 | `WitnessExamSection`：证人席位块（标注「来自幕1·X透镜」）+ 点名 Q→A（答问全文按证人节点 run 取回）；pending 显「待命」、整场未被点名显「未传唤」；机制见 [`辩论编排设计.md` §四之三](/docs/03-AI核心/辩论编排设计.md)，手机 fold/`DebateView` 同构 |
| 用户追问 | `UserInterjection`：右侧条 + 定向 chip；收场标「已承接」 |
| 站队 | **记分牌** `StanceControl`（正反 VS 行旁）；会话内态、不持久化 |
| 掌舵 | 常驻 `SteeringPanel`（fire-and-forget · 下一轮生效）；回显「已发送·下一轮生效」 |
| 决策简报 / 裁决 | `FinaleStage` + `brief/BriefCard`：三区 BLUF（裁决卡 → 战果对照 → 留给你的·handoffs 异质形态），替代旧「倾向头条 + 次级区块全展平」与「三分组同质 bullet + 分类名词标签」 |

**约束**：纯前端渲染层重构，**不动协议 fold / conformance**——`toDebateModel` 读 `execution`、已归一 live+收场（守 [`protocol-conformance.mdc`](/.cursor/rules/protocol-conformance.mdc)）。

→ 见代码 `components/chat/debate/arena/`。

### 4.1b 旧范式退场与组件去向（✅ 已完成）

**现行树**：`arena/DebateArena` = `Scoreboard` + `Transcript`（含 `FindingThreads` / `ThreadTurns` / `CrossExamSection`）+ `FinaleStage` + `brief/`；放大态辩论回合与协作图 / 对比同为 `TurnDetailPage` 平级 tab（§6.5）。

**否决理由（一行）**：IM 群聊单流 / 擂台对开 / 右坞裁判台 / ArgMap 等多套范式表达不了阶段·比分·裁决且抢宽——一律由赛事页三层替代（群聊隐喻与拍板 hero 等历史组件已删，不保留兼容导出）。

→ 见代码 `components/chat/debate/arena/`。

### 4.2 团队图上的辩论标记（✅）

差异化呈现（仅辩论回合触发，普通并行批次零变化）：

| 处 | 现状 |
|----|------|
| 范式标题 | 内嵌图状态条显「辩论」pill、完成态作「辩论完成」（普通为「团队完成」）——`InlineTeamGraph`（`isDebate` = 有 `debate` 产物或有 `stance` runs） |
| 节点 badge | 对立节点显「正方/反方」徽章（`primary` 令牌，与 6 态状态色解耦）——`AgentNode` |
| 图分列对置 | 正/反节点按 `stance` 排序 + ELK `considerModelOrder`，分两带对置——`GraphView` / `lib/elk-layout.ts` |
| 节点层级 | CEO（主气泡，不进图）→ 主持人（完成态节点）→ 辩手（挂主持人下），见 [`辩论编排设计.md §7.3`](/docs/03-AI核心/辩论编排设计.md) |
| 辩论全程 | **不内联聊天**——辩论全程（逐轮发言 + 决策简报 + 交锋，§4.1）归 `TurnDetailPage`「辩论室」tab；聊天侧内嵌协作图**默认展开**（与普通团队同，可手动收起），入口为**醒目「打开辩论室」CTA**；live 与收场是同一条流、无跳跃——`DebateArena`（`debate/model.ts` 归一 live+收场） |

### 4.3 老板介入与追问（✅）

辩论中途介入**复用** [`辩论编排设计.md §六`](/docs/03-AI核心/辩论编排设计.md) 的 ambient 掌舵（steer 队列 + 主列常驻 `SteeringPanel`）：

| 动作 | 前端落点 |
|---|---|
| 继续辩 / 按此角度继续 / 够了出结论 | `SteeringPanel` → `submitDebateSteer`（下一轮边界生效，回显「已发送·下一轮生效」） |
| **追问**某方/全场 | `SteeringPanel` 的【追问输入 + 定向 chip】一并提交（`ask`/`ask_target`）；复盘在 `UserInterjection`（手机 `DebateView` 只读复盘）渲染「你的追问·是否被承接」 |
| 收场后再辩 | 无专用入口——用户在对话框对 CEO 说话，CEO 重开全新辩论（结构化 `debate_seed` / `DebateContinue` 已下线） |

辩论**永不硬停**——无挂起卡 / 无 `DEBATE_ROUND` 交互；追问 verbatim 进 `user_interjections` 可重载复盘。

> ✅ 已落地（§4.1）：常驻掌舵 = `arena/SteeringPanel`；复盘追问 = `arena/UserInterjection`。

### 4.4 站队（✅ · 会话内态）

用户侧轻量标注，**绝不改 AI 裁决内容**（守中立：站队只对比）。store `debateUserTake.ts`（按 `turnId` 分桶）+ 记分牌 `StanceControl`（落点见 §4.1）：

- **站队** `StanceControl`（记分牌正反 VS 行旁）：点选某方记倾向（身份色高亮、仅你可见·不影响 AI 裁决）；终局在 `FinaleStage` 附「你 vs AI」软对照（按**累计净分最高方**是否为你站队方判「看似一致 / 或有不同」，只提示不下硬判）。
- **会话内态、不持久化**：站队仅在当前打开的会话有效，重载 / 翻页即重置（轻量倾向标记，不值得专用持久化基建）。

> **「用户拍板」(gavel) 已移除（2026-06）**：原置顶结论卡展开区的 `GavelActions`（对价值之争选一方上位 / 维持 AI 裁决，并落 `debate_user_takes` 表跨重载持久化）整体删除——纯客户端标注无人消费、与站队职责重叠、专用持久化基建与价值不相称（详见 [`辩论编排设计.md §6.7`](/docs/03-AI核心/辩论编排设计.md)）。要据结论推进，直接对 CEO 下指令即可。

### 4.5 论证地图透镜（已移除）

曾把辩论读成节点（各方 + 最强主张）+ 有向边（各轮 `clashes` 谁驳谁）的 `ArgMap` 次级透镜，**已随「视图过多」收口移除**（2026-06）。攻防结构的逐轮交锋仍可在赛事页 `ReplyQuote` + 记分牌 VS 对垒读到。放大态辩论视图现为 **`TurnDetailPage` 平级 tab「辩论室」**（协作图 / 对比同页切换），见 §4.1b / §6.5。

> **决策演进**：「主持人是 CEO 之下、辩手之上的一层、底层无 debate 专用执行路径」**仍成立**——只是这层落成 `debate` 工具内的确定性循环 + 图上完成态节点，而非一个 LLM 委派角色。旧「多轮 = CEO 手搓跨轮 DAG」**被替代**，见 [`辩论编排设计.md §八`](/docs/03-AI核心/辩论编排设计.md)。

---

## 五、图视图（现状）

**内嵌静态 + 画布放大态探索**（核心 UX 规则）：内嵌 `GraphView`（`embedded` 形态）为**静态预览**——禁缩放交互，滚动对话而非缩放画布；状态条「在画布打开」进入全屏 `TurnDetailPage` 做缩放/平移/回放。内嵌 fit-to-width 定高，节点 face 三层：角色 → 在干什么 → 用时（**工具次数归 hover 速览卡 / run 详情**；**¥ / token 归 run 详情**，§7.3B）。点节点下钻：内嵌图开右坞 `SidePanel` run 详情 tab；**放大态点 worker 同样走右坞 `SidePanel` run 详情——复用同一 `sidePanel` store（节点高亮、退出放大态后右坞仍展示同一 run），端点（用户输入 / CEO 汇聚点）同样开到右坞 `SidePanel`——作「内容 tab」渲染提问 / 最终回答正文（是气泡非 run，故另立 tab 类；画布无气泡陪同，最终回答首入自动开一次）。详情一律向右开、不退出放大态；Esc 渐进收起（先收右坞面板、再退放大态）。内容 tab 是画布专属——离开画布阅读上下文（退放大态 / 切回聊天）自动清掉、run tab 保留，故答案不与对话气泡重复。内嵌图的端点点击仍跳对话气泡（气泡就在阅读列内，无需面板）**。

→ 见代码 `components/graph/GraphView.tsx`、`components/graph/`、`pages/TurnDetailPage.tsx`

**节点身份与重复执行呈现（裁决准则，2026-07）**：图节点 = **一次执行（run）**，非 agent 实体——阶段 1 后端无稳定 worker 实体（`agent_id == run_id`，见 [`编排器与CEO主Agent.md` §Agent 实体化](/docs/03-AI核心/编排器与CEO主Agent.md)）。带现场续派 / 辩论续 beat 等重复迭代场景统一按三分裁决：① **产生独立产出、值得单独下钻或对比的执行 → 新节点**，以链边挂在源节点之后（同人接续链「续 ×N」、辩论续轮「第 N 轮」与结辩列、`replaces_run_id` 接手、普通再委派）；② **轮内从属 beat → 折进宿主节点**（仅辩论质询，见下「辩论 beat 折叠」段）；③ **不产生新执行、只是既有执行的状态变化 → 原节点角标/徽标**（检查点暂停徽标、`plan_revised` 轻痕迹）。**被否决 · 单卡堆叠计数**（原节点挂 ×N 角标代替新节点）：链上对比失去落点（对比透镜依赖各次产出皆为可点节点）、DAG 失真（第二次执行的 `depends_on` 边无处画）、一卡挤多态；**图膨胀一律走折叠**（子队盒 / 质询折进轮节点 / 回合折叠态），不动节点身份模型。**「同一人」文案以接续链为准**：wire `continues_run_id` 存在＝同一作者带现场续干（transcript 续写，[多轮编排与同人续派](/docs/03-AI核心/多轮编排与同人续派.md)），可表述「同一人接续」（peek「接续 {role} 的现场」）；**无接续标记的同 role 再委派仍是冷启动新人**（不继承 transcript，CEO 须在 task 里自包含转述），身份色头像按角色名派生只表「角色延续」心智，**禁止**对无接续标记的同 role 多节点称「同一人」。

### 5.1 模式能力表（✅）

`planType`（`single_agent` / `multi_agent` / `debate`）在图上的能力**一处声明、处处查表**——禁止散落 `planType === "multi_agent"` 等值判断（曾导致辩论回合漏掉审计注入）。表字段：`showsTeamGraph`、`auditInject`、`forceExpandDebateUnits`、`inlineDefaultExpanded`、`revisionBadgeStyle`、`runRedirect`。辩论与 multi_agent 共享 `auditInject`；角标风格辩论为 beat（第 N 轮 / 结辩；质询已折进轮节点）、multi_agent 为同人接续「续 ×N」。

**辩论不开放「改方向」（产品决策，2026-07）**：辩手中途「场边教练」会污染独立对抗的胜负参照（「反方略占优」将混入人为干预），想干预方向应重开一场改辩题；且辩论轮次编排是否消费 redirect 队列未打通。若未来立项开放，前置 = 后端消费路径 + 记分牌/总结的「受指导痕迹」呈现设计。

→ 见代码 `components/graph/planCapabilities.ts`（消费点：`GraphView` / `useCanvasFlow` / `InlineTeamGraph` / `RunDetailBody`）。

**宿主契约（✅）**：三入口（聊天内联 / 画布回合 / 全屏）共用 `graphHost`——Provider、内容包围盒 fit、原点归一化后的 `computeLayout` bbox；全屏 `fitMode=view` 为 fitView 基准。布局失败须显式错误态（`GraphLayoutError`），禁止 `layoutReady` 永假空白占位；不做自动重试。

**嵌套子团队 · 子队盒**：子 worker 经虚线委派边挂父 worker 下、带「子任务」徽章，并由 ELK compound 包成一个虚线**子队盒**（`SubTeamGroupNode`，标「X 子队 · N 人」）；嵌套委派 → 盒中盒。**接续轮归属子队（布局不变量）**：被盒住的成员若有续写轮（辩论/圆桌逐轮＝携 `continuesRunId` 的接续 run），整条接续链归入**同一子队盒**并按网格排（参与者＝行 / 轮次＝列）；归属沿**现场根**（接续链根）解析，R1 起由 `lib/layoutHints.ts` **单源判定**——`buildGraphScene` 输出 `nodeGroup` / `layoutHints`，ELK compound 与投影 `parentId` 同源消费，不再四处各自推导（历史上「归属判定 / compound 子节点 / bbox / 投影 `parentId`」四处漂移曾致续写逃逸盒外、与源之间空出一列 phantom gap）。→ 见代码 `components/graph/scene.ts`（`buildGraphScene`）、`lib/layoutHints.ts`、`components/graph/SubTeamGroupNode.tsx`。

**辩论 beat 折叠与角标（✅ 2026-07 改版）**：认真辩透的对抗辩论里，同辩手的质询 / 结辩也是 `continue_run`（与续轮陈词共用 `round`），但协作图**一列 = 一轮**：质询作答折进同轮陈词节点——状态取轮内最差态（失败 / 运行中优先于完成）、耗时/成本/token 合计、直播中状态条显「立论中 / 质询作答中」且输出预览跟随活跃 beat；**收场**折叠了质询的轮节点状态行挂「含质询」标记（可点直达该轮质询 run；多续写时活跃 > 失败 > 最新），质询作答失败时状态文案归因「质询作答失败」（同样可点）；点整卡仍开陈词/宿主 run。结辩保留独立列。角标读 `run_context.channel`——续轮陈词「第 N 轮」、结辩「结辩」，首轮陈词无角标；「第 N 轮·质询」不再出现在图上（beat 明细归侧栏接续链区段 RunRevisionChain 与辩论室 `CrossExamSection`）。接续链边连可见节点（轮→轮→结辩）。状态条「接续 N 次」只计 CEO 带现场续派 / redirect 热修，辩论 continue_run 不计。**被替代**：初版「质询独立成列」——thorough 3 轮每方 7 列、同质卡片墙。→ 见代码 `components/graph/helpers.ts`（`debateStatementHostId` / `aggregateDebateRoundStatus` / `debateRoundPhaseLabel` / `debateRoundSettledMark` / `pickDebateCrossExamActivateId`）、`components/graph/projectFlowGraph.ts`（折叠聚合）；金样 `multi_agent_debate_multibeat`。

**辩论阶段标签（✅）**：协作图辩论回合在辩手列顶挂「第 N 轮 / 结辩」胶囊标签（`DebateStageBands`）；**无**阶段浅蓝填充/边框（点阵画布、节点边框、连线照旧）。标签锚点只按该列辩手节点居中——第 1 轮不因左侧主持人开场节点左偏。与普通多 Agent 的波次泳道（半透明条）无关。→ 见代码 `components/graph/DebateStageBands.tsx`、`components/graph/scene.ts`（`debateStage` bands 结构派生 + `projectSceneBands` 几何）。

**角色身份（✅ 已落地）**：每个队员节点的头像 = 按角色名**稳定派生**的「颜色 + 首字字形」（`lib/agentIdentity.ts` 用 FNV hash → `--agent-1..8` 身份色板，CJK 角色名首字即天然字号头像「研/工/设」），让一支团队读作「一个个人」而非一排同款 Bot 图标。**身份与状态解耦**：身份在头像盘，运行状态走卡片色环 + 头像角标的「在线点」（运行/完成/失败带小字形，保留非颜色线索），故身份色永不与 6 态状态色抢色（见 `.cursor/rules/color-tokens.mdc`「分类色板」）。

**信息流边（✅ 已落地）**：队员间的依赖边不再只表「先后」，而是据下游 run 的 `receivedContext`（按 `source_run_id` 精确匹配上游产物块）标注**真实交接**——仅在**有损**交接（`摘要` / `递指针` / `截断`）时挂一枚小标签，`全文`（pass_through）交接保持干净线，故标签精准落在「队友只拿到了不完整产物」处；hover 标签看「来自 X · 保真度 · N 字 · 是否截断」。纯渲染层派生（`GraphView` `flowEdges` + `StepEdge` 的 `EdgeLabelRenderer`），**不改协议 fold / conformance**。

**审计数据流高亮（✅ Phase 2）**：`multi_agent` / `debate` 回合经 `useTurnAudit` 读 `causal_graph` inject 边（能力表 `auditInject`）——**打开某 run 详情时**（`litRunId`）高亮该 run 的 inject 入/出邻域（与 dep 重合则加粗原箭头、不画二线；仅 audit 有 inject 时补虚线）；其余边/节点变淡。工具栏可选 toggle「始终显示审计数据流」（默认关）。与 run 详情「数据从哪来」同源。桌面 UI **仅展示 inject**（`parent` / `depends_on` 与「关系」/协作图 dep 边重复，不另画）。**已否决**：全量 inject 虚线叠加 · Run 详情迷你 DAG · ELK 为 inject 重布局 · 用 audit 替换 handoff 标签 · conformance 变更。→ 见代码 `lib/causalInject.ts` · `planCapabilities.ts` · `GraphView.tsx` · `StepEdge.tsx`。

**波次泳道（✅ 已落地）**：协作图按**拓扑依赖层**（Kahn 分层 `computeTopologicalRunWaves`，镜像后端 `RunPlan.waves`，≠ 运行时调度时刻）在节点后方画半透明泳道 + 「批次 N（M 节点）」标签，让「团队分轮推进（并行扇出 → 汇总 → …）」一眼可读；**单波（纯并行扇出）/ 单 Agent 不出泳道**，简单回合保持干净；端点（用户输入 / CEO 汇聚点）在泳道之外。经 `ViewportPortal` 在画布坐标系渲染（泳道 z-index -1 沉底、标签浮顶），随平移/缩放联动。→ 见代码 `components/graph/scene.ts`（`computeTopologicalRunWaves` + lane bands 结构派生；`GraphView` 经 `projectSceneBands` 渲染）。

**同回合多次 `delegate` 泳道（✅ 已落地）**：CEO 同回合再委派会合并进同一 `execution_id`（`mergePlanInto`），跨批常无 `depends_on`——拓扑波次会把不同委派的根节点编进同一「批次」列，抹掉「先后追加」叙事。呈现层在 ingest 时给 plan run 盖 `delegateBatch` 戳（**不进协议 / ProjectedTurn**）；当可见顶层 worker 跨 ≥2 次委派时，泳道改标「第 N 次委派」并沿交叉轴分条（不画假依赖边、不合并节点、不把同 role 写成「同一人」）。单次委派仍走上方拓扑波次泳道。

**hover 速览卡（✅ 已落地）**：hover 队员节点弹一张**比 face 更详、比右侧面板更轻**的速览（角色 + 状态 + 分类标记 + 任务 + 更长的「在做 / 产出」预览 + 模型·token·用时·工具 一行），补「节点 face → 完整面板」之间的渐进披露层；复用 face 同源信号、只给更多空间，不新增数据通路（模型档 / 力度徽标已随档位删除下线）。→ 见代码 `components/graph/AgentNode.tsx`。

**产物落点 chip（✅ 已落地）**：节点据自身**已提交**的文件工具调用（`file_write` / `str_replace`，按 `path` 去重、保首写顺序）派生「这个队员产出了哪些文件」，在 face 上挂文件 chip（📄 + 文件名，face 最多 2 个 + 「+N」溢出，hover chip 看全路径），速览卡列更多（至多 6 + 溢出）、aria-label 播报「产物 N 个」。**只算 `success` 调用**（失败/中止的写入不落产物），且与中行的「正在生成」分离——chip 是已落盘成果，中行是进行中的写入；纯渲染层派生（`GraphView` `deriveArtifacts`），不改协议。→ 见代码 `components/graph/GraphView.tsx`（`deriveArtifacts`）、`components/graph/AgentNode.tsx`。

**可达性与多选**：节点 `role=button` + `tabIndex` 键盘 focus + Enter/Space 激活 + `aria-label` 播报角色/状态/模型/Token/成本/用时/工具/产物；支持多选（修饰键加选 / 框选，`selected` 与面板下钻高亮共用 outline）。**动画 / 布局选型理由**：状态过渡用纯 CSS（**否决 Framer Motion**——零依赖、与 React Flow 定位 transform 无冲突）；ELK 仅留左右流 / 树形（径向 / 力导向曾实现、小团队下无价值已移除）；右键菜单复用 `sidebar/ContextMenu`（无需 Radix）。

**结构化挂起图徽标（✅ 已落地，Phase 2a）**：`plan_review_*` 事件入 journal 后，execution fold 按 step `run_id` 折进 `RunNode`；在检查点步骤的 `AgentNode` 上挂暂停徽标（⏸ + 待放行/已放行/已调整/已停止）。**否决独立 `CheckpointNode`**（step 与下游之间插入合成节点 + ELK 重布局）——视觉更突出但代价显著，徽标已满足「图上可见检查点」；独立节点留作后续 richer 形态。→ 见代码 `stores/execution/`（`RunCheckpoint`）、`components/graph/AgentNode.tsx`。

> 多轮辩论用普通 agent 节点（主持人 + 辩手，✅ 见 §四），无独立 arena 节点。**已否决·工具点节点**：每个工具调用单独成图节点 = 与「inline 只做信号、面板承担完整详情」+ §八 ≤50 节点性能约束冲突（一个调研 agent 调 10 次 `web_search` 即 +10 节点）；工具已被 agent 节点「工具数」+ `SidePanel` run 详情 `ProcessTimeline` 工具步覆盖，无需独立节点。

> **看懂协作（产品手册）**：`工具箱 → 产品手册 → 看懂协作（选读）`（`/toolbox/manual/mechanism`）。面向用户的协作透明章，用真实图组件标注机制含义；纯用户向，**否决**页内开发者细节开关（运行时全景/协作回合等叙事一律用户视角，无实现术语）。→ 见代码 `components/manual/MechanismContent.tsx`（真图件）、`pages/toolbox/manual/content/mechanism.ts`（叙事内容源）。

---

## 六、聊天 ⇄ 画布双视图 ✅ 已落地

多 Agent 协作图从「聊天消息里内嵌的一个组件」（`InlineTeamGraph`，§三）升级为可与聊天**平起平坐的第二视图**——一块「画布」。已**毕业**（原实验开关 `canvasEnabled` 已撤）：入口恒显示、无需开启；**对话页恒为传统聊天**（早期把对话页也卡片化的第一刀已撤，见 §6.4），画布是按对话 opt-in 的第二视图。

**核心论点 · 一份数据两种渲染**：后端单 Agent = 只有 Captain 的退化 Team、单 / Team 同一执行路径（[`Agent协作模式.md §设计哲学`](/docs/03-AI核心/Agent协作模式.md)）这条洞察只用在**数据层**——同一份「回合 + 执行（CEO+worker DAG / journal）」既可渲染成聊天、又可渲染成画布。两视图同源 `projectExecution` fold，**切换 = 换视图不换数据，不动协议 / `turn_journal` / conformance**。

| 视图 | 渲染 | 默认 |
|---|---|---|
| 聊天模式 | 回合 → 气泡 + 内联协作图（团队回合就地开花，§三） | ✅ 默认 |
| 画布模式 | 同一批回合 → 单张持久空间画布 | opt-in |

**默认聊天 + 显眼入口**：差异化靠「团队在该出现处就地开花 + 一步进画布」，不靠强迫所有人上画布——聊天里一起团队即内联出图（`InlineTeamGraph`），其上「在画布打开」主按钮一键切到画布；顶部 `聊天 / 画布` 分段切换按对话记忆视图模式（`conversationViews`，**持久化** `localStorage: agentcore:conversation-views`、只落画布 override 切回即删键）。

### 6.1 画布 = 单张持久画布（视觉累积，非 worker 实体化）

一个对话 = 一张可平移画布，每回合自上而下**跨回合视觉累积**成节点；「同一拨人」靠 `agentIdentity`（同角色稳定色 / 字，§五）延续，**团队仍每回合临时组、不做 worker 实体化**（真持久团队见 §6.4 否决）。

**LOD「只有聚焦回合画完整 DAG」**（守 §八 ≤50 节点 / ≥60fps）：完成的团队回合塌成「回合摘要节点」（状态 / 任务摘要 / 身份头像 / 进度）、单 Agent 回合塌成竖排轻卡（`SimpleTurn`），**恰好一个聚焦回合**（默认最新、自动跟随新回合、点摘要可切换）就地展开完整 worker DAG；配小地图 / 相机。聚焦回合内嵌整套 `GraphView`（点 worker 走右坞 run 详情、点端点〔汇聚点读最终回答 / 用户端点重读提问〕开右坞「内容 tab」）+ 就地脚抽屉（仅承表头 chip 唤出的「版本对比」比对；辩论回合无 peek、全程走放大态「辩论室」），深读 / 放大走**画布放大态**（Route A · `TurnDetailPage`，就地放大该回合、非独立 overlay）。**团队便签**（与聊天 `TeamNotesPanel` 同源，取聚焦回合 `Execution.teamNotes`）：聚焦回合图下方就地展示便签墙（执行中且有 `active` 便签默认展开，已完成/已停止默认收起为「便签 N」可点展开）；非聚焦摘要节点有便签时只亮「便签 N」chip、无便签不渲染——**不**做成图上可拖节点、**不**进指挥台主区、**不**混白板 spatial sticky。**点 `SimpleTurn` 轻卡 → 右坞开 `simple-turn` Q&A tab**（一次展示该回合完整「提问 + 回答」Markdown，不离开画布；无 execution，故不走 `showRunDetail` / 不硬套单气泡 `content` tab——后者 live 校验依赖 plan）。命令栏 `CanvasCommandBar` 常驻画布概览底栏（**仅此一处**；放大态为纯深读页、不设命令栏，见 §6.5），且与聊天输入框**统一为同一 composer 核**（`TurnComposer`，2026-07）：附件 / @ 文件引用 / 停止生成 / 字数 / 回填通道两视图同款，草稿按对话存 store、聊天 ⇄ 画布切换不丢，正文并持久化 localStorage（重启不丢；附件仅会话内，防配额且盘上易过期）（`MessageInput` / `CanvasCommandBar` 只是两层皮）。**对话页（聊天视图）恒为传统聊天**——不再把单 Agent 回合渲染成节点卡，图相关体验收敛在画布（原「对话页卡片化」第一刀已撤，见 §6.4）。

### 6.2 图上指挥：指挥台 `CommandRegion`（统一侧面板顶部常驻区）

画布一旦成为管团队的地方，检查点 / 发问 / 审批 / 续跑 / 救火这些**老板权力**必须能就地行使（一个「掌管团队」的视图不可能只读）。落地**不**逐个塞进节点，而是把指挥台收口为**统一侧面板（§十）顶部的可折叠常驻区** `CommandRegion`（面板标题「指挥台」，徽标计待裁决数；不再单开第二个右坞，取舍见 §6.3）：

- **双作用域同处一面**：回合级（`ask_user` 检查点 / `plan_review` / 工作者上报 / **救火行**）随**聚焦回合**的 message + 投影执行渲染；对话级（工具放行 approval / 待恢复续跑 resume / **传输错误重试 `RetryBanner`** / **后台云端任务 `BackgroundTaskCard`**）自带 store + 当前对话自渲染。画布模式下 `ChatView` / `InlineTeamGraph` / `MessageList` 未挂载，其对话级卡片、救火行与时间线内的后台任务卡本会**消失且无法操作**——故必须在统一侧面板的指挥台区（`CommandRegion`）承载。
- **救火**（失败重试 / 已决策·执行中断续跑）：聚焦回合终态有失败（整轮崩 / 部分失败 / 已停止）或 interrupted store 命中时，指挥台渲染聊天同款 `RecoveryActions`（行内文字链接：interrupted → **继续**；部分失败只出 **重试失败项**，否则只出 **重试**；无显式忽略——新 turn 隐式收口）；外加对话级 `RetryBanner`（发送 / 续跑 / 重生成断流的传输错误重试）。聚焦节点头另挂一枚「待救火」红牌。
- **后台云端任务**（非阻塞 · 跨对话的「另一类」）：本地模式对话的云端交接任务（`BackgroundTaskCard`，§十）原按时间戳并入聊天时间线；画布无时间线，故收进指挥台**末尾**（卡片自带派发 / 运行 / 失败状态 + 完成后「查看并应用」内联评审）。**不计入「待你拍板」**（非决策、不污染节点徽标），但其存在 / 新到一项会自动浮出指挥台；轮询同步由常驻的 `ConversationCanvas` 驱动（指挥台收起时仍刷新，故计数能反过来浮出面板）。发起侧：画布命令栏 `CanvasCommandBar` 也带「后台云端」开关（仅本地模式对话亮出），可在画布里直接派发，走与聊天**同一** `dispatchBackgroundTask` 通路、结果即落本指挥台。
- **逐字复用聊天同款卡片**（`CheckpointCard` / `PlanReviewCard` / `EscalationCard` / `ApprovalPrompt` / `ResumePrompt` / `RetryBanner` / `RecoveryActions` / `BackgroundTaskCard`，§三），操作经**同一**服务 + SSE 折叠（守单一数据源、不开第二条通路）；决策提示卡（审批 / 委派授权 / 续跑）经 `ConversationDecisionPrompts` **单挂载**——Chat 与画布互斥复用同一实例，消灭「同屏两套可操作卡」；`interactive` 取聚焦回合 `isStreaming`，重载 / 已结束回合的卡片呈被动记录。
- **数据来源（画布→面板桥）**：转 focus 是画布概念，故 `ConversationCanvas` 经 `stores/commandPanel.ts` 只发布「画布已挂载 `active`」+「聚焦团队回合 id」；区自己从执行 / **InteractionStore（§三统一交互模型）** / resume / 后台任务各 store **现取**派生（单一数据源、不拷快照）、自管自动浮出。`active` 是画布专属门——聊天模式恒 false 故区不出现（聊天的决策本就内联在消息流）。
- **自动浮出 + 折叠（非关闭）**：聚焦节点头部「待你拍板 N」/「待救火」提示牌指向指挥台；有待裁决项（回合级计数 + 对话级 approval + resume）、可救火（聚焦回合失败 / 对话传输错误）或有后台云端任务时，**每来一个全新待办都自动展开本区并揭示侧面板**（`openPanel` 只开 dock、**不切**你当前 tab，故正看的 run 详情不被挤走），焦点切换 / 新项到达再武装（重展开）；用户可经表头 chevron **折叠**成一条（仍亮角标），但**关整个面板**走侧面板自身的 X / `Ctrl/Cmd+I`——折叠 ≠ 关 dock。区高**封顶约 55%** 面板内容高 + 区内滚动，故下方 tab 体（run 详情 / 工作区）恒留可用高度。

### 6.3 关键决策（代码看不出的取舍）

- **双视图而非「图即唯一界面」**：原方向「无模式切换、聊天 = 图的退化渲染、最终砍掉聊天列」**已撤**——强迫简单问答上画布是负体验，且整方案命悬「画布必须像聊天一样轻」的试金石。双视图（聊天默认 + 画布 opt-in）零门槛天然、风险降到「加一个视图 + 一个开关」、**聊天永不删**；「聊天 = 图的退化渲染」只保留在数据层。
- **画布已毕业（撤实验开关）**：原 `canvasEnabled` 实验门为开发期守「画布像聊天一样轻」试金石而设；试金石已过（聊天默认零回归 + 画布 opt-in 顺滑），故撤门——入口恒显示、无需开启，免「藏命令面板后没人发现 + 永远 dogfood 不到」。每对话视图偏好随之由会话内存态**升为持久化**（`localStorage: agentcore:conversation-views`，只落画布 override、切回即删键 → 表恒收敛），刷新 / 重开对话记得上次停在画布还是聊天。
- **内嵌 DAG = 嵌套 ReactFlow**：聚焦回合把整套 `GraphView` 包进外层画布的自定义节点，靠**独立 `ReactFlowProvider` 隔离 flow store**；内层 `embedded` 弃自身平移 / 缩放、外层画布独占平移 / 缩放 / 小地图。→ 复用既有图构建，不重写第二套图。
- **聚焦节点固定高度**（`FOCUS_NODE_HEIGHT`）：脚抽屉（仅「版本对比」；读答案 / 重读提问已改走右坞「内容 tab」，辩论回合走放大态「辩论室」无 peek）与内嵌图**共享这块固定高度**（开抽屉图区缩、抽屉占下半承版本列 `DRAWER_H`、图区相应再缩），节点总高恒定 → 下方回合堆叠偏移不被挤动。**否决**抽屉撑高节点（触发动态高度 → 重算堆叠）。
- **面板停靠 ≠ 节点弹层**：可裁决 / 救火卡片体量大（表单 / 备注 / 多按钮），浮节点上会挤爆 LOD 视图；故收口到**统一侧面板顶部的指挥台区**、聚焦节点只留「待你拍板 / 待救火」提示牌指过去。
- **指挥台并入侧面板顶部区，而非第二右坞 / 并列 tab**：并排双右坞吃 ~760px + 双边框双开关；做成侧面板里的**并列 tab** 又有三患——切 tab 互斥故看不到「指挥台 + run 详情」同屏、自动浮出会抢走你正看的 tab、还得给「指挥台 tab 钉到哪个回合」一个别扭答案。**顶部常驻区**（封顶 + 折叠）让两块同屏可见、自动浮出不抢 tab、两套定位逻辑（区跟随聚焦回合 / tab 按 message 钉）互不干扰。

### 6.4 守住的决策 / 被否决 / 暂不做

**守住**（不因双视图推翻）：CEO 智能路由**不给选择器**（画布只让你在 CEO 组好的团队上行使老板权力，指挥 ≠ 替 CEO 组队，§十一）；节点 ≤50 / ≥60fps 靠 LOD（§八）；节点 face 极简（数字归 run 详情）；简单任务零噪音（聊天默认 + 画布退化竖排双重守住，§三）。

| 方向 | 处置 | 理由 |
|---|---|---|
| 图即唯一界面 / 无模式切换 | 撤 | 见 §6.3 |
| 对话页卡片化（单 Agent → CEO 节点卡 / 团队图聊天内就地读，原画布实验第一刀） | 撤 | 把传统对话页改成卡片是早期理解偏差；图相关体验收敛到「画布」opt-in，对话页恒为传统聊天（删 `CeoNodeCard` + `AssistantMessage.isSoloGraph` + `InlineTeamGraph` 聊天就地读） |
| 丙 · 自适应默认（按有无团队自动切模式） | 否决 | 中途翻模式 = 错愕；「何时切」判据含糊 + 每对话模式偏好状态边界多；收益小（简单回合本就退化轻卡）。改用「显眼内联入口」达成同等「画布在相关时出现」 |
| 乙-2 · 真持久团队（worker 实体化） | 暂不做 | 「团队跨回合」真需求 = 连续性 / 团队懂我，已由记忆模块 + CEO 跨回合记忆 + 共享工作区覆盖；worker 实体化撞「无选择器 / 每回合自适应组队」赌注（[`执行引擎架构设计.md` §受监督的波循环](/docs/03-AI核心/执行引擎架构设计.md)），是定位级（养成系）改动 |
| 跨对话 / 工作区 / 公司级空间画布 | 不在范围 | 本特性只管单对话内双视图（原『公司画布』上层提案已删除） |

**✅ 收口**：图上指挥与比对卡片已全数上画布——`BackgroundTaskCard`（云端 / 后台任务卡片，非阻塞 · 跨对话的另一类）入指挥台（见 §6.2）；「链上对比」**已彻底移出聊天正文**（2026-07，与辩论「过程归画布、正文只留信号」对齐）（`compare/TurnCompare`，2026-07，§6.5）：正文不再内联对比大卡，改由状态条**「接续 N 次」信号 chip** 深链画布；画布两处落点——**放大态「对比」视图**（`TurnDetailPage` 视图切换器，§6.5）承载完整对比（**仅非辩论同人接续链**：胶片轨 + 聚焦精读 + 按需 2-up + 相似产出自动文本 diff；辩论的两方对照由辩论室可选左右并排布局承担、见 §4.1），**概览聚焦节点脚抽屉**（表头 chip 唤出·仅非辩论接续）作就地 peek，二者共用同一 `TurnCompare`、逐次产出仍下钻右坞 run 详情。至此聊天正文只留信号（辩论 pill /「接续 N 次」chip）+ 入口 CTA，过程产物全归画布（带现场续派本身仍 CEO 驱动、无用户触发入口，其结果另作「续 ×N」`AgentNode` 节点画在聚焦回合 DAG 上）。

→ 见代码 `pages/TurnDetailPage.tsx`。

### 6.5 放大态视图：协作图 / 辩论室 / 对比 ✅ 已落地

放大态（`TurnDetailPage`，路由 `/conversations/:id/turn/:turnId`）顶栏给一个**视图切换器**（≥2 个可用视图才出现），同一回合在多种渲染间切换，**按回合性质分叉**：

- **辩论回合**：**辩论室**（赛事页 `DebateArena`，§4.1）为默认内容主视图；**协作图**与（若有接续链）**对比**同为顶栏**平级 tab**——不再是头部浮层 `graphOverlay`。两方对照仍可由辩论室内可选「左右并排」布局承担（仅正反 2 方 · 记分牌「布局」开关，§4.1）。
- **非辩论回合**：**协作图**（依赖结构，默认）/ **对比**（统一对比透镜 `compare/TurnCompare`，**仅同人接续链** → 产出轨〔`RevisionOverview`，胶片轨 + 聚焦精读，下文〕；点任意两格进共享精读对比面〔`ComparePane`，2-up / 真·文本 diff〕；仅当本回合有接续链，§6.4——聊天正文已不再内联，改由状态条「接续 N 次」信号 chip **深链**首挂直达）。

默认：辩论落辩论室、非辩论落协作图；聊天「回放」深链落协作图并自动帧回放；**对比恒为可选透镜、从不作默认**（可经信号 chip 深链首挂直达）。

**放大态无命令栏（2026-07）**：放大态是**纯深读 / 回放页**——不挂对话级 composer 与「下一步」chips，指令输入只在对话正文与画布概览两处。理由 = 作用域一致：composer 派发的是**对话级新回合**，而放大态展示**单个回合**（回放旧回合时底部却能派发全新回合、还触发跳转，对象错位）；且放大态本就不承载指挥台 / 决策卡，辩论直播的掌舵 / 追问自在赛事页内（§4.1）。随命令栏一并移除的还有其派发后「自动跟随新回合」跳转。补偿：**所看回合本身**在直播时顶栏出一枚「停止」（作用域 = 本回合，非「对话在生成」）；回正文 / 画布下指令 Esc 一键即达，草稿在同一 composer 核按对话共享、不丢。

**协作图两种布局（用户偏好持久化 `stores/graph.ts`）**：放大态与非嵌入 `GraphView` 右上角 toolbar 切换——① **左右流**（默认，ELK 横向依赖 DAG）② **树形**（ELK 纵向）。依赖布局背景的 `WaveLanes` 标签为 **「批次 N」**（拓扑依赖层，≠ 调度时间；同回合多次委派时改标「第 N 次委派」）。**帧回放**（左下 HUD `CanvasPlaybackControls`）在两种依赖布局下均可用。Toolbar 旁仍可挂 **`metricsSummary` chip**（峰值并发 · 总时长 · 串行化次数，来自 `batch_metrics`）。内嵌聊天列 `GraphView`（`embedded`）不展示布局 toolbar。曾有时间轴布局、因视图收口删除；时间真相改由诊断 SchedulingDiag / `batch_metrics` 聚合。

**链上对比版式 · 胶片轨 + 聚焦精读（多轮不崩）**：一条接续链可累积很多次产出（同人接续：一个 worker 被 CEO 多次带现场续派），故 `hasRevisions` 为真——此产出轨 `RevisionOverview` 现**仅承载非辩论的同人接续链**（辩论回合含多轮辩论虽也走 `continuesRunId` 接续建模〔轮次由 wire `round` 声明，`stores/execution/debate.ts`〕，但其两方对照由辩论室可选左右并排布局承担、不进对比 tab，见 §4.1）。等分并排到多轮必崩（每列挤成几个字、还各自纵滚）。故每条链渲染为**产出轨**（`v1…vN` 缩略卡：状态点 + `原始/最新` + 字数 + 两行预览，多轮只让轨**横向滚动**、绝不挤压阅读区）+ 下方**聚焦 / 对比区**：默认 **2 次产出直接进「对比」**（经典并排）、**3+ 次聚焦最新产出全宽精读**；**回合级「对比两版」开关**：开启后所有链只留轨，缩略卡可**跨链勾选任意两格**（`A`/`B` 徽标带角色名，**可跨方/跨角色**——支持方 v3 × 反对方 v3、撰写员终稿 × 审阅员意见…），默认 **≥2 方＝两方各自最新互比、单链＝原始×最新**；下方**共享对比面板** 2-up 并排、两段全宽可读（不对比时保留每条链的轨+聚焦精读）。**真文本 diff（自动开）**：两段读起来像同一交付物的「编辑」时（`looksLikeEdit`：共同首尾够长 + 长度相当）自动开 `@codemirror/merge` **侧栏 diff**（未改处折叠、增删分色、跟随亮 / 暗），可一键切「渲染」；**跨角色内容本就不像编辑 → `looksLikeEdit` 判否、走 2-up**（不按内容类型一刀切——某链 v3 × v5 若确是延写微调也给 diff）。同一角色跨次产出、跨方 / 跨角色**任意两段**都能比，共用此精读对比面 `ComparePane`。承载页 `TurnDetailPage` 统一「对比」页用 `max-w-5xl`（比阅读列宽，给 2-up / diff 更多地方）。

**调度时间数据仍在**：`WaveScheduler` 每节点的 dispatch/finish 时刻随既有 `batch_metrics` SSE/journal 折到前端 `execution.batches[].timeline`（`NodeTiming`）。协作图不再用它做布局；聚合指标（平均并发 / 槽位等待 / 自我纠偏边界）只在诊断模式的 run 详情「调度」块出现（§十 · `SchedulingDiag`）。Toolbar `metricsSummary` chip 仍可读同一份数据的一行摘要。**桌面专属**：移动端 fold no-op `batch_metrics`、不进 conformance `ProjectedTurn`。

> 注意：本节是**单回合内 worker 并行**的调度指标，与 §十五「多任务同时进行」（多个任务 / 会话**跨回合**并行的总览面板）是两件事，后者仍 ⏳。

→ 见代码 `pages/TurnDetailPage.tsx`。

---

## 八、图视图技术选型

**被否决**：
- **D3**——与 React DOM 模型冲突；节点内容复杂（进度条/多行/状态灯）SVG 手绘极痛苦；丢失 React 组件复用与状态管理。
- **自研画布**——图视图非核心壁垒（编排器才是），自研需 1–2 个月，资源错配；50 节点不需要 Canvas/WebGL 极限性能。

**性能约束**：节点 ≤50、≥60fps、首屏 <200ms、布局计算 <100ms。

---

## 九、文件交互设计 ✅ 已确定

> **项目即工作区**：两个入口——① 对话内工作区面板（SidePanel）；② 文件中枢 `/files`（VSCode 式左树右详情，跨项目全局，承载项目生命周期）。`/conversations` 仅按项目筛选，项目增删改归 `/files`。技术细节 → 见 [`前端技术与架构.md` §8](/docs/04-前端/前端技术与架构.md)；后端契约见 [`双模式工作区.md` §九](/docs/02-架构/双模式工作区.md)。

**设计原则**：一棵以本地授权目录为根的树。**被否决**：「云端/本地两平级源」上下分段——心智割裂 + 主次写死。

| 交互 | 行为 |
|------|------|
| 添加文件夹 | 选本地目录 = 立即成为一个项目（建云端身份一步到位） |
| 展开目录 | 懒读子项 + 启动 watch；折叠即停止 watch |
| 内联改名 | 就地 input，回车/blur 提交，Esc 取消 |
| 拖拽移动 | 落点校验（非原父/非自身子树） |
| 右键菜单 | 普通节点：新建/下载/打开/重命名/删除（共用 `FileTree`）；**工作区根节点**（文件中枢 `FileWorkbench`）：重命名/删除/新建文件·文件夹/上传/查看对话（跳 `/conversations` 筛该项目）；根级「设为项目」已隐含（加文件夹即建项目）；项目工作区位置**创建时定、不可改**（无「连接/断开」，本期不做 relocate） |

**工作区删除 vs 对话整理（✅ 已确定 · 对标 ChatGPT/Codex 分层）**：**对话层**——归档（可恢复，隐藏活跃列表）/ 永久删除（用户视角不可恢复），见 §一；**工作区（Folder）层**——**不做「归档项目」**（行业亦无独立概念），侧栏降噪靠**组头「归档全部对话」**（批量归档该项目下活跃对话）或在 `/conversations` 按项目批量归档。**删除项目**（`/files` 工作区根右键 + 侧栏组头「删除项目…」· 现有 `folders` soft-delete，共用 `DeleteFolderDialog`）：仅删容器——其下对话**固定归档**、**不**删对话记录；项目文件归 Folder 所有，保留至保留期（默认 30 天，见 [`双模式工作区.md` §七](/docs/02-架构/双模式工作区.md)）后 sweeper 物理清理。**否决** ChatGPT 式「删 Project 级联删全部聊天+文件」——真实工作区（本地盘 + OSS）下对话是索引、文件是资产，级联过狠。**否决** `Folder.archived` 第三整理层。**删除确认**（✅ 已落地）：主对话框两行说明（对话归档 + 文件约 30 天清理）+「取消 / 删除项目」；底部链「需要立即清除全部数据？」进入第二步二次确认（无输入项目名）。软删路径固定归档其下对话。**「彻底删除项目」**（✅ 核按钮、第二步）：一次性清对话+文件+快照（`DELETE /v1/folders/{id}/permanent`）；本地项目不删用户磁盘文件。→ 见代码 `components/folders/DeleteFolderDialog.tsx`、`agentcore/folders/permanent_delete.py`。

**审批 UX（写操作）**：只读时尝试写引导开启；可写时写前弹审批（可「本轮内都允许」按同名工具、或「本轮内允许所有文件改动」按整类一次放行——类成员单源 = 后端 `approval_class_tool_names()`（文件改动五工具 ∪ `git` 写入），依赖工具审批两态的 `grantable` 级别，避免 N 次写/改/删 = N 次弹窗）。

**对话落点表达（✅ 项目=工作区 · 单一「在哪工作」入口）**：草稿输入框工具行只挂一个 `ComposerWorkspaceChip`。菜单：快速对话（= 云端草稿·桌面/web 默认）/ 本机草稿（桌面显式·落本机容器走本地引擎）/ 项目列表（名称+位置副文）/ 新建项目…。选定后 chip 显示单一事实（如「快速对话」/「项目名 · 本地」）。草稿意向为判别联合 `draftWorkspaceIntent`（quick_local / quick_cloud / project）。**新建项目**（桌面）锚点级联菜单（左栏三行）：本机文件夹（右栏搜索 + `listRoots` 路径列表，底部分隔「打开其他文件夹…」；点选或系统选完即建，名=目录名）/ 本机空白（命名 → `~/Documents/AgentCore/<名>`）/ 云端空白（命名）；Web 仅云端空白命名。入口统一（chip「新建项目…」、侧栏项目区 `+`、命令面板「新建项目」）锚定触发按钮。已建会话只读展示工作区；无会话级「绑定/断开」；不支持事后移入/「在项目中继续」。**否决**：菜单并列「打开本地文件夹…」（与新建终点重复，能力在「本机文件夹」右栏底）；大 Dialog 填表。**B4** 附件提示 `DraftWorkspaceAssignPrompt` 仍适配新 store。→ 见代码 `ComposerWorkspaceChip.tsx`、`CreateFolderMenu.tsx`、`DraftWorkspaceAssignPrompt.tsx`、`stores/folders.ts`。

**隐私承诺**：默认不留存（未备份内容不进云）；在途可用（读文件时正文临时发给模型）；备份/分享 = 显式上传（不自动同步，操作前明示）。

**AI 产物默认阅读态 · 可编辑**：工作区面板点开 `.md/.markdown` **默认渲染预览**（阅读优先——点开先看渲染内容，编辑为次级动作），分发唯一出口 `FileDetail`。可写 md 点「编辑」进 CodeMirror 源码（编辑/预览切换、CAS 写盘、选区 AI 改写）；只读 md 也默认渲染（截断的 md 回落源码 + 截断提示）。→ 见 [`前端技术与架构.md` §八](/docs/04-前端/前端技术与架构.md)（`lib/fileSource.ts`、Markdown 编辑）。

**网页产物预览（✅ 已落地）**：工作区面板选中 HTML 与其他文本文件**一致显示源码**（编辑 / 写入归因同权），顶部横幅指路完整效果，CTA 按能力递进：完整预览 → 在浏览器打开 → 下载兜底。完整效果两个出口——①「**完整预览**」= SidePanel「预览」tab 内置浏览器（应用内完整跑 JS + 多文件相对引用，外壳只读地址 + 后退 + 刷新 + 关闭，仅桌面云端会话源出现）；②「**在系统浏览器打开**」（快照解压临时目录，完整效果兜底）。聊天「产出文件」卡点 HTML 产物**直达**完整预览 tab（能力判定与对话侧栏同一套 `useConversationFileSource`，无能力回落文件源码视图）。预览 tab 与工作区/终端 tab 同排、可关闭、切会话自动关闭；页面里的外链点击转系统浏览器（应用内永不离开工作区产物）。原面板内**静态快照**（sandbox srcdoc，不跑 JS）已整体取消——「像效果又不是效果」的半渲染让用户误以为产物坏了，源码视图 + 真浏览器出口更诚实。隔离与遮挡机制 → [`前端技术与架构.md` §9.12](/docs/04-前端/前端技术与架构.md)。→ 见代码 `components/workspace/{FilePreviewView,EmbeddedPreview}.tsx`。

**回合内文件呈现（✅ 已落地）**：**文件产物内联卡**——回合若写了文件，答复正文下方挂一张 `FileArtifactsCard` 列出本回合产物，点行经 `useSidePanelStore` 在工作区面板预览，HTML 产物在会话具备内置浏览器能力时直达「完整预览」tab（单 Agent 取 `process`、多 Agent 取 execution 投影，去重合并）。**A1 / A1+ / A2′ 查看改动 ✅**：卡头「查看改动」只读——云端优先 `GET …/messages/{id}/files/diff`（回合开始 labeled 基线 vs 此刻树）；**本地会话**走 sidecar `turnFilesDiff` / `restoreTurnBaseline`（工作区旁 `.agentcore/baselines/{message_id}.zip`，不经云盘）；无基线 / 失败降级工具参数预览。有基线时出「回退到本回合开始」（确认后云 `restore_snapshot` / 本机 unzip 整树覆盖）。**否决**默认预写暂存。→ 见代码 `FileArtifactsCard.tsx`、`TurnFileChangesReview.tsx`、`workspace/turn_baseline.py`、`workspace/turn_diff.py`；定案 [前端 UX §九](/docs/04-前端/前端UX设计.md)（定案全文：详细提案不在公开仓 / 维护者本地）。

**交付状态卡（掐断透明化 · C3 职责分离 ✅）**：`delivery_status` 在 partial / blocked 时出 `DeliveryStatusCard`（正文下、产物卡上；`delivered` 不出卡、由产物卡承载）。**结构化 `gaps` 是缺口唯一可信源**——综述正文不再承担缺口披露；完成条件卡是缺口的唯一披露面（逐条 gap 明细），partial / blocked 的强调色由卡片头部（图标 + 状态徽标）承接，避免「正文乐观、卡片悲观」。缺口行可选 `reason` 徽标——已知 `token_budget`（预算触顶）/ `worker_timeout`（运行超时）/ `degraded_handoff`（降级交接）；未知 reason 忽略（向前兼容）。整卡可折叠（整行头部开合 + chevron，对齐产出文件卡）——诚实披露卡**默认展开**（不套产物卡「>4 收起」阈值），收起仅折叠 gap 明细与行动项、头部恒可见；桌面折叠偏好按回合持久化（`usePersistentDisclosure`），手机为本地会话态。手机 TeamView `DeliverySection` 同口径（徽标 + 可折叠）。→ 见代码 `DeliveryStatusCard.tsx`、`TeamView.tsx`；后端 [`编排器 §交付状态`](/docs/03-AI核心/编排器与CEO主Agent.md)。

**案卷徽章与阶段目录（✅）**：文件树对约定阶段目录出**案卷徽章**（「调研案卷 / 辩论产物 / 审查 · N 件」，中性口径不写幕号）；产物卡带案卷标签 +「在文件页查看案卷」跳转。路径→元信息走可扩展表 `lib/stageDirs.ts`（双端同构）；前缀 `AgentCore/文档/{research,debate,reviews}/`（见 [`双模式工作区.md` §五](/docs/02-架构/双模式工作区.md)）。无案卷目录的工作区零噪音。**否决**阶段视图 Tab（超一层、与「复用文件树心智」冲突）。→ 见代码 `components/files/FileTreeRow.tsx`、`lib/stageDirs.ts`。

**项目级协作时间线（✅ 2026-07-19）**：跨会话的项目协作视图 = **读时聚合**——`GET /v1/folders/{id}/collaboration-timeline`（会话 + 幕摘要 + 案卷引用条）；桌面 `/conversations` 项目筛选态顶部 `CollaborationTimeline` 面板、手机工作区文件页文字摘要；阶段产物复用工作区文件 API。**否决**项目级 execution 实体与单张跨会话大图（不造第二真相源，幕拼线靠读时聚合）。→ 见代码 `pages/conversations/CollaborationTimeline.tsx`、`services/collaborationTimeline.ts`、后端 `api/routes/folders.py`。

**共享空间（✅ 2026-07-16 · 多人云端共享盘；✅ 2026-07-24 IA：并入「项目」段）**：`/files` 左栏**无独立「共享空间」分区**——`shared:` 与 `folder:` 按最近活跃**混排**进「项目」段；条目角标为「共享」（与项目的「本地」「云端」三态互斥，不叠「云端」）。树仍按 `shared:<space_id>` 寻址、复用 `FileTree`；差异在行右键：成员管理（IM 精确搜人 + 角色三档 + 移除/改角色/退出，`SharedSpaceMembersDialog`）、变更流水（`SharedSpaceEventsDialog`）、退出/删除。**新建**：项目区头 `+` 菜单 =「新建项目…」「新建共享空间…」（`ProjectsRailHeader`）。**待处理邀请**：左栏顶部 `PendingSharedInvites`，**有 pending 才显示**（无则零噪音）。**否决**：用「云端」角标冒充共享（位置轴 ≠ 协作轴）；独立空态占位分区。**会话侧挂载**：云执行对话的工作区面板挂 `SharedMountsSection`——挂载/卸载空间（角色映射读写面），本地会话不显示。**实时**：firehose `shared_space_invite`（toast + 失效 pending 查询）/ `shared_space_changed`（失效空间列表/流水/挂载树查询），见 `services/realtime.ts`。产品决策与机制 → [双模式工作区 §十一](/docs/02-架构/双模式工作区.md)。→ 见代码 `components/files/sharedSpaces/`、`components/workspace/SharedMountsSection.tsx`、`hooks/useSharedSpaces.ts`、`services/sharedSpaces.ts`。

---

## 十、详情面板与委派展示 ✅ 已确定

> **实现现状**：对话右侧收敛为**单一侧面板** `SidePanel`——固定首位「工作区」home tab + 条件显隐「终端」tab + 按需详情 tab（同一接续链共用一个 tab；离开画布时清内容类 tab、保留 run tab）+ 画布模式顶部指挥台钉区。**单一面板取代并排双右坞**；工作区 body 首次激活懒挂载、之后 keep-alive。节点高亮派生自当前激活 tab。→ 见代码: `stores/sidePanel.ts`

> **交接 = 时间线卡片（方案 B）✅**：本地模式「把活交给云端团队」是对话时间线里的「后台云端任务」卡（非工作区居中模态）；完成后卡内「查看并应用」就地展开内联评审。三段式后端契约不变，仅前端入口下沉进对话。→ 见代码: `components/chat/BackgroundTaskCard.tsx`

聊天右侧详情面板 = Agent 执行的「点开看详情」查看器：正文气泡保持简报（思考折叠条 + 内嵌协作图信号），点图节点后右侧推入该 run 完整详情。**核心价值**：Multi-Agent 一次交互信息量大，正文保持简报、细节按需点开。

**关键行为决策**：

| 决策 | 取值 | 理由 |
|---|---|---|
| Tab 管理 | 动态打开/关闭（非固定 Tab 栏） | 用户只看关心的 |
| 标签上限 | 6，超出淘汰最旧 | 防无限堆积 |
| 持久化 | `open` + `width`；run tab 集会话级（`section` 已删：文件常驻，快照为瞬态） | 面板形态持久，run tab 是临时工作态 |
| 多开 | 多个 `run-detail` 可并存对比 | **否决**每次覆盖 |
| 数据获取 | Tab 只存引用（指针），详情从 run 树现取 | 单一数据源 |
| 下钻导航 | 子任务点击开新 Tab，无限层级 | 各 Tab 独立 |
| 打开方式 | 点内嵌图节点下钻该 run（无自动进度 tab）；点 `SimpleTurn` 开 Q&A tab | 按需、零噪音 |
| 节点高亮 | 内嵌图与放大态**同源派生自**面板当前激活详情 tab（run tab 亮 worker、内容 tab 亮端点；切/关 tab、切到「工作区」tab、关面板自动跟随）——放大态点节点把 run 详情 / 端点内容开到右坞 `SidePanel`（复用同一 `sidePanel` store） | 一面一个高亮源，**否决**反向 `selectRun` 跨 store 对账 |

**run-detail 区段构成**（条件区段无数据时不渲染；顺序见代码）：头部锚点（角色 / 状态 / 用时 / 权限档 / 任务——wire task 块一律升格并从上下文列表去重：续写 beat 以块 body 为正文，冷开局仍用 run.task）→ 主持台账（仅辩论主持人：L1 摘要 +「打开辩论室」；进行中不显示记分）→ 接续链 / 升级 / 收到的上下文（复制型通道默认引用卡：来源跳转 + 保真度 / 截断徽章 + 首行摘要，展开即逐字；增量通道分段卡）→ 主体 `ProcessTimeline`（per-run `process[]`）→ 尾部结论 / 关系 / 资源消耗 / 诊断。**已删除**侧栏平行实现（独立思考区 / 工具列表区 / 单独输出区）——时间线即主体。**独立 `reasoning` Tab 已否决**。→ 见代码: `components/chat/detail/RunDetailBody.tsx`

**诊断 / 开发者模式（✅ 已落地 · 骨架）**：独立开关 `diagnosticMode`（默认关），与「用量 / 成本」呈现无关。开后：气泡挂诊断 id 复制 + run 详情「诊断信息」区。**大众报障不依赖本开关**：错误卡「复制诊断信息」对所有用户可见。深层：调度 `BatchMetrics` ✅；收敛 `turn_metrics` 仍 ⏳。→ 见代码: `stores/ui.ts`

**委派展示统一**：单一可视化（`GraphView` 一张图同表委派树与 `depends_on` 依赖）+ 单一数据模型（`AgentRun`：编排步骤与委派子 Agent 共用同一节点类型）+ `run_*` 事件族（前端不拼接两路流）。**被否决**：前端按 N 隐藏其一（状态仍分叉）；保留双协议只在前端合并（双写漂移）。

**run-detail「委派关系」区段**（阶段2 嵌套委派）：worker 详情在「协作关系」（`dependsOn` 上游 依赖 / 下游 后续，横向同波次）之外另设「委派关系」区段——「上级」是委派它的 captain worker（仅当父 run 是本回合图上的真实节点才显；顶层 worker 的父是 CEO captain、图上无节点，故为空），「子任务」按 `parentRunId` 递归缩进成树、点行下钻该子 run。两者**并列而非混淆**：DAG 边横向（同波次依赖），委派边纵向（嵌套层级）。→ 见代码 `RunDetailBody.tsx`。

**聊天紧凑化原则**：inline 只做信号展示（思考折叠条/状态条/内嵌协作图）；面板承担完整详情（per-run 时间线全文 + 用量）；失败/运行中强制展开（错误绝不藏）；协作图内嵌于回合（非面板 Tab），大图 / 回放进画布放大态。

---

## 十一、Agent 可发现性 ✅ 已确定

可发现性是 Agent 的固有属性，单独成轴，不从「被哪个团队引用」反推。三态：`public`（上架，进发现/搜索，并入 CEO **智能路由**的可用人才池）、`unlisted`（后台构件，不进发现面但按 id 可直达）、`private`（仅创作者可见）。**可发现 ≠ 用户手选**：可发现只是把 agent 喂进 CEO 的人才池由智能路由自动组团，**不给用户开「选择器」菜单**（手选 = 替代 CEO 调度、制造双决策逻辑，已否决）。

**设计原则**：单一谓词（一处过滤 `visibility=public` 覆盖全部发现入口）；`is_featured` 解耦（回归「编辑精选」本职，与可见性正交）；缺省 public（避免误隐藏）；组件型默认 unlisted（团队成员/captain/竞技场角色）。

**被否决**：把辩论/对抗角色拆成**给用户手选的独立实体**——违背 Multi-Agent First；辩论由 CEO 自动调度、主持人驱动（§四），主持人 / 辩手不进发现面、不给用户手选，无独立 Arena 实体或槽位。

---

## 十二、工具箱（卡片网格）

> **已落地**：工具箱页（`/toolbox`）为卡片网格 IA（→ 见代码 `pages/ToolboxPage.tsx`）；「能力」组下两张直达卡片——**工具**（`/toolbox/tools`）、**AI 提示词**（`/toolbox/guidelines`），各进专注子页、共享一次 `/v1/capabilities` 拉取（→ 见代码 `pages/toolbox/{Tools,Guidelines}Page.tsx` + `components/tools/`）。技能（系统 Skill）并入「AI 提示词」页作「工具进阶用法（薄技能）」一节，不再单列卡片（决策见下）。本节为关键决策；工具/产物模型见 [`工具与能力系统.md` §3.4](/docs/03-AI核心/工具与能力系统.md)。

分组：创作工具 / 能力（工具+AI 提示词直达）/ 了解平台（产品手册唯一入口）/ 实验（仅 DEV）。

**关键决策**：小标题非 Tab；了解平台 ⊥ 能力；手册收敛单一入口；能力图鉴 = 工具 + AI 提示词（技能并回提示词层）。**否决**技能并列卡、原文藏起仅开发者可见。→ 见代码: `pages/ToolboxPage.tsx`

**能力透明三层**：L1 图鉴 → L2 过程卡 → L3 收到的上下文。**否决**原文当竞争资产。

**Prompt 结构化渲染**：`PromptDocument` 统一拆段/中文标题。→ 见代码: `components/prompt/PromptDocument.tsx`

---

## 十三、模型配置与会话级组合切换

**信息架构（✅）**：设置侧栏「模型」组两项，按任务拆开——凭据、组合、本地引擎不再塞同一页。

| 页 | 路由 | 一句话职责 |
|---|---|---|
| **模型** | `/more/model` | 账号默认怎么聊：默认组合 + 组合 CRUD |
| **服务商** | `/more/providers` | Key 从哪来、通不通：平台额度说明 + BYOK 列表/表单/测连 |

- **打开 `/more` 落点**：`billing_mode=platform`（或已有可用平台/服务商）→ 模型页；byok 且无服务商、又无平台回退 → 服务商页（最短接 Key 路径）。
- **本地引擎**不在模型组：桌面有本地引擎能力时挂在 **偏好 · 外观**（与 LLM 凭据无关）。
- **用户面「默认」只保留一个词**：账号默认组合 =「默认组合」；服务商表单里的回落模型名不叫「默认」抢戏；会话侧继续「跟随账号默认」。
- platform 叙事：模型页首屏强调「已可直接使用」；BYOK 是可选升级，CTA 进服务商页。

**模型页（组合）**：系统预置「5.2」/「Grok 4.5」不可删（模型不在平台目录则该档不展示）；用户组合可新建 / 改名 / 删 / 设账号默认；复制预置为用户组合。编辑：主模型必填；Worker / 后台**默认折叠**「跟随主模型」，展开后从统一目录选槽。无服务商且无平台时：空态 CTA「接入服务商」→ `/more/providers`（本页不塞完整 Key 表单）。

**服务商页（凭据）**：平台额度只读卡（platform / 免费档）；BYOK 列表（测试连接 / 软提示 `supports_tools` / 编辑 / 删除）；添加·编辑表单（高级·价卡）；安全说明跟本页。

质量档 UI 已永久移除。→ 见代码: `pages/more/ModelSettings.tsx`、`pages/more/ProviderSettings.tsx`、`pages/more/AppearanceSettings.tsx`（本地引擎）、`pages/more/MoreIndexRedirect.tsx`。

**会话级组合切换（✅）**：
- 输入框选的是**组合**（或「跟随账号默认」），**不是**裸模型；次要一行只读摘要 `主 · Worker`。
- 「管理组合…」跳转 **设置 · 模型**（`/more/model`）。
- Key / 余额类错误 CTA（「去设置」「接入自己的 Key」）跳转 **设置 · 服务商**（`/more/providers`）。
- 活引用：`PATCH conversation.model_profile_id`；改组合定义后引用它的会话下一 turn 用新展开。
- 明确不做：角色→模型矩阵、质量档、输入框双 picker、聊天框散装改三槽。
- 无 key / 空目录时组合槽位编辑走服务商页 CTA；组合切换器始终可见。

→ 见代码: 桌面 `components/chat/message-input/ModelPicker.tsx`（组合选择器）、手机同契约；后端见 [平台LLM接入 §二](/docs/05-平台与运维/平台LLM接入.md)、[编排器 §2.1](/docs/03-AI核心/编排器与CEO主Agent.md)。

**设置 · 自主度（✅）**：三档 `always_ask` / `first_grant` / `full_auto`；管开工卡 ∪ GRANTABLE；不动拍板节点。→ 见代码: `pages/more/AutonomySettings.tsx`；权威见 [安全权限与治理 §三](/docs/05-平台与运维/安全权限与治理.md)。

---

## 十四、全局搜索与命令面板（现状）

`Ctrl/Cmd+K`：Tier 1 关键词搜索 + Tier 2 命令导航 ✅。空查询显最近对话+命令；有查询 300ms 防抖后端搜索；消息命中走 load-around。有查询时可按时间 / 工作区筛选结果。入口双假输入框（文案「搜索或运行命令…」）：TitleBar 用 `TitleBarSearchTrigger`，侧栏用 `SearchTrigger`——均 `openSearch()` 打开同一 `CommandPalette`，侧栏不放真输入框。

**搜索 / 筛选 / 查找 三层用词**（✅ 组件已收口）：

| 词 | 场景 | 示例 |
|---|---|---|
| **搜索** | 仅全局 `Cmd+K` | 跨对话、消息、项目、命令 |
| **筛选** | 当前列表/树客户端过滤 | `/conversations`、文件工作区、IM 会话列表、`@` 弹层 |
| **查找** | 当前视图内定位 | `Cmd+F` 已加载消息；IM「查找联系人」 |

会话内 `FindBar` 无命中时引导「在全对话中搜索」并预填关键词打开命令面板。

技术契约 → [`前端技术与架构.md` §9.8](/docs/04-前端/前端技术与架构.md)。组件规格 → [`UI-Pattern索引.md`](/docs/04-前端/UI-Pattern索引.md)。Tier 3 语义搜索 ⏳ → 远期规划 §三（详细提案不在公开仓 / 维护者本地）。

---

## 十五、待定事项

| 议题 | 说明 |
|------|------|
| 移动端适配 | 图视图在手机端如何简化 |
| 多任务同时进行 | 多个任务并行时图视图如何呈现 |
| 历史任务回放 | 图视图内帧流回放已落地（`Timeline`）；跨会话回放完整历史任务待定 |
| 无障碍访问 | 图视图的键盘导航和屏幕阅读器支持 |
| 离线态 UX | 已连接但目录不可达时的降级展示 |
| 深层诊断指标 | 诊断模式骨架 + 调度 `BatchMetrics` 已落地（§十）；worker LLM 窗口已并入「收到的上下文」诊断态 ✅；收敛 `turn_metrics` 仍 ⏳ |
| 流式文字平滑追加 | 正文按 2–3 字一组平滑追加的微动画（现 `streamingMarkdown.ts` 为逐块切分、无字符级动画） |

### 消息收藏 ✅ 已落地

助手气泡脚 `BookmarkButton` 星标收藏（`stores/bookmarks.ts`：打开会话时从服务端水合 id 集，toggle **乐观翻转** + 失败回滚；成功后 invalidate「已收藏」列表）。**服务端真相**（`GET/POST/DELETE /v1/bookmarks`，跨设备）。聚合入口 = 命令面板 facet「**已收藏**」（空查询亦露「最近收藏」teaser）——**否决**侧栏独立「已收藏」列表 / 专用 `/bookmarks` 页（与全局发现同壳、少一层导航）。→ 见代码 `stores/bookmarks.ts`。
