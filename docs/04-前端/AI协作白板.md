---
status: landed
code: apps/desktop/src/renderer/whiteboard/
related:
  - docs/03-AI核心/工具与能力系统.md
  - docs/02-架构/核心接口定义.md
skip_if:
  - 不涉及白板 / 画布引擎 / AI 读图摆元素
---

# AI 协作白板

> 桌面内页面（非独立 app）；空间 JSON 为真相。→ `apps/desktop/src/renderer/whiteboard/`。冲突以代码为准。

## 定位与差异

真白板（无限画布）+ **AI 团队进板**（读图 / 摆元素 / 照白板干活）。人主画、AI 助手。**不做** ConversationCanvas 升级版、不做独立 app。空间 JSON 与「文本典范」不冲突——scene 本质空间，文本表达不了。重叠面（团队图/mermaid/文件列表）不重做。

## 关键决策

| # | 决策 |
|---|---|
| 形态 | desktop 路由 `/whiteboard`；工具箱入口，**不**进侧栏主导航 |
| 引擎 | **自研**原生引擎；`agentNode`/`artifactCard` 一等形状 |
| 归属 | board ∈ folder；独立 `boards` 表 + scene blob（<256KB JSONB，否则 S3）+ CAS version |
| AI 写 | 结构化 `board_ops`（catalog 工具），非裸 REST、非整图生成 |
| 读图 | 选区混合：结构→JSON，手绘/截图→栅格化→`VisionReader` |
| 团队 | 复用 `sendBoardTurn` + CEO `delegate`/`debate`；**零新编排/fold** |

**否决**：独立 web app；stock Excalidraw（美学+非原生节点）；tldraw（授权）；Fork Excalidraw（merge 税）；侧栏直达；`briefRegion` 原生形状（brief=选区/`frame`）。

## 引擎不变量

历史深拷不别名；仅 engine 持可变态；编组扁平；箭头绑定删除连带；CAS 冲突不覆盖；applier 仅画布打开时在册；M3 进度=`setOverlay` 瞬时浮层，终态才 `addElements` crystallize（按 runId 幂等）。配色走 token。→ `WhiteboardApi`（`whiteboard/types.ts`）。

## 接缝

| 面 | 约束 |
|---|---|
| 后端 | 又一个 run+SSE 客户端；发现改编排器 → 停（绊线） |
| 协议 | 复用现有 run fold；组件层不进 conformance |
| 读图 | `board_read` CLIENT_TOOL；视觉子调用 `role=vision` 独立入账；仅 `billing_mode=platform` + `VISION_API_KEY`/`VISION_BASE_URL` 启用（默认 `kimi-k2.5`）；BYOK 不启用；空配置干净失败 |
| 产物 | 文本卡先行；`@` 回工作区待文件信号；迭代空间留痕 |

平台识图（`kimi-k2.5` + curated 价卡 + `board_read` 实调用）已在本地验收通过；桌面画布前台栅格化仍依赖打开白板的真实 CLIENT_TOOL 回填。

## 风险护栏

通用画布够用即止、火力在 AI；拖累 Hero 即停。实时协作 v1 不做（可留 yjs 缝）。
