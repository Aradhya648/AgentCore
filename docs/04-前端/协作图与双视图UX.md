---
status: blueprint
code: apps/desktop/src/renderer/
related:
  - docs/04-前端/前端UX设计.md
  - docs/04-前端/前端技术与架构.md
skip_if:
  - 只改辩论室呈现（读辩论室UX）
  - 只改壳层布局/首启/文件（读前端UX设计）
---

# 协作图与双视图 UX

> 入口：[前端 UX](/docs/04-前端/前端UX设计.md) · 渲染内核 → [前端技术 §9.13](/docs/04-前端/前端技术与架构.md)

## 三、内嵌协作图与状态条

多 Agent 团队界面 = 消息内嵌 `InlineTeamGraph`：状态条四态 + 可折叠图；「在画布打开」→ `TurnDetailPage`。

| 场景 | 行为 |
|------|------|
| 简单任务（无 plan） | **不出图** |
| `delegate` | `run_plan` 到达自动内嵌 |
| 跨回合同图追加 | 新回合只渲染锚点条；生长归旧图 |
| 开工挂起零 run | **不出图**（注意力归续跑卡） |
| 完成 / 停止 | 战绩收缩 / 「已停止」（只陈述，无救火按钮） |

**失败收口**：协作图状态条 / 画布指挥台只报战绩——meta 的 `n/m` + 图节点色 + 右坞详情，**不**另挂「N 个子任务失败」红条；救火统一「对 CEO 再说」或再发一条（同人续派 / `continue_from_run_id`）。**否决**状态条「重试」「重试失败项」、`retry-failed` API、叠「全部重生成」、显式忽略（新 turn 隐式收口）、无帧「继续」。有正文气泡的 regenerate、传输层 RetryBanner 仍保留。`cancelled`/`interrupted` 不出 finishReason chip。

默认展开，按对话持久化。多幕 LOD：≥2 幕恰好一幕展开 DAG；**否决**默认全展开。face 徽标 ≤2；行动条仅 ≥2 待决。**否决**「规划中」态（`run_plan` 同步到达）。

**运行中再发（P0+P1 ✅）**：composer 不禁发；`delivery` 必填。三原语 Steer / Queue / Stop。默认 Enter=Steer（协调→插话；经典→步边界软插入 + toast「已插入，下一工具步生效」）；Ctrl/Cmd+Enter（桌面）/「排队」钮（手机）强制 Queue。失败才 `degraded_from` 排队提示。Queue → 主气泡+轻态可取消；Stop ≠ 取消排队（但 Stop 后队列会立刻 drain 开跑）。单轮散文可能先 ack 再升下一回合——见 [运行时三模型 · 已知行为](/docs/03-AI核心/运行时三模型与挂起.md#已知行为真跑--平台-deepseek--2026-08)。权威 → [同对话再发](/docs/03-AI核心/运行时三模型与挂起.md#同对话再发steer--queue)。

检查点 / 非阻塞发问 / plan_review / ResumePrompt / InteractionStore：语义 → [检查点与开工卡](/docs/03-AI核心/检查点与开工卡.md)。内联卡只留 resolved；可操作面统一 `ResumePrompt`。**否决**题目 accordion、Wizard、消息流再堆可操作入口。决策区 Chat/画布 `ConversationDecisionPrompts` 单挂载互斥。

## 五、图视图

内嵌 = 静态预览（禁缩放）；探索在放大态。节点 face：角色→在干什么→用时；¥/token 归 run 详情。点节点 → 右坞 SidePanel（高亮同源）。

**布局 / 相机（白板模型）**：ELK **只**在结构变更时跑；`NODE_WIDTH`×`NODE_HEIGHT` 为布局权威 footprint，face 槽内裁切/滚动。相机只在结构 bbox 就绪/身份变化或容器尺寸变化时 fit（内联一次 fit-width）；**否决**测高二次 ELK、soft-center 抬 footprint、测高伺服相机。宿主常驻：`layoutReady` 不卸载 ReactFlow；内联折叠隐藏不卸树。契约 → `graphHost.tsx`。

**节点 = 一次执行（run）**：独立产出→新节点；轮内从属 beat→折进宿主；状态变化→角标。**否决**单卡堆叠 ×N、工具点节点。无 `continues_run_id` 的同 role ≠「同一人」。辩论不开放「改方向」。能力表一处声明 `planCapabilities.ts`。宿主三入口共用 `graphHost`；布局失败显式错误。

子队盒：接续链归属单源 `layoutHints.ts`。辩论：一列=一轮，质询折进轮节点；结辩独立列。身份色 ⊥ 状态色。信息流边仅有损交接挂签。审计 inject 按需高亮；**否决**全量虚线、迷你 DAG、改 conformance。波次=拓扑层；跨委派用 `delegateBatch`（不进协议）。

## 六、聊天 ⇄ 画布

一份数据两种渲染（同 `projectExecution`）；切换不动协议。聊天默认 + 画布 opt-in；**聊天永不删**。画布=单张持久空间；LOD 恰好一聚焦回合展 DAG。指挥台 = SidePanel 顶部 `CommandRegion`（非第二右坞）。composer 核统一 `TurnComposer`。放大态纯深读、无命令栏。

| 方向 | 处置 |
|---|---|
| 图即唯一界面 | 撤 |
| 对话页卡片化 | 撤 |
| 自适应默认切模式 | 否决 |
| 真持久团队实体化 | 暂不做 |
| 跨对话公司级画布 | 不在范围 |

对比透镜仅非辩论同人接续链；辩论对照归辩论室。图技术：**否决** D3、自研画布。性能：节点 ≤50、≥60fps。

→ 见代码 `components/graph/`、`pages/TurnDetailPage.tsx`、`stores/commandPanel.ts`。
