---
status: blueprint
code: apps/desktop/src/renderer/
related:
  - docs/04-前端/前端技术与架构.md
  - docs/04-前端/协作图与双视图UX.md
  - docs/04-前端/辩论室UX.md
  - docs/03-AI核心/辩论编排设计.md
skip_if:
  - 只改 Store/IPC（读前端技术与架构）
---

# 前端 UX 设计

> **04 UX 入口**（壳层）。工作区 → [双模式工作区](/docs/02-架构/双模式工作区.md)；FileSource → [前端技术 §八](/docs/04-前端/前端技术与架构.md)。

## 权威归属表

| 主题 | 权威文档 |
|---|---|
| 全局布局、侧栏、首启、文件/详情/工具箱/模型/搜索 | **本文** |
| 内嵌协作图、图视图、聊天⇄画布、图技术选型 | [协作图与双视图 UX](/docs/04-前端/协作图与双视图UX.md) |
| 辩论室赛事页、介入、站队 | [辩论室 UX](/docs/04-前端/辩论室UX.md) |
| 协作图渲染内核 | [前端技术 §9.13](/docs/04-前端/前端技术与架构.md) |

心智：「掌管 AI CEO 带队的 Agent 团队」。原则：零门槛、渐进揭示、简单任务零噪音。

## 一、全局布局与侧栏

侧栏 + 页面自布局；对话页单栏聊天。内嵌图「在画布打开」→ `TurnDetailPage`；点节点 → SidePanel run tab。输入框：空草稿居中，首条后 FLIP 落底。→ `ChatView.tsx`、`useComposerDockFlip.ts`。

**侧栏 IA（方案 C）**：顶=全局置顶（裸聊 + 项目对话均可；按最近活动；零重复）；中=项目分组（Top 5/组、≤6 组；组内仅未置顶）；底=未置顶裸聊扁平（有分组 10 / 无分组 15）。**否决**跨区「最近」、裸聊「未分组」空组、置顶与组内/裸聊双显。三区无标题，分隔线区分。对话出生定终身（不支持事后移入）。归档可撤销；删除对用户永久（无回收站 UI）。「对话」导航 = 新建草稿（`/` 唯一真相）。

**全局协作感知**：列表状态点（执行中脉动 / 「等你决策」光环）；跨对话完成 Toast + 原生通知。`finish_reason=paused` ≠ 完成。→ `teamActivityNotifications.ts`。

