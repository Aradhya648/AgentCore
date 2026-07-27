---
status: landed
code: apps/town/
related:
  - docs/02-架构/项目结构.md
  - docs/03-AI核心/运行时总览.md
  - docs/01-产品/产品路线图摘要.md
---

# AgentTown 客户端

> Unity 3D 模拟观测客户端。打开/构建/测试 → `apps/town/README.md`。后端 → [运行时总览 · AI 小镇](/docs/03-AI核心/运行时总览.md#ai-小镇模拟)。

## 产品边界

| 维度 | 定案 |
|---|---|
| 引擎 | Unity 6 LTS + URP |
| 角色 | 观看 / 控制 / 回放；不含 LLM、不推算世界 |
| 后端 | 共用账号 + `simulation/` |
| Desktop | 只写 session 并启动，**不内嵌** 3D |
| 入口 | Windows 独立应用；WebGL 作传播演进 |
| ⏳ | 恋综节目模式服务端接入（详细提案不在公开仓 / 维护者本地） |

## 不变量

1. 后端 `sim_tick` 快照 = 世界真相。
2. 客户端只消费契约；单一状态机 `SimulationSession`。
3. Live / Replay / Offline 共用 `ApplySnapshot`。
4. Live：`tick_ended` 后读快照；**忽略** `tick_frame` 更新世界（防双写）。
5. Replay：仅 `GET /ticks/{n}`；不并行 replay SSE。
6. 坐标转换只一次：`unity = (wire.x, wire.y, -wire.z)`；区域以 conformance fixture 为准。
7. 视觉 spawn offset 不回写后端。

## 模式

| 模式 | 位置更新 |
|---|---|
| Live | `tick_ended` → 读快照 |
| Replay | 只读 playhead 快照 |
| Offline Demo | 本地故事包帧，仍走 ApplySnapshot |

## 契约要点

基址 `/v1/simulation`（路径以 OpenAPI 为准）。居民：manifest=身份；tick=运行时；本地 persona 仅补展示文案。DTO 向前兼容；事件名/必填/坐标变必须同步契约+fixture，禁静默兜底。

## 启动与分发

CLI 或 `%APPDATA%/AgentCore/session.json`；缺可执行文件须明确提示。WebGL 不读本机 session；正式传播的 token 边界未定稿。本地 run 历史只是入口缓存。

## 真相源

| 内容 | 权威 |
|---|---|
| 模拟行为 | `apps/server/agentcore/simulation/` |
| REST / SSE | OpenAPI · `packages/contract-types` |
| 区域坐标 | `packages/protocol-conformance/fixtures/` |
| 故事包 / 资产 / 构建 | `town-story-packs` · `TownAssets` · `apps/town/README.md` |

## 否决

Desktop 内嵌 R3F（双栈漂移）；Unreal（过重且碍 WebGL）；Live 多权威源并写；过早抽象通用模拟客户端。

Unity 唯一 3D 栈。未经验证前，不把 Offline 演示表述为真实涌现质量。
