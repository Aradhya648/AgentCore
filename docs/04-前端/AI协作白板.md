---
status: landed
code: apps/desktop/src/renderer/whiteboard/
related:
  - docs/03-AI核心/工具与能力系统.md
  - docs/02-架构/核心接口定义.md
skip_if:
  - 不涉及白板 / 画布引擎 / AI 读图摆元素
---

# AI 协作白板（桌面端 · as-built）

> **定位**：AgentCore 桌面端的一块**协作白板**（市场款无限画布，便签/形状/箭头/手绘），差异点是**白板里有一支 AI 团队**（读图 / 摆元素 / 拉团队照白板干活）。落地为 **`apps/desktop` 内一个页面/路由**（非独立 app），**数据模型用空间 JSON 为真相**，复用 AgentCore 地基（账号、Agent 团队后端、LLM 推理、存储）。本文是**现状说明书**：§一/§二 产品差异化与定位；§三–§五 关键决策（含被否决方案）；§六 = 自研引擎 as-built（`apps/desktop/src/renderer/whiteboard/`）；§七–§九 数据契约 / 后端接线 / 读图；§十 交付现状。冲突以代码为准。
>
> **状态（2026-06-29）**：**M1 自研引擎 + M2 结构化 ops + M3 团队照白板（贴源 / crystallize / 迭代）+ 读图链路 / `VisionReader` / 视觉子调用入账 均已落地 ✅**；**唯一缺口 ⏳**：读图端到端实跑验收——配 `apps/server/.env` 的 `VISION_API_KEY` 选定具体视觉模型（默认 `qwen-vl-max`，§九）即可。状态标记：**✅** 已落地 / **⏳** 已确认未落地。
>
> **来源**：2026-06-25 一次「开发画布 / 白板工具」讨论，经「用户需求三问」压测定调（真白板 / 做进 desktop 非独立 app / AI 团队第一天就进 / 人主画·AI 当助手）；落地形态曾起 strawman B（独立 web app），压测后改定 A（§四.1）；引擎选型曾定 stock Excalidraw（MIT $0），2026-06-27 经压测后推翻、改定自研原生引擎（§五）。

---

## 一、为什么做（先对齐需求，别用技术反推）

诚实声明：这不是「技术方便 / 跟风反推需求」。讨论中先对白板做了压力测试——**白板能干的事，大半在 AgentCore 里是重复造轮子**：

| 候选需求 | AgentCore 现状 | 白板独占价值 |
|---|---|---|
| 看团队并行产出 / 对比多方案 | `ConversationCanvas`（回合→节点图）+ 协作图依赖布局 + 辩论卡 + 诊断 SchedulingDiag | ❌ 大量重叠 |
| 画架构图 / 流程图 | mermaid（表达形态·已落地）+ 规划中「流程图」产物 | ❌ 文本图对 AI 共编更优（[工具与能力系统 §3.2/3.3](/docs/03-AI核心/工具与能力系统.md)） |
| 跟 AI 头脑风暴 / 视觉思考 | 聊天能聊，无「空间铺陈」 | ⚠️ 半覆盖 |
| **人手绘 / 视觉输入当需求，AI 看懂据此干活** | 无 | ✅ 文本真表达不了，**白板独有** |
| **把多个文件 / 产物空间化成「项目地图」** | 仅列表视图（`/files`） | ✅ 空间 vs 列表，互补 |

**结论**：纯白板是红海，再造一个 Miro / Excalidraw 没意义。**唯一值得做的差异点 = 白板里有一支 AI 团队**——能看懂你的手绘、按草图摆元素 / 生成结构、甚至拉团队照着白板干活。这正好兑现 AgentCore 的核心心智「管理一个 Agent 团队」（[产品定位与品牌](/docs/01-产品/产品定位与品牌.md)）。

> **空间 JSON 为真相，与 §3.3 不冲突**：[工具与能力系统 §3.3](/docs/03-AI核心/工具与能力系统.md)「文本为典范模型」针对的是**本可用文本表达**的协作内容；白板 scene 是**本质空间**的（手绘/位置/连线，文本真表达不了，§一已述），故用空间 JSON 当真相是必然，不与文本典范铁律冲突。

---

## 二、产品定位与差异化

- **是什么**：市场款真白板——无限画布、便签、形状、箭头、连线、手绘笔、插图、框选分组。
- **不是什么**：不是 AgentCore 内核里的「创作产物」，不是 `ConversationCanvas` 的升级版；也**不做成独立 app**（落地为 desktop 内页面，见 §四）。
- **Hero 差异点 = AI 团队进白板**：
  - **读图**：看懂你的手绘草图 / 截图当 brief（视觉模型）。
  - **摆 / 生成结构**：加便签、拉箭头、排流程、生成图骨架（结构化操作，非「手绘」）。
  - **拉团队照白板干活**：选中白板某区域 →「让团队照这个实现」→ 发起一次 Agent run →产物（文件 / 卡）回到白板。
- **AI 角色（已定）**：**人是主画手，AI 当助手**——AI 摆元素 / 生成结构 / 整理布局 / 读图执行，**不**替人「拿笔涂鸦」。

---

## 三、已对齐决策与 Gate（✅ 全部已定 2026-06-25；G1 引擎 2026-06-27 更新）

> 下表是**已落地的关键决策**（上半=产品/策略，下半 G1–G6=工程 gate）。「解锁 / 影响」列记录该决策当初卡住的施工面，今均已交付（§十）。
>
> **落地状态（2026-06-29）**：G1–G6 对应的 **M1 自研引擎 + M2 结构化 ops + M3 团队照白板（贴源 / crystallize / 迭代）前端均已落地 ✅**（后端 AI-ops / 读图协议与引擎无关、保留，§五.4）；**G6 读图链路 + Qwen-VL 参考 reader + 视觉子调用入账（`role=vision` 行）均已落地 ✅，仅端到端实跑待验 ⏳**。下表「解锁 / 影响」是**决策视角**；G6 读图施工级设计见 §九、整体施工进度见 §十。

