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

**侧栏 IA（方案 B）**：上=项目分组（Top 5/组、≤6 组）；下=裸聊扁平（有分组 10 / 无分组 15）。**否决**跨区「最近」、裸聊「未分组」空组。两区无标题，分隔线区分。对话出生定终身（不支持事后移入）。归档可撤销；删除对用户永久（无回收站 UI）。「对话」导航 = 新建草稿（`/` 唯一真相）。

**全局协作感知**：列表状态点（执行中脉动 / 「等你决策」光环）；跨对话完成 Toast + 原生通知。`finish_reason=paused` ≠ 完成。→ `teamActivityNotifications.ts`。

**团队展示**：多 Agent 走内联 `ProcessTimeline`，协作图嵌在 `delegate`/`debate` 步；单 Agent / 开工挂起零 run **不出图**。形态分工 → [协作图 UX](/docs/04-前端/协作图与双视图UX.md)。

### 一B、ProcessTimeline

思考·正文·工具按时序交织；末段正文=答案。**否决**常驻吵闹工具卡、按类别归桶。连续 ≥2 工具保序折叠（纯渲染）。完成态可折过程，可见节点不入折。复制两档：仅交付 / 含过程。`cancelled`/`interrupted` **不出** finishReason chip。→ `ProcessTimeline.tsx`、`lib/processTimeline.ts`。

**已否决（聊天）**：Slash、Agent/Team 选择器、产物 Pill、草稿「存储⊥项目」双入口。

## 二、首启与空态

激活 = 首次真实回合成功。平台代付开箱即用；**无接入门**；BYOK 仅设置可选升级。**否决**服务端 onboarding 状态、form gate、多步 Tour。空态两态客户端推导；新用户 starter chips（老用户消失）。情境提示 ≤3，仅协作图一枚。→ `components/onboarding/`。Mobile：keyless 同无接入门。

## 九、文件交互

**项目=工作区**；入口= SidePanel + `/files`。**否决**云/本地两平级分段。删项目：对话归档、文件保留期清理；**否决**级联删聊天、`Folder.archived`。「清空本对话产物」仅云端 `conv:` scratch。审批：信任档下文件改动免逐次卡（永久删仍问）。草稿「在哪工作」单一 chip。md 默认阅读预览；HTML 面板显源码，完整效果走预览 tab / 系统浏览器（→ 前端技术 §9.12）。产物卡 + 改动 diff；交付状态卡以结构化 `gaps` 为唯一缺口源。案卷徽章复用文件树；**否决**阶段 Tab。协作时间线=读时聚合；**否决**项目级 execution 实体。共享空间并入「项目」段角标「共享」。→ [双模式工作区](/docs/02-架构/双模式工作区.md)。

## 十、详情面板

单一 `SidePanel`：工作区 home + 条件终端 + 按需详情。Tab 上限 6；多开并存；只存引用。高亮同源 sidePanel。**否决**覆盖式单 tab、独立 reasoning Tab、并排双右坞。委派：单一 GraphView + 单一 `AgentRun` 模型。诊断模式 ⊥ 用量呈现。→ `stores/sidePanel.ts`、`RunDetailBody.tsx`。

## 十一、Agent 可发现性

`public`/`unlisted`/`private`；可发现 ≠ 手选。**否决**用户 Agent/Team 选择器、辩论角色手选实体。

## 十二、工具箱

卡片网格；技能并入「AI 提示词」。**否决**技能并列卡、原文当竞争资产。→ `ToolboxPage.tsx`。

## 十三、模型与自主度

设置拆「模型」（组合）/「服务商」（凭据）；本地引擎挂外观。会话选**组合**非裸模型。**否决**角色→模型矩阵、质量档、双 picker。自主度三档 → [安全权限与治理 §三](/docs/05-平台与运维/安全权限与治理.md)。

## 十四、搜索

Cmd+K：搜索；页内：筛选；Cmd+F：查找。Tier 3 语义搜索 ⏳（详细提案不在公开仓）。→ 前端技术 §9.8、[UI-Pattern](/docs/04-前端/UI-Pattern索引.md)。

## 十五、待定与收藏

移动端图简化、跨会话多任务总览、无障碍、离线态 UX、流式字级动画 ⏳。消息收藏 ✅：命令面板「已收藏」facet；**否决**侧栏独立列表。