**产品公告**（运营 Notice，≠ 群公告 / ≠ 站立收件箱）：顶栏 Banner（同时 ≤1，紧急/维护）+ 登录后一次性弹窗（`surface=modal`，关即 dismiss）+ 消息页「AgentCore 官方」只读会话回看；Banner/Modal 软轮询；inbox 走 IM 未读。More「公告」已撤（`#/more/notices` → 官方会话）。契约 → [管理员后台 · 产品公告](/docs/05-平台与运维/管理员后台.md#产品公告全局-notice)、[消息 IM](/docs/05-平台与运维/消息IM.md)。→ `ProductNoticeBanner`、`ProductNoticeModal`、`stores/productNotices.ts`、MessagesPage 官方号。

**团队展示**：多 Agent 走内联 `ProcessTimeline`，协作图嵌在 `delegate`/`debate` 步；单 Agent / 开工挂起零 run **不出图**。形态分工 → [协作图 UX](/docs/04-前端/协作图与双视图UX.md)。

### 一B、ProcessTimeline

思考·正文·工具按时序交织；末段正文=答案。**否决**常驻吵闹工具卡、按类别归桶。连续 ≥2 工具保序折叠（纯渲染）。完成态可折过程，可见节点不入折。复制两档：仅交付 / 含过程。`cancelled`/`interrupted` **不出** finishReason chip。→ `ProcessTimeline.tsx`、`lib/processTimeline.ts`。

**已否决（聊天）**：Slash、Agent/Team 选择器、产物 Pill、草稿「存储⊥项目」双入口。

## 二、首启与空态

激活 = 首次真实回合成功。平台代付开箱即用；**无接入门**；BYOK 仅设置可选升级。**否决**服务端 onboarding 状态、form gate、多步 Tour。空态两态客户端推导；新用户 starter chips（老用户消失）。情境提示 ≤3，仅协作图一枚。→ `components/onboarding/`。Mobile：keyless 同无接入门。

## 九、文件交互

**项目=工作区**；入口= SidePanel + `/files`。**否决**云/本地两平级分段。删项目：对话归档、文件保留期清理；**否决**级联删聊天、`Folder.archived`。「清空本对话产物」仅云端 `conv:` scratch。审批：信任档下文件改动免逐次卡（永久删仍问）。草稿「在哪工作」单一 chip。md 默认阅读预览；HTML 面板显源码，完整效果走统一浏览器壳（桌面 `workspace://` + 右坞 BrowserPanel；Web 下载 / 系统浏览器；→ 前端技术 §9.12）。产物主清单认 `delivery_status.artifacts` 验收态（已验收/未通过；**否决**写入/编辑标签冒充交付）；「查看改动」按路径相对基线标新建/更新/删除，与右坞「改动」tab 同源（见 §十）。**否决**「交付验收」大卡与卡上动作：`delivered`/`notes` 静默；仅 `partial`/`blocked` 一句轻提示；缺口细节不靠验收卡展开（后台 `gaps` 仍供对账与 finish_guard）。案卷徽章复用文件树；**否决**阶段 Tab。协作时间线=读时聚合；**否决**项目级 execution 实体。共享空间并入「项目」段角标「共享」。→ [双模式工作区](/docs/02-架构/双模式工作区.md)；产物卡 → `lib/fileArtifacts.ts`。

## 十、详情面板（右坞）

单一 `SidePanel`（对话/画布**主坞**）。高亮跟**焦点面板**的 run（主坞活跃 tab 或某浮窗；`focusSurface` / `sidePanelFocusTabId`）。**否决**覆盖式单 tab、独立 reasoning Tab、并排双右坞、把白板塞进右坞、顶栏全局命令板（首期）。委派：单一 GraphView + 单一 `AgentRun` 模型。诊断模式 ⊥ 用量呈现。run 详情时间线：进行中贴底跟随（同主对话 stick 语义，上滑脱钩 +「回到底部」）；回看已结束 run 打开置顶。→ `stores/sidePanel.ts`、`RunDetailScroll.tsx` / `RunDetailBody.tsx`。

**主坞定义**：未弹出内容的**停靠条 + 右侧布局槽**（非唯一可见/唯一可操作面）。关主坞 = 收起右侧槽，不销毁已弹出浮窗。

**右坞 IA**：顶栏 = `[工作区?] [改动?] | 内容 tabs | [+]`（工作区**不可销毁、可 detach**——在坞内时固定首位；已弹出则坞条不留重复入口，可钉回；**改动按本对话有无 AI 文件改动条件出现**，出现后在坞内位次靠前、不可关，亦可 detach）。内容 tab 多开并存、只存引用；可关 tab 上限 **12**（固定/条件固定不计；正在 float 的 tab 不被此帽挤掉）。`+` 菜单：文件 / 终端 / 浏览器（**文件**可多开顶栏 tab；**终端 / 浏览器**各一壳，多会话/页签在壳内管理）。**浏览器** = 统一 BrowserSession 壳（可新空白页+地址栏；非「等 AI 才亮」）；产物完整预览并入同壳（桌面 workspace 协议；**否决**平行「预览」tab）。**否决**「团队浏览器 vs 通用浏览器」双入口。画布态另出「指挥台」（条件固定，不进 `+`）。工作区 tab 内保留文件树 + 项目·本地/云端 chip + 新建文件/文件夹等工具栏；点文件开顶栏 File tab（不 swap 掉树）。

**「改动」tab**：本对话 AI 文件改动聚合（只读真 diff + 回滚；不做 apply/三方冲突——仍归交接）。行标签=新建/更新/删除（相对回合基线；**否决**工具名「写入/编辑」）。与产物卡「查看改动」同源聚焦（深链可先挂再聚焦）。**出现** = 本对话已有 AI 文件改动记录，或产物卡深链；**不**空挂常驻（对齐 Cursor 等「有货才审」）。**卸下** = 本对话无改动记录（切对话各自推导）；有改动时挂上不抢焦点。**否决**空态常驻入口；**否决**「清空本对话产物」作为卸 tab 条件（清空只抹云 scratch 盘，process/execution 改动史仍在）。文案用「改动」；**否决** tab 名 `diff`。→ `ConversationChangesPanel.tsx`

### ✅ 应用内浮窗（方案 B · Web）

桌面已切方案 C；**Web 长期保留 B**（无真窗）。B 宿主：`SidePanelFloatHost` ⊥ `open`。

| 项 | 现状 |
|---|---|
| 语义 | Move；上限 8；可弹 run/工作区/文件/改动 |
| 宿主 | `SidePanelFloatHost` ⊥ `open`；几何限于应用客户区（盖不住侧栏） |
| 指针 | `stores/sidePanel.ts`、`FloatingPanelShell` / `SidePanelFloatHost` / `SidePanelSurfaceBody` |

### ✅ 真 OS 窗（方案 C）

桌面「弹出」= 独立 `BrowserWindow`（对标 JetBrains **Window** / VS Code Aux），可拖到任意显示器、可盖过主窗 UI。**否决**继续用应用内 absolute 层冒充「任意移到屏幕」；**否决** Copy 双开；终端/浏览器/指挥台/`content`/`simple-turn` 仍不可弹。

| 项 | 定案 / 现状 |
|---|---|
| 平台 | **仅桌面 Electron**；Web 保持方案 B |
| 语义 | 仍 **Move**；同一 tab 至多一处（坞 \| 应用内浮层(Web) \| 真窗(桌面)） |
| 可弹 | 同 B：run、工作区、文件、改动 |
| 交互 | 真窗内完整可操作；审批须在真窗内可达 |
| 关主坞 | 真窗保留 |
| 关真窗 | **系统关闭** = 钉回主坞（同 VS Code 关 aux）；**否决**真窗顶栏再挂图钉/自定义 ×（与窗控叠床架屋） |
| 关主应用 | 主进程退出时收尽真窗 |
| 高亮 | 跟焦点面（含「焦点在某真窗」）；主窗图高亮经 BroadcastChannel 焦点同步 |
| 数量 | 统一上限 **8** |
| 状态 | 真窗 = 新 renderer；主窗 SSE 权威，经 BroadcastChannel 推投影快照（禁真窗各自开对话流） |
| Local Browser | 仍不可弹；单 `hostWin` 附着模型首期不改为多宿主 |
| 窗控 IPC | 按 **webContents/窗 id** 路由；`float-window:*` + preload `floatWindowApi` |
| 任务栏（Win） | **单 AppUserModelID**（`com.agentcore.desktop`）分组 + 多预览；最小化后缩略图/列表可还原；预览标题=真窗 title；**否决**每真窗独立钉选图标 |

→ `main/float-window.ts`、`DesktopFloatWindowBridge`、`FloatWindowPage`、`lib/floatWindowSync.ts`

**验收**：真窗可拖到副屏；盖过主窗侧栏/外框；两 worker 真窗并排跟流；钉回/切对话清空；审批在真窗可点；Web 仍为应用内浮窗。
## 十一、Agent 可发现性

`public`/`unlisted`/`private`；可发现 ≠ 手选。**否决**用户 Agent/Team 选择器、辩论角色手选实体。

## 十二、工具箱

卡片网格；技能并入「AI 提示词」。**否决**技能并列卡、原文当竞争资产。→ `ToolboxPage.tsx`。

**自动化**（`#/toolbox/automations`）：站立任务列表 + 收件箱；系统模板「每日对话复盘」引导开（未装/未启用顶卡；可配本地时刻、全局裸聊、多云项目作用域、报告落点）。→ `StandingTasksPanel` / `StandingTaskEditor`；契约 [记忆 · 跨会话](/docs/03-AI核心/Agent记忆与知识系统.md)。

## 十三、模型与自主度

设置拆「模型」（组合）/「服务商」（凭据）；本地引擎挂外观。会话选**组合**非裸模型。**否决**角色→模型矩阵、质量档、双 picker。自主度配方三选一（谨慎 / 少打断（默认）/ 托管）→ [安全权限与治理 §三](/docs/05-平台与运维/安全权限与治理.md)。账户默认：桌面经对话权限徽章「设为新会话默认」写入；手机仍可经设置改。会话内徽章可改四轴（含本机）；非法组合不可选；自定义四轴不可存为账户默认。

## 十四、搜索

Cmd+K：搜索；页内：筛选；Cmd+F：查找。Tier 3 语义搜索 ⏳（详细提案不在公开仓）。→ 前端技术 §9.8、[UI-Pattern](/docs/04-前端/UI-Pattern索引.md)。

## 十五、待定与收藏

移动端图简化、跨会话多任务总览、无障碍、流式字级动画 ⏳。**断线只读（N4-A）**：可浏览已缓存对话与本机文件（只读），不能发送 / 改文件 / 跑 AI；「本地引擎」= 本机执行更快，**不是**离线模式（推理仍要云）。完全离线（本机推理 + 本机消息库）仍 ⏳。消息收藏 ✅：命令面板「已收藏」facet；**否决**侧栏独立列表。