| # | 维度 | 决策 | 解锁 / 影响 |
|---|---|---|---|
| 产品 | 产品形态 | 真白板（市场款无限画布） | 整体方向 |
| 产品 | 典范模型 | **空间 JSON 为真相**（独立产品，不受 [§3.3](/docs/03-AI核心/工具与能力系统.md) 文本典范约束） | 数据模型（§七） |
| 产品 | 产品归属 | AgentCore **桌面端的一个功能/页面**（非独立 app），复用后端地基 | 落地范围（§四） |
| 产品 | 与 AI 团队关系 | **AI 团队是核心卖点，第一天就进**（不延后 v2） | 里程碑（§十） |
| 产品 | AI 角色 | 人主画 / AI 当助手（含读图执行） | 产品体验 |
| 产品 | 复用地基 | 账号 / Agent 团队后端 / LLM 推理 / 存储 | 后端零新基建（§八） |
| 产品 | 导航入口 | **工具箱磁贴**（`/toolbox` →「白板」→ `/whiteboard`）；**不设**主导航侧栏直达（§四.2） | M1 信息架构 |
| G1 | 渲染引擎 | **自研原生引擎**（2026-06-27 推翻 stock Excalidraw；Agent 节点做成原生一等形状，§五） | M1 全部 |
| G2 | 落地形态 | **desktop 内白板页面/路由**（同 origin，复用桌面 auth/run/SSE）；否决独立 web app（§四.1） | M1 |
| G3 | board↔folder | board **归属一个 folder 工作区**（复用现有 folders 用户作用域，[`folders.py`](/apps/server/agentcore/api/routes/folders.py)） | M1 数据模型 |
| G4 | 白板存储 | 独立 `boards` 表 + scene blob；<256 KB 内联 JSONB，≥256 KB 落 S3（§七） | M1 数据模型 |
| G5 | AI ops 通道 | AI 摆元素走**新内建工具进 `tools/catalog`**（复用 run/工具协议），非裸 REST | M2 |
| G6 | 读图通道 | **选区混合读取**：结构元素 → scene JSON；手绘 / 截图 → 栅格化 → `/v1/inference` 视觉模型（宿主侧导出，不依赖引擎内部） | M2 |
| — | M3 run 接入点 | **复用 `sendBoardTurn`(pipeline) + CEO 自主 `delegate`/`debate`**（pipeline 唯一入口、二者回合内工具）；零新编排 / 零新 fold（§十 M3） | M3 ✅ |

---

## 四、落地形态：desktop 内白板页面（✅ G2 = A）

**决策**：白板**不**做成独立 app，而是 **`apps/desktop` 渲染层里的一个新页面/路由**，与桌面**同 origin `app://agentcore`、同构建、同认证、同发版列车**。理由见 §四.1。

| 维度 | 取值 | 复用桌面现成 |
|---|---|---|
| 页面 | `pages/WhiteboardPage.tsx`（`/whiteboard` 跨文件夹板列表）+ `pages/WhiteboardCanvasPage.tsx`（`/whiteboard/:boardId` 全屏画布，照 `/toolbox/manual` 全屏页范式） | ✅ desktop-layout 全屏页豁免 |
| 路由 | `router.tsx` 加 `whiteboard` / `whiteboard/:boardId` | ✅ 现有 HashRouter |
| 导航 | **工具箱** `ToolboxPage` 创作工具区磁贴「白板」→ `/whiteboard`（**不进** `Sidebar` `NAV_ITEMS`，见 §四.2） | ✅ 现有工具箱 |
| 认证/会话 | **零接线**——同 origin，复用 `services/api.ts`（凭证式 + 401 refresh + CSRF） | ✅ |
| 配色 | 全程用 `@agentcore/design-tokens` 语义 token（[color-tokens](/.cursor/rules/color-tokens.mdc)）；自研引擎从零用 token，无 vendored 样式 | ✅ |
| 契约 | 复用 `@agentcore/contract-rest-types`（boards 端点落地后重生成） | ✅ |
| 依赖 | **自研引擎无第三方画布依赖**；仅按需引底层算法库（`perfect-freehand` 手绘、远期 `yjs` 协作，§五.2） | — |

### 四.1 为什么 A 不是 B（决策依据，2026-06-25）

被否决方案：**B 独立 web app（`apps/whiteboard`）+ 桌面窗口入口**。否决理由（三问压测后）：

- **受众**：web 触达「不太需要」——不面向不装 app 的外部用户。
- **协作**：要的是「自己人同板」（都装了 app 的用户 / 多 Agent），靠**后端 sync** 即可，桌面 app 照样能做（Figma / Linear / Notion 桌面端皆如此）——**协作 ≠ web**。只有「外部链接分享给没装 app 的人」才逼出 web，而那条已判「不太需要」。
- **工程**：A 进程内全复用桌面 auth / chat / files / run / SSE，M2/M3 显著更省。
- **已接受风险**：万一日后要「外部链接分享」，A→web 回填较贵（基本重写为独立 web app）；届时再走内嵌 / co-bundle。

### 四.2 导航：工具箱入口，不设侧栏直达（✅ 2026-06-27）

**决策**：白板从 **工具箱 → 创作工具** 磁贴进入（`ToolboxPage` `id: "canvas"` → `/whiteboard`），**不**在主导航侧栏 `NAV_ITEMS` 单列一项。

| 考量 | 结论 |
|---|---|
| 侧栏 IA | 侧栏锚定**高频主路径**（对话 / 文件 / 消息 / 工具箱 / 探索）；白板与幻灯片、流程图等同属**创作工具**，归工具箱更一致 |
| 认知负担 | 避免侧栏再增一项稀释「管 Agent 团队」主心智；需要白板时用户已习惯在工具箱找创作能力 |
| 工程 | 路由与页面不变；仅入口落在 `ToolboxPage`，**不**改 `Sidebar.tsx` |

**否决**：初稿 §四 曾写「侧栏加白板」——与当前产品分层不符，**以本节为准**；代码现状已与决策对齐（→ 见 `pages/ToolboxPage.tsx`）。

---

## 五、渲染引擎选型：自研原生引擎（✅ G1 = 自研 · 2026-06-27 推翻原 Excalidraw 决策）

