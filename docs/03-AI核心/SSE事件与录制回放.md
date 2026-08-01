---
status: blueprint
code: apps/server/agentcore/runtime/events/,apps/server/agentcore/replay/
related:
  - docs/03-AI核心/执行引擎架构设计.md
  - docs/04-前端/前端技术与架构.md
  - demos/README.md
skip_if:
  - 只改 DAG/ReAct（读执行引擎）
---

# SSE 事件与录制回放

> **权威**：SSE 事件协议、契约生成、录制/回放。前端消费 → [前端技术 §十二](/docs/04-前端/前端技术与架构.md)。

## 一、事件协议

清单 → 见代码: `runtime/events/types.py`（`EventType`）+ `packages/contract-types`。  
处置权威 → `runtime/events/disposition.py`：DURABLE 入 journal；DERIVED 走专用列；EPHEMERAL 有意不落库。

**接缝决策**：
- **`run_escalation`**：worker 调 `escalate` 瞬间即可见（DURABLE + `escalation_id`）；工具经 `on_escalate` 回调，不碰事件词表。escalate 仍非阻塞。
- **幕序列 `act`**：协作图 = 幕序列；旧 journal 无 `act` → fold 合成单幕。编排 → [辩论编排](/docs/03-AI核心/辩论编排设计.md)；渲染 → [协作图 UX](/docs/04-前端/协作图与双视图UX.md)。
- **`run_phase`**（✅）：worker mid-flight 活动相位（`thinking` / `tool` / `waiting_children` / `winding_down`）——EPHEMERAL；投影 `run.phase` / `phaseTool`。`queued`=`status:pending`，`skipped`=`status:skipped`。→ 见代码：`runtime/events/run.py:run_phase`

`finish_reason` → 见代码 `FinishReason`。

## 二、契约生成

后端 dataclass = SSE 类型唯一真相源；`pnpm gen:types` 反射生成 TS；CI `contracts` job 漂移门禁。改事件后必跑 `pnpm gen:types` **与** `pnpm conformance`。

## 三、录制与回放

**回放 = 同一 SSE 事件契约的另一种事件源**，不是另一条执行链路。业务只认事件契约；执行语义只有 runtime 一份。

| 层 | 职责 |
|---|---|
| 录制 | EventSink 纯 tap（失败不影响回合，默认关） |
| 事件文档 | 线上契约超集；录制永不带 `projected` |
| 裁切 | durable-face → 脱敏 → golden |
| 回放 | A=FOLD（不 remint）与 B=SINK（可 remint）互斥 |

**红线**：回放/演示不得侵入 runtime 语义（禁 `if is_demo_tape` 改语义）。有副作用的客户端工具导出期硬剪。操作 → [`demos/README.md`](/demos/README.md)。

**边界**：不做全站 event sourcing；与生产 attach/重连（`Last-Event-ID`）正交不合并。有副作用服务端工具短路回放 ⏳ 不实施。
