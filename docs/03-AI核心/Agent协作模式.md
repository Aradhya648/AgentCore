---
status: landed
code: apps/server/agentcore/runtime/runs/
related:
  - docs/03-AI核心/运行时总览.md
  - docs/03-AI核心/编排器与CEO主Agent.md
skip_if:
  - 只改 CEO delegate 字段（读编排器）
---

# Agent 协作模式

> **权威**：协作哲学、通信、`escalate` / handoff、便签墙、冲突裁决。编排字段 → [编排器](/docs/03-AI核心/编排器与CEO主Agent.md)；辩论 → [辩论编排](/docs/03-AI核心/辩论编排设计.md)。
>
> → 见代码: `apps/server/agentcore/runtime/runs/`

## 一、哲学

Multi-Agent First：组合优于堆叠；单 Agent = 无成员的 Team（统一执行路径）；委派一等公民（depth&lt;2 默认 `delegate`+`replan`；depth=2 叶子；单 lead ≤4 sub）；形状由 `depends_on` 数据决定，非独立模式枚举。

| 范式 | 表示 |
|---|---|
| 串行 / 并行 / 混合 | `depends_on` DAG |
| 辩论 / 审查 | `debate` 工具内主持人循环（底层仍普通 DAG） |

## 二、通信：不直连

上游产物经调度器注入；被动通道 = 扇出感知 / 拓扑 / `escalate`；主动共享 = 便签墙。

**否决** Agent 直聊：成本翻倍、不可观测。

### `escalate`

worker 唯一向上通道。`blocking=false`（默认）= 报后按假设续跑；`blocking=true` = 挂起求决（默认无限期等 +「按假设继续」按钮）。经典路径直挂**用户**（否决挂 CEO——会死锁）；协调模式例外：CEO 波内存活 → 等 `resolve_escalation`。单 worker 永不走 resolve。

| kind | 语义 |
|---|---|
| `normal` | 普通上报 |
| `scope` | 职责偏离 → 波边界操舵 |
| `dep` | 缺尚不存在的输入 → `replan(add)` |

### `handoff`

收尾接力契约（非正文复述）。有下游依赖则强制；叶节点仅有增量才写。门禁不足则合成降级 debrief。

### 自主度三档

琐碎自修 → 执行层试一轮再 escalate → 方案层立刻 escalate。与用户会话 **PermissionAxes** / 权限配方正交。

Worker 工具后还有确定性 **Escalation Gate**（模型漏报兜底）：扫非语料工具输出的方案层词；`file_read` / `grep` / `code_search` / `web_search` / `read_url` 的正文当语料、不触发（真矛盾走 `escalate` 工具）。同 run 同 question 只 live 上报一次。

### 便签墙

`coordination=wall|none`（缺省 `none`）。贴事实、不要求回应；四能力：`decision` / `heads_up` / `claim` + `read_notes`；`amend_note` 改写/作废；仅推 ACTIVE。缺「还不存在」的输入走 `escalate kind=dep`，不走便签。

**否决**点对点直聊；变味信号 = 拿便签来回讨论。

## 三、冲突与文件写权

CEO 唯一裁决；置信度低才 `ask_user`。资源冲突靠 DAG。

### 交接式写权（C3）

协调会话内一本路径账本（`WriteCoordinator`）：

| 阶段 | 行为 |
|---|---|
| **派发 declare** | 无主路径由首个声明 artifact 的节点成为写主；**下游不因祖先关系在派发瞬间抢锁**（只登记计划意图）。嵌套 lead→child 显式允许派发交接。**跨波次**：新节点声明的路径若锁主已在 `completed_run_ids`，派发时自动移交（审校→修订无需用户点卡）。 |
| **写入 claim** | 真写时：本人 / 无主可写；祖先持有则可交接覆写；无关队友拒写。 |
| **完成交接** | worker 完成后，若其持有路径恰好被**唯一**未完成依赖方列入 artifacts，则自动移交。 |
| **显式移交** | `resolve_escalation(transfer_ownership=true)`；或用户写权卡「移交写权 / 保持原主」。仍在跑的锁主冲突仍直达用户。 |

写权冲突 escalate：**直达用户**（与 `browser_login` 同属用户直达例外），卡上结构化动作真正转锁——自然语言「移交」 alone 不会改账本。

→ 见代码: `workspace/write_claims.py` · `coordination/append_guard.py` · `EscalationCard`

## 四、⏳ / 否决

| 项 | 状态 |
|---|---|
| 完整 Preflight Audit | ⏳；薄预览 = 开工卡 ✅ |
| 一等 Team 实体 / A2A | ⏳（勿与现行 `delegate` 临时组队混淆） |
| 独立 Arena | **否决** |
| 树级共享 Semaphore | **否决**（父子互等死锁） |