> **决策反转（2026-06-27，人拍板）**：原方案「v1 用 stock Excalidraw」**已撤销**。经充分压测原「否决自造」论证后，产品负责人在「**产品级美学 + Agent 节点原生 + 数据模型自主 + 零第三方授权 + 一体化**」的综合诉求下，明确选择**自研原生无限画布引擎**，并接受其工程代价。本节记录新决策理由、被撤销 / 否决方案、以及自研的已接受代价与护栏。

### 五.1 为什么自研（决策理由）

1. **护城河第一公民**——Agent 任务节点 / 产物卡做成**原生形状**，第一天就与矩形、箭头**完全平权**（原生绑定 / 吸附 / 缩放 / 命中 / 序列化 / 协作）。这正是 AgentCore 心智「白板里有一支 AI 团队」的兑现；嵌第三方引擎做不到（Excalidraw 无自定义形状一等机制，只能近似）。（"brief 区"**不做原生形状**——brief = 选区 / `frame`，见 §六/§九。）
2. **产品级美学完全可控**——不背 Excalidraw 的手绘草图风，也不受任何引擎默认观感约束，从零定义「产品级」白板气质（用户对原 Excalidraw 版「不像别的白板产品」的不满，正源于此）。
3. **数据模型自主**——scene 格式为 AgentCore 量身定义，三类特有元素是**一等公民**，不挂在别人的 `customData` 上、不受 `.excalidraw` / `.tldr` 格式牵制。
4. **零第三方依赖 / 授权 / 受制风险**——不付授权费、不背 fork merge 税、不受上游 API / license 变更牵制。
5. **白板与 AI 团队一体设计**——当成**一个产品**从头设计，而非把 AI 焊在外来引擎周边。

### 五.2 已接受的代价与护栏（诚实记账）

自研要自己啃通用画布引擎层的领域难题——**这些对护城河零贡献，是自研的已接受代价**，文档不假装它消失：

| 难点 | 性质 | 护栏 / 策略 |
|---|---|---|
| 手绘笔迹平滑 | 算法 | 借成熟开源库（`perfect-freehand`）做底层，不自推算法 |
| 箭头吸附与重路由 | 公认地狱级 | 分阶段：先直线 / 折线绑定，避障重路由延后到验证刚需 |
| 画布内中文 IME 文字编辑 | 边界 case 多 | 早做早测真实中文输入（隐藏 textarea + 测量回投范式） |
| 多选变换 / 对齐吸附 / 撤销重做 | 基础体验 | 列为 MVP 必做；用统一 command / transaction 模型承载 undo |
| scene 序列化与迁移 | 长期债 | 第一天就 `schemaVersion` + 迁移器，不留后患 |
| 多人 / 多 Agent 协作 CRDT | 远期 | 可选 `yjs` 等成熟 CRDT 库，不自研协作内核（§十二 留缝） |

> **核心风险 = 机会成本**：自研引擎的长尾别吃掉 AI 团队（护城河）的开发预算。护栏：**通用功能够用即止、火力集中在 AI 差异化**；底层算法**借库不重造**（freehand / CRDT）；分层渐进交付（先画布原语 MVP，难点逐个攻）。一旦发现自研引擎拖累 Hero 进度 → 即停复盘（[dev-process](/.cursor/rules/dev-process.mdc)）。

### 五.3 被撤销 / 否决的方案（各留一行）

- **stock Excalidraw**（原 G1 决策，**2026-06-27 已撤销**）：MIT $0，但**手绘草图风不达产品级** + **Agent 节点非原生**（只能近似，画布上拿不到原生绑定 / 吸附），不满足美学与护城河刚需。
- **tldraw**（否决）：原生自定义形状开箱、产品级美学，但**商用授权年费** + 仍是**第三方引擎与 `.tldr` 格式**，控制权不在自己。
- **Fork Excalidraw**（否决）：$0 + 改后代码归己，但背 **merge 税**，且受其封闭元素模型架构约束，自定义形状仍非真一等。

### 五.4 复用：AI 读写画布的设计与引擎无关

引擎换成自研，但「AI 读写画布」的产品设计**整体复用**：**读** = scene 是纯 JSON（天然喂 LLM）；**写** = AI 只产**结构化骨架 / ops**（add / move / connect / group），宿主侧布局助手（grid / dagre）算坐标，AI 不算像素（规避「4 失败点」，§七）。自研引擎只需提供等价的 `getScene()` / `applyOps()` / `onChange()` API（§六）。**已落地的后端 AI-ops 协议（`board_ops` + `BoardChannel`，§十 M2）与引擎无关、整体保留**；本次反转主要影响**前端渲染 / applier 层**（从 Excalidraw 换成自研引擎）。

---

## 六、自研引擎架构（as-built）

> **定位**：`apps/desktop/src/renderer/whiteboard/` 的**现状说明书**——分层、模块职责、数据流、跨模块不变量。回答「读完代码后还缺什么」。**why / 选型**见 §五；**数据契约**见 §七；**里程碑**见 §十。冲突以代码为准。
>
> **状态（2026-06-29）**：引擎核心 **✅ 已落地**——渲染、交互（指针状态机 / 拖拽边·中线吸附参考线 / 橡皮 / 旋转 / 透明度 / 锁定）、历史、选择运算、文本浮层、手绘平滑（`perfect-freehand`）、图片导入、AI ops、读图栅格化、持久化；`agentNode` / `artifactCard` **✅ 已接真实 run**（M3 浮层贴源 + crystallize + 迭代）。`briefRegion` 已砸（brief = 选区 / `frame`，§九）。

引擎已定（**G1 ✅ 自研**）。**通用画布层**够用即止（§五.2），**AgentCore 差异层**是护城河（`agentNode` / `artifactCard` 原生一等形状，非挂 `customData`）；`schemaVersion` 是 scene 迁移后悔药（§七）。**brief 不做原生形状**——= 当前选区或 `frame`（§九）。

### 6.1 分层与模块

引擎按「**纯核心 → 有状态编排 → DOM 浮层 → React 壳 → 宿主页 → AI 通道**」分层，越靠下越纯、越好测；模块清单与各自职责 → 见代码 `apps/desktop/src/renderer/whiteboard/` + `services/board*.ts`（文件名即职责）。单文件读不出的要点：

- `SceneElement` 是**单一接口按 `type` 判别**（非严格联合，MVP 取紧凑）；`schemaVersion` 是每元素迁移后悔药；M3 字段（`runStatus` / `runId` / `ref` …）对通用形状是可选噪音、仅 `agentNode`/`artifactCard` 读。
- 命中容差按 `1/zoom` 缩放；历史是**整数组快照**（非逆操作），push/undo/redo 各自深拷。
- `render.ts`：元素在 world 变换下画、选择装饰在 screen 空间画（求 1px 锐利）；`agentNode` / `artifactCard` 与 M3 进度浮层复用**同一** `RunVisualStatus`→调色板映射。
- `boardProgress` / `boardCrystallize` 是**纯投影函数**（run 树 → 元素），是 M3 的测试主战场。
- 布局助手（`layout.ts` 网格 / `layoutDagre.ts` DAG）在宿主侧算坐标——对应 §七「AI 只产结构、宿主算坐标」。

### 6.2 坐标系与视口

- **两套坐标**：元素几何全是 **world**；`Viewport { panX, panY, zoom }` 在重绘时映射 world→screen：`screen = world * zoom + pan`。
- **谁负责换算**：指针事件先经 `engine.toWorld()`（`geometry.screenToWorld`）落到 world 再处理；`render.ts` 在 `ctx.translate(pan)+scale(zoom)` 下画元素、在恒等变换下画选择装饰。
- **特例**：`freedraw.points` 相对元素 `(x,y)`，**落笔结束经 `perfect-freehand` 平滑成轮廓多边形**（填充描边，非原始采样点）；`arrow`/`line`（linear）`.points` 是**绝对 world**（未绑定时用），绑定后端点由 `arrowEndpoints` 按绑定元素实时算并裁到框边——所以拖动绑定元素，箭头自动跟随。`image.src` 存 data URL（粘贴/拖入，导入时降采样），渲染走 `ImageCache` 异步解码；移动/缩放/选择/历史与矩形同构（命中即 `pointInBox`）。`rotation` 元素命中测试**反旋**回正交框再测。

### 6.3 数据流

四条主流（细节见代码 `WhiteboardCanvasPage.tsx`）：**加载**（getBoard → `parseScene` → `loadScene`）；**编辑 → 防抖 autosave**（`onChange` → 1.5s 防抖 → CAS 保存，conflict 暂停不覆盖）；**AI 作画**（`sendBoardTurn` → SSE `board_op_required` → `applyOps` → CAS 保存 → resolve 回执）；**M3 团队照白板**（订阅活 run 树 → `setOverlay` 瞬时浮层 → 终态 `addElements` crystallize → 一次 CAS 落库）。

- **重绘循环**：所有改动调 `scheduleRender()`，单帧 `requestAnimationFrame` 合并；`render()` 整帧重画（无脏矩形，MVP 够用）。
- **autosave 触发面**：仅 `onChange`（元素提交）触发；**pan/zoom 不触发 onChange**——导航不写库。`savedSceneRef` 对序列化结果去重，跳过 no-op 保存。
- **M3 团队照白板**：发起复用 `sendBoardTurn`(pipeline)，CEO 自主 `delegate`/`debate`（零新编排）；进度走**瞬时浮层**（`setOverlay`，逐帧投影活 run、**不写库不进历史**），仅回合**终态**把完成 worker **crystallize** 成持久 `agentNode`/`artifactCard` 经 `addElements`（一次历史步）+ 一次 CAS 落库（`crystallizedExecRef` 保幂等、随后清浮层无缝交棒）；迭代回喂上一版、新版按新 `runId` **贴旁留旧**。

### 6.4 关键不变量与约束（代码外的全局契约）

> 这些是分散在多个文件、靠读单文件**看不全**的约定；改引擎前先认。

1. **历史不别名**：变更前 `history.push(before)` 内部 `cloneElements` 深拷；`selectionOps` 返回的新数组里未动元素**保留旧引用**，但旧引用已被快照深拷固化，故撤销恢复的状态与实时场景**互不影响**。新增 mutate 路径务必走 `engine.commit()` 或显式 `history.push`。
2. **纯运算 + 薄委托**：选择类操作（编组/层级/对齐/分布/样式/微移/复制）一律落在 `selectionOps` 纯函数，引擎方法只做「快照→换场景→`emitChange`」。新功能优先加纯函数 + 单测，再在引擎接一行。
3. **引擎独占可变态**：只有 `engine` 持有可变 `elements` 与 `history`。`textEditor` / `selectionOps` / `ops` 都不直接改它们——文本浮层把结果经 `onCommitText` 交还引擎的 `commitText` 落库。
4. **编组扁平模型**：一个元素一个 `groupId`（无嵌套）；选择是**组感知**的——`withGroup` 把任一组成员的点击/框选/右键扩成整组。
5. **线性元素（箭头/直线）**：`points` 绝对 world + 可选 `start/end` 绑定（端点取绑定元素中心、裁到框边）；删除被绑定端点的元素时**连带删除**该箭头（`ops`/`deleteSelected`/橡皮 都遵守）；选择 bbox 按实时端点算（绑定移动也对）。`line` 与 `arrow` 共用 linear 路径，仅 `line` 不画箭头头部。
6. **持久化容错**：`parseScene` 对未知/旧格式（含旧 Excalidraw blob）返回**空画布**，dev 期**不做兼容迁移**；逐字段 normalize 防脏数据。`schemaVersion` 为将来迁移留口。
7. **CAS 不覆盖**：autosave 带 `version` baseline；服务端回 `conflict` 即暂停 autosave、提示重载，**绝不盲覆盖**（§七）。
8. **AI applier 生命周期**：applier 按 board id 注册、**仅画布打开时在册**；对未打开的板，`board_op_required` 干净失败（「画布未打开」）而非挂死回合。
9. **配色合规**：所有颜色走设计 token（`colors.ts` 读 CSS 变量），无硬编码十六进制——`check-ui-tokens` 门禁。
10. **锁定与旋转**：`locked` 元素被命中 / 框选 / 移动 / 缩放 / 删除 / 橡皮**整体跳过**，直到右键「解锁 / 解锁全部」，渲染加锁标；`rotation`（仅非线性元素）只影响绘制与命中（反旋回正交框），存储几何 bbox 仍按未旋——选择 / 缩放 / 持久化都用正交 bbox。
11. **瞬时浮层 vs 持久 crystallize（M3）**：run 进度走 `setOverlay`——浮层元素**画在主场景之上但不进 `elements`/历史/序列化/命中/autosave**，纯展示、可随时整组替换；**只有回合终态**才把产物经 `addElements` 落进 `elements`（一次历史步、可撤销、触发一次 CAS autosave）。crystallize 按 `runId` 幂等（`crystallizedExecRef` + 场景已存 `runId` 双重去重），重复终态/重挂不产生重复卡；落库后清浮层无缝交棒。**新增 run 可视化务必先走浮层**，别把中间态写进 `elements`。

### 6.5 引擎对外 API（`WhiteboardApi`）

宿主只通过这个命令式句柄驱动引擎（`WhiteboardCanvas` 经 `ref` 暴露）；方法清单 → 见代码 `whiteboard/types.ts`（`WhiteboardApi`）。契约要点：`setOverlay` 为**瞬时**浮层（不入 scene/历史/序列化/命中）、`addElements` 为**一次历史步**（可撤销、触发 autosave）、`rasterizeElements` 离屏重绘 ≤1024px 无选择装饰（读图 §九.2）。引擎内部另有样式/编组/剪贴板/层级公开方法（供 React 壳调用），不在宿主契约里。

### 6.6 测试与门禁

- **单测主战场 = 纯核心与纯投影**（`whiteboard/__tests__/` + `services/__tests__/`，vitest）；引擎状态机靠类型 + 前端预览回归，浮层/crystallize 视觉靠 `#/preview` 回归。
- **门禁**：`pnpm typecheck`、`pnpm lint`（biome + `check-ui-tokens`）。
- **自检渲染**：`#/preview` 回放 + `pnpm shoot` 无头截图（见 [frontend-preview](/.cursor/rules/frontend-preview.mdc)），别靠跑真实 AI 看前端。

---

## 七、数据模型与契约

- **典范模型 = 场景 JSON**（scene：形状 / 位置 / 连线 / 分组 / 手绘笔触）。一块 board = 一条记录 + 一份 scene blob。两类 AgentCore 特有元素（`agentNode` / `artifactCard`）是**自研引擎一等形状**（非挂第三方 `customData`），机制见 §六；**brief 不是元素**，= 选区 / `frame`（§九）。
- **AI 读写原则**：**写**走**结构化运行时 ops**（add/move/connect/group），**不**走「让 AI 生成整张图片」，规避表达走工具的「4 失败点」（[工具与能力系统 §3.2](/docs/03-AI核心/工具与能力系统.md)）；**读 = 同一选区混合**：结构元素直接读 scene JSON（`getScene`，精确便宜），手绘 / 截图子集才栅格化喂视觉模型（G6）。自研引擎侧落地见 §六。
- **`boards` 表（Postgres）**：`id` / `user_id` / `folder_id`（G3）/ `title` / `scene`（小场景内联 JSONB）/ `scene_blob_ref`（超阈值 S3 指针，G4）/ `version`（CAS）/ `created_at` / `updated_at`。
- **存储阈值（G4 ✅）**：scene JSON < **256 KB** 内联行内 JSONB；≥ 256 KB 落 S3、行内只存 `scene_blob_ref`。autosave 防抖 **~1.5s**；版本历史 = 保留**最近 K 次 autosave + 显式命名快照**（K 默认 20，实现细节可调）。复用 AgentCore 存储栈（PostgreSQL / Redis / S3，见 [技术架构与基础设施](/docs/02-架构/技术架构与基础设施.md)）。
- **REST 契约**：新增 `/v1/boards` CRUD，**照 [`folders.py`](/apps/server/agentcore/api/routes/folders.py) 范式**——`AuthUser` 作用域、非属主 404（IDOR-safe）、`repository` 模式、Pydantic schema 在 route 层转换。CAS 写法照 [`memory.py`](/apps/server/agentcore/api/routes/memory.py)：full text + `version` baseline，冲突回 `conflict` 不覆盖。
- **类型单一源**：route + schema 落地后 → 重生成 `pnpm -C packages/contract-rest-types gen`（`openapi-typescript apps/server/openapi.json`），白板前端 import 生成类型，不手写。
- **DB 迁移**：alembic 新 revision（照 `db/migrations/versions/` 现有范式）。
- **实时协作**（多人 / 多 Agent 同板）：按「无第二需求不预建」留缝，v1 可先单人 + AI，协作 sync 远期（§十二）。

---

## 八、后端接线（零新编排，守绊线）

白板**复用桌面客户端现有的** run 发起 + 事件流（进程内），不动 engine / loop / 调度（[dev-process 补丁绊线](/.cursor/rules/dev-process.mdc)）。

| 地基 | 复用方式 |
|---|---|
| 账号 / 认证 | **零接线**：白板是 desktop 内页面，同 origin 复用 `services/api.ts`（凭证式会话 + 401 refresh + CSRF），无新 CORS / 登录 gate |
| 发起团队 run（M3 ✅） | **进程内**复用 `sendBoardTurn`(pipeline)：白板选区 → 组 brief → 起回合，CEO 在回合内自主 `delegate` / `debate`（pipeline = 唯一入口、二者是回合内工具，**非平行入口**）；**不写新编排** |
| 事件流（M3 ✅） | 复用 SSE / 协议 fold：活 run 树 → `agentNode` 进度浮层（贴源）→ 终态 crystallize 持久卡，**零新增 fold** |
| LLM / 读图 | 复用云推理代理 `/v1/inference`（含**视觉模型**读选区中手绘 / 截图子集，G6） |
| 产物回贴 | 复用 `files` / 工作区；board ↔ 工作区加**导出接缝**（board → 图 / md / 产物入工作区），不反向破坏文本典范 |
| 存储 | Postgres + S3（§七） |
| 类型契约 | 复用 `@agentcore/contract-rest-types`（OpenAPI 单一源，[pnpm-workspace](/pnpm-workspace.yaml)） |
| desktop 接线 | **不新增 app**——`apps/desktop` 加 `WhiteboardPage` + 路由 + 工具箱入口 + **自研画布引擎模块**；复用桌面构建 / 认证 / run / SSE |

> **接缝而非内核改造**：白板对 AgentCore 后端是**又一个发起 run + 读事件流的客户端**，不动引擎 / loop / 调度。一旦发现「为白板改编排器」→ 立即停、提根因（[dev-process 绊线](/.cursor/rules/dev-process.mdc)）。
>
> **协议 fold**：白板是新渲染面，组件层不进 conformance；`agentNode` 状态**直接复用桌面现有 run 事件 fold**（`conformanceFold`，已过 conformance），零新增 fold（[protocol-conformance](/.cursor/rules/protocol-conformance.mdc)）。

---

## 九、读图（G6）施工级设计 ✅ 链路 + OpenAI 兼容参考实现已落地 / 具体视觉模型待选定

> **状态**：**链路 + 一个 OpenAI 兼容参考实现 2026-06-27 已落地 ✅**（`board_read` 工具 + `BoardChannel.read` + `board_read_required` 事件 + 桌面 `rasterizeElements` / `boardRead.ts` reader + `VisionReader` 端口 + 参考实现 `QwenVLReader`，单测 + conformance 绿）；**具体视觉模型待用户选定（⏳，可随时换）**。**同日重定（砸 briefRegion）**：读图**不再是单独的「圈 briefRegion」流程**，而是**并入 select→go 主路径**——brief = 当前选区（或一个 `frame`），发给 AI 时**混合 payload**：结构元素走 scene JSON（精确便宜、无需视觉），手绘 / 截图子集才栅格化喂视觉模型。行业（tldraw Make Real / Figma Make / Miro Sidekicks）均「选区即 prompt、结构+视觉一起发」，故砸掉人造的 `briefRegion` 形状（§六）。**视觉解读节点抽象成 `VisionReader` 端口**——因 **DeepSeek V4 无多模态**（已确认），视觉是独立 provider（成本 / 密钥 / 选型，[dev-process](/.cursor/rules/dev-process.mdc) AI 提案 → 人确认）；已落地一个 OpenAI 兼容参考 `VisionReader`（`QwenVLReader`），**换模型 = 改 `VISION_BASE_URL`/`VISION_MODEL`（任意兼容端点）或加一个适配器（异构 API 如 Claude/Gemini 原生）**。

**端到端链路**：人选中含手绘 / 截图的元素 → 触发回合（整理 / 让团队实现）→ 宿主把选区拆「结构子集（→ JSON）+ 手绘/截图子集」→ 后者经 `board_read` **栅格化为 PNG** → `board_read` 调 `VisionReader.read(png)` 得**文字解读** → 与结构 JSON 一起作为 brief 回 agent → agent 据此 `board_ops` 落元素。视觉是**一次性子调用**，**不**把主 ReAct 循环多模态化（§八 守绊线）。

### 九.1 brief = 选区（无新元素类型 · §六 砸 briefRegion）
- brief **不再是原生形状**；= 当前**选区**（一次性 ad-hoc）或一个 `frame`（常驻工作流区，右键发起、随 scene 持久化）。
- 选区拆两半：**结构元素**（便签 / 文字 / 形状 / 连线 / 卡）→ scene JSON，**不进视觉**；**手绘 / freedraw / image / 截图** → 进视觉子集。
- **无「标为 brief / 套框」步骤**——选了就发，符合行业「选区即 prompt」；省一个元素类型、一条圈定交互、一份迁移负担。

### 九.2 桌面栅格化（provider 无关 · 可施工）
- 用自研引擎的 `rasterizeElements(ids)`（§六）：取选区中手绘 / 截图子集，按其并集 bbox 离屏重绘 → PNG → base64。
- 体积护栏：导出设 `maxWidthOrHeight`（如 1024）压尺寸；base64 入日志**必须截断**（[logging](/.cursor/rules/logging.mdc) 铁律：不落完整正文）。
- 落点：`WhiteboardCanvasPage` 与 applier 同层新增 `rasterizeElements(ids): Promise<{ pngBase64, w, h }>`，按 board id 注册进一个 reader 注册表（仿 `registerBoardApplier`），**只在画布打开时可用**。

### 九.3 board_read 通道（provider 无关 · 可施工 · 复刻 board_ops）
- 工具：`tools/builtin/board_read.py`（`board_read`），**仅白板会话可用**——同 `board_ops` 的 `ToolContext` 守卫（无通道则返回干净错误，不触碰画布）。入参：要栅格化的**元素 ids**（选区中手绘 / 截图子集）。
- 通道：仿 `BoardChannel`（`board/channel.py`）——`suspend(request_id, kind=CLIENT_TOOL, payload={ids})` → `on_suspended` 发 `board_read_required` → 桌面栅格化回填 → future 落定；超时 / 画布未开 → 映射成**失败 tool 结果**（同 board_ops，不挂死回合）。
- 事件 + 契约：`runtime/events/board.py` 加 `board_read_required`；**与 `board_op_required` 同属 `client_tool` 交互事件**，沿用其契约重生成 + 两端处理范式（[protocol-conformance](/.cursor/rules/protocol-conformance.mdc)：是否进 fold 照 `board_op_required` 既有处理）。
- 桌面：`services/sse/handlers/board.ts` 加 `board_read_required` 分支 → 调 `rasterizeElements` → `resolveInteraction(convId, requestId, { kind:"client_tool", ok, value:{ pngBase64, w, h } })`（仿 `boardOps.ts` 的 `performBoardOp`）。

### 九.4 视觉解读节点 = `VisionReader` 端口（✅ 端口 + OpenAI 兼容参考实现已落地，模型可换）
- 端口（先定接口）：`class VisionReader(Protocol): async def read(self, png_b64: str, prompt: str) -> str`——输入 PNG + 提示，返回对图的**文字解读**。
- 接线：`board_read` 拿到 PNG 后 `text = await ctx.vision_reader.read(png, "把这张手绘/截图当作需求 brief，描述其结构与意图")`，把 `text` 作为 `ToolResult.output`（**纯文本**）回主 agent → 主 DeepSeek agent 据此 `board_ops`。
- **参考实现 = `QwenVLReader`（OpenAI 兼容，模型可换）**：`vision/qwen.py` 走标准多模态 `/chat/completions`，图以 `image_url`（`data:image/png;base64,…`）入参——**指向任意 OpenAI 兼容视觉端点即用**（改 `VISION_BASE_URL`/`VISION_MODEL`：智谱 GLM-4V / 豆包 / Kimi-VL / GPT-4o / 本地 vLLM…）；异构 API（Claude/Gemini 原生）另加一个 `VisionReader` 适配器。`vision/factory.py::build_vision_reader(settings)` 在 pipeline（`run.py` / `resume`）按 `VISION_API_KEY` 注入：**空 key → `None`**，`board_read` 返回干净「读图能力未配置」错误（不假装、不挂起）；**填 key → 即启用**，§九.1–九.3 全不动（「插上即用」）。错误（401/402/429/超时/5xx/空回复）映射成典型 LLM 错误 → `board_read` 收成失败 tool 结果。配置：`apps/server/.env` 的 `VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL`。
- 落账（✅ 已落地）：视觉子调用除 `log_llm_call(scenario="vision.board_read")` 可观测外，**已入 `cost_events` 账本**。链路：`QwenVLReader.read` 回传 `VisionReading{text, usage, model}` → `BoardReadTool._bill_vision` 经 `runtime/costing.py::vision_run_cost`（`role=vision`、parented 到调用 run、独立 `vis_` id、按 `calculate_cost` 一次定价）写进 `ToolContext.cost_sink` → pipeline（`run.py` + `resume/{pipeline,finish}.py`）把该 sink 折进回合 `cost_runs` → 落 `cost_events`（迁移 `e7a2d9c4f1b8` 放开 `role=vision` CHECK 约束、`db/models/billing.py` 同步）。视觉模型 ≠ run 的 DeepSeek，故**独占一行不并进 run usage**；无 sink（测试 / 无白板）或 stub reader 零 usage 则不计费。单测：`test_board_read_channel.py::test_tool_bills_vision_subcall_into_cost_sink` + `test_costing.py::test_vision_run_cost_prices_subcall_under_vision_role`。

### 验收
- **链路 + OpenAI 兼容参考 `VisionReader` ✅ 已落地**：选区中手绘 / 截图子集经 `board_read` → `rasterizeElements` 成 PNG 回到后端（结构元素走 JSON）→ `QwenVLReader` 解读成文字回主 agent；空 key 时返回明确「未配置」错误而非挂起。代码：后端 `tools/builtin/board_read.py` / `board/channel.py::read` / `vision/{protocol,qwen,factory}.py`，前端 `services/boardRead.ts` / `whiteboard/engine.ts::rasterizeElements`；事件 `board_read_required` 已并入契约 + 三端 fold no-op。单测：`tests/test_vision_qwen.py`（MockTransport：图入参形状 / 文字解析 / 错误映射 / 工厂开关）+ `tests/test_board_read_channel.py`。
- **整理选区入口 ✅ 已切混合 payload**：右键「整理选区」→ `boardTurn.ts::organizeSelectionPrompt` 按类型拆分——结构元素走文字描述（CEO 用真实 id `board_ops`），`freedraw` 手绘让 CEO 先 `board_read` 读懂；单测 `boardTurn.test.ts`（structured-only / mixed / pure-visual）。
- **视觉子调用入账 ✅ 已落地**：`board_read` 读图成功即按 `role=vision` 在回合 `cost_events` 写一行（独立 `vis_` id、parented 到调用 run、按 qwen-vl-max 价定一次），不并进 run usage；迁移 `e7a2d9c4f1b8` 放开约束。单测绿（`test_board_read_channel.py` 入账 / 无 sink / stub 零 usage 三例 + `test_costing.py` 定价例）。
- **选模型 + 端到端实跑 ⏳ 待人验**：默认 `qwen-vl-max`（已接已定价）；选定具体视觉模型（改 `VISION_*` 或加适配器）并配 `VISION_API_KEY` 后，Hero——手绘 brief 被读懂、AI 据此摆元素端到端跑通（即 §十 M2 的读图验收项）。

---

## 十、交付现状（M1–M3 as-built）

> 「AI 团队第一天就进」是产品要求，M1–M3 同属 v1，工程上按引擎→助手→团队分步交付，**后端零新基建**（复用现有 run 原语）。下面是各步 as-built 状态（详细机制见 §六/§九；冲突以代码为准）。

### M1 白板骨架 ✅ 已落地
- 任务：`apps/desktop` 建**自研画布引擎模块** → `WhiteboardCanvasPage`（全屏画布）→ 路由 + 工具箱入口 → 落 `boards` 表 + `/v1/boards` + autosave 落库。
- **验收**：工具箱「白板」可进；能画 / 平移 / 缩放；建 / 存 / 开 board；刷新不丢；autosave 冲突回 `conflict` 不覆盖。
- **现状 ✅**：自研画布引擎模块（§六）+ `WhiteboardCanvasPage` + 路由 + 工具箱入口（§四）全部落地；后端 `boards` 表 + 迁移 `b1d7f3c9a2e4` + `/v1/boards` CRUD（照 `folders.py` 范式）+ autosave 1.5s 防抖 + CAS `conflict` 不覆盖（→ 见代码 `apps/desktop/src/renderer/pages/WhiteboardCanvasPage.tsx`、`apps/server/agentcore/api/routes/boards.py`）。

### M2 AI 助手进板 ⚠️ 部分落地（结构化 ops ✅ / 读图 G6 链路 + Qwen-VL provider ✅ · 视觉子调用入账 ✅ · 端到端实跑待人验）
- 任务：AI ops 适配器（add/move/connect/group → 自研引擎 `applyOps`）+ 布局助手；**选区混合读图**（结构 → JSON，手绘/截图 → 栅格化喂视觉，§九）；一个 AI 操作入口（选区 →「帮我整理 / 生成结构」）。
- **验收**：选区 → AI 加便签 / 连线 / 排流程可见；手绘 brief 能被读懂并据此摆元素。
- **现状 结构化 ops ✅**：**后端** `board_ops` 工具 + `BoardChannel`（run 挂起 → `board_op_required` 事件 → CAS 保存 → resolve 回执）+ 老板命令栏 + 整理选区 + resume 重绑全链路通；**前端 applier 接自研引擎 `applyOps`**（§六 `ops.ts::applyBoardOps`）（→ 见代码 `apps/server/agentcore/tools/builtin/board_ops.py`、`apps/server/agentcore/board/channel.py`）。
- **读图（G6）✅ 链路 + OpenAI 兼容参考 reader + 混合 payload 入口已落地**：`board_read` 工具 + `BoardChannel.read` + `board_read_required` 事件 + 桌面 `rasterizeElements` / `boardRead.ts` reader + `VisionReader` 端口 + 参考实现 `QwenVLReader`（OpenAI 兼容，模型可换）经 `build_vision_reader` 注入 pipeline 全部就位；**「整理选区」入口已切混合 payload**（`boardTurn.ts::organizeSelectionPrompt`：结构走 JSON 文字，`freedraw` 手绘 + `image` 粘贴/拖入截图让 CEO `board_read`），单测 + conformance 绿。配 `VISION_API_KEY` 即真正读图，未配则得干净「未配置」错误。**②（视觉子调用入 `cost_events` 账本）已落地 ✅**：`role=vision` 行，迁移 `e7a2d9c4f1b8`，单测绿（§九.4 落账）。**唯一缺口 ⏳**：选定具体视觉模型 + 配 `VISION_API_KEY` + 端到端实跑验收（默认 `qwen-vl-max` 已接已定价，改 `VISION_*` 或加适配器，§九.4）。

### M3 AI 团队照白板干活 ✅ 已落地（Slice 1–4，2026-06-29）
- 任务：**选区 / `frame`** →「让团队实现」→ 发起 run → 进度**贴源**（实时浮层）→ 终态 **crystallize** 持久 `agentNode` / `artifactCard` → 产物**迭代**（新版贴旁留旧）。
- **落地（提案 A：复用 `sendBoardTurn`(pipeline) + CEO 自主 `delegate`/`debate`，零新编排 / 零新 fold）**：
  - **发起**：选区浮动条「让团队实现」→ `boardTurn.ts::implementSelectionPrompt` 组 brief（结构走 JSON 文字、手绘/截图走 `board_read`，§九 混合 payload）→ CEO 自主拆解。
  - **进度贴源**：订阅本 board 会话活的 run 树（`useBoardExecution`→`useMessageExecution`，复用既有 `projectExecution`、零新 fold）→ `boardProgress.ts::buildProgressOverlay` 投影成**瞬时浮层**贴 brief 旁、箭头指 brief；引擎 `setOverlay`（不入 scene / 历史 / 序列化 / 命中）。
  - **产物回贴**：回合终态 → `boardCrystallize.ts::buildCrystallizedElements` 把每个完成 worker 固化成持久 `agentNode` + `artifactCard`（连线、指回 brief），经引擎 `addElements` **一次 CAS 落库**；按 `runId` 幂等去重，浮层无缝交棒（持久化不变量见 §6.4）。
  - **迭代**：选产物卡「迭代」→ `iterateArtifactPrompt` 回喂上一版 + 批注 → 新回合；新版卡片**贴旁留旧**（同一 crystallize 按新 `runId` 追加）。
- **验收**：Hero 端到端跑通（发起→进度→产物→迭代）；同一 board 多轮迭代历史可追（旧版留痕）。
- **v1 边界（干净接缝，非裁需求）**：产物为**文本**（worker `outputSummary`）；`artifactCard` 的 `ref` / `artifactKind` 字段已留，**`@` 回工作区文件**待后端给出文件产物信号再接；迭代版本用**空间留痕**而非 vN 角标；迭代入口走浮动按钮（`frame` 右键延后）。as-built 实现见 §六。

---

## 十一、风险与护栏

| 风险 | 护栏 |
|---|---|
| 自研引擎长尾吃掉护城河预算 | 通用功能够用即止、火力集中在 AI 差异化；底层算法借库不重造（freehand / CRDT）；分层渐进交付；拖累 Hero 即停复盘（§五.2） |
| 「又一个 Miro」（无差异） | 守住 Hero = AI 团队；纯白板部分够用即可，不在通用功能上卷 |
| 范围蔓延 / 重复造轮子 | 不把 `ConversationCanvas`、mermaid、文件列表搬进来重做（§一已界定重叠） |
| AI 在空间画布的「4 失败点」回归 | AI 摆元素走**结构化运行时 ops**，绝不强行让 AI「画」整图（§七） |
| scene 迁移坑 | 元素 `schemaVersion` + 迁移器第一天就留好（§六） |
| 并发写 / 协作 | 协作 = 自己人同板，走后端 sync（远期）；即便单人，人与 AI 也并发写板 → 定 `id→element` 合并策略 |
| 空间 JSON 与文件体系割裂 | 独立产品故合规；若需互通，加**导出接缝**（board → 导出图 / md / 产物入工作区），不反向破坏文本典范 |
| 为白板改内核 | [dev-process 绊线](/.cursor/rules/dev-process.mdc)：即停、提根因重设计 |

---

## 十二、未定项

| 议题 | 选项 |
|---|---|
| 实时协作（多人 / 多 Agent 同板） | v1 单人 + AI vs v1 即上 sync（倾向前者，留缝不预建——§五.2 可选 `yjs` 等成熟 CRDT，不自研协作内核） |

> **唯一缺口（2026-06-29）**：读图端到端实跑验收——配 `apps/server/.env` 的 `VISION_API_KEY` 选定具体视觉模型（默认 `qwen-vl-max` 已接已定价，§九.4）即可。其余 M1–M3 + 读图链路 / `VisionReader` / 视觉入账（`role=vision` 行 + 迁移 `e7a2d9c4f1b8`）均已落地 ✅。
