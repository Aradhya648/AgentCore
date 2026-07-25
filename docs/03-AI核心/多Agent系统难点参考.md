---
status: reference
code: apps/server/agentcore/evals/mast.py
related:
  - docs/03-AI核心/Agent协作模式.md
  - docs/03-AI核心/编排器与CEO主Agent.md
  - docs/03-AI核心/辩论编排设计.md
  - docs/05-平台与运维/管理员后台.md
  - docs/01-产品/产品路线图摘要.md
skip_if:
  - 只改 AgentCore 内部编排实现（读 03-AI 区对应文档）
---

# 多 Agent 系统难点参考

> **用途**：行业通用的 LLM 多 Agent 系统（LLM-MAS）难点综述，供产品/架构/评测讨论时查阅。
> **范围**：外部研究与业界共识；AgentCore 落地映射见 [§八](#八agentcore-交叉指针)。
> **数据来源**：MAST（Cemri et al. 2025）、任务复杂度理论（Tang et al. 2025）、错误级联与集体幻觉系列论文、多家工程实践总结；截至 2026-06。

---

## 一、核心结论

**多 Agent 不是默认升级。** 在不少 benchmark 与生产对照中，同等模型下单 Agent 反而更快、更便宜、更稳；SOTA 开源 MAS 框架的正确率可低至 25–33%。

| 现象 | 含义 |
|------|------|
| 协调税 | 多轮 Agent 交互消耗 context，留给任务的容量变少 |
| 失败较均衡 | 规格 ~42% / 错位 ~37% / 验证 ~21%（MAST 实测分布） |
| 根因多在系统 | 架构与编排问题常多于「基座模型不够强」 |

**行业设计原则**：默认单 Agent；仅当任务** genuinely** 需要分解、角色专精或显式交叉核验时，才付多 Agent 的协调税。

> **AgentCore 产品立场（与上行业口径刻意相反）**：协作是本产品的第一性（「真正的 Agent 团队协作」即卖点），故路由采用**该派就派、按活的自然缝拆人**（见 [编排器 §协调者工具边界·团队形态判据](/docs/03-AI核心/编排器与CEO主Agent.md)）——不是否认协调税，而是把它当**被度量的成本**（team gate / 协作质量评测）而非预先回避的理由；跨域合成流水线少派，避免按工种堆人。本文的价值在于枚举「组队之后会怎么失败」，供护栏与评测设计对照。

---

## 二、MAST 失败分类（14 类 · 三大组）

[MAST](https://sky.cs.berkeley.edu/project/mast/)（Multi-Agent System Failure Taxonomy）基于 7 个开源框架、200+ 执行轨迹归纳，是目前引用最广的失败 taxonomy。AgentCore 离线评测直接采用其 14 类作为失败标签 → 见 [`evals/mast.py`](/apps/server/agentcore/evals/mast.py)。

### FC1 · 规格不达（~41.8%）

| 码 | 英文 | 中文 |
|----|------|------|
| 1.1 | Disobey task specification | 不遵守任务规格 |
| 1.2 | Disobey role specification | 不遵守角色规格 |
| 1.3 | Step repetition | 步骤重复 |
| 1.4 | Loss of conversation history | 丢失对话历史 |
| 1.5 | Unaware of termination conditions | 不认终止条件 |

**典型根因**：任务/角色/终止条件写在 prompt 里但架构未 enforce；长链路 context rot 导致历史丢失。

### FC2 · 互相错位（~36.9%）

| 码 | 英文 | 中文 |
|----|------|------|
| 2.1 | Conversation reset | 对话被重置 |
| 2.2 | Fail to ask for clarification | 该问不问 |
| 2.3 | Task derailment | 任务跑偏 |
| 2.4 | Information withholding | 信息藏着不说 |
| 2.5 | Ignored other agent's input | 无视他人产出 |
| 2.6 | Reasoning-action mismatch | 想得对做得错 |

**注**：2.6 为 FC2 最大单项（~13.2%）——上下文里约束已给出，产出仍不遵守。

### FC3 · 验证缺位（~21.3%）

| 码 | 英文 | 中文 |
|----|------|------|
| 3.1 | Premature termination | 过早终止 |
| 3.2 | No or incomplete verification | 验证缺失/不全 |
| 3.3 | Incorrect verification | 验证做错 |

**执行阶段映射**：Pre-Execution（规格）→ Execution（错位）→ Post-Execution（验证）。论文提供 LLM-as-Judge 自动标注流水线（与人标注 Kappa ≈ 0.77）。

**开源资源**：[论文](https://arxiv.org/html/2503.13657v1) · [MAST 官网](https://sites.google.com/berkeley.edu/mast) · [数据集](https://github.com/multi-agent-systems-failure-taxonomy/MASFT)

---

## 三、按维度展开的难点

### 3.1 协作与编排

- **任务分解**：拆太细 → 通信爆炸；拆太粗 → 多 Agent 无意义。
- **状态与依赖**：Agent 基于过期状态行动；每跳 context 衰减（context rot）。
- **终止模糊**：该停不停（1.3、1.5）或该继续就停（3.1）。
- **拓扑敏感**：消息依赖图形状决定错误放大风险（见 §四）。
- **扩展悖论**：Agent 数量 ↑ ≠ 性能 ↑；通信、记忆、负载均衡成瓶颈。

**缓解方向**：显式编排（DAG / 状态机）、检查点、按失败影响分区（isolation zones）。

### 3.2 一致性与冲突

- 各 Agent 对同一任务理解漂移（2.3、2.5）。
- 重复劳动或互相推翻已收敛结论。
- 协议违规：对话重置（2.1）、该共享的信息藏着不说（2.4）。
- 子任务强依赖时，误差传播代价近似 O(K²)（MARL sample complexity 分析）。

### 3.3 可靠性与幻觉

- **错误级联**：小错在依赖链上被当作可信输入，逐级放大。
- **共识惯性**：多个 Agent 独立采纳同一上游错误，形成「假互相印证」。
- **集体幻觉**：unsupported claim 在 Agent 网络里递归扩散、强化。
- **语义级失败**：schema 校验通过但逻辑错误，下游无法察觉。

**缓解方向**：Execute / Validate / Critic 角色分离；handoff 语义验证（不只验 schema）；claim 溯源图（genealogy / provenance）；红队与外部核验 Agent。

### 3.4 成本与延迟

- 每多一轮交互 = 额外 prompt + 历史 replay + 可能的重复 tool call。
- 协调占 context → token 与延迟双升；Best-of-N 采样有时 beating 复杂 MAS。
- 简单、边界清晰、顺序任务 → 单 Agent 通常更优。

### 3.5 用户体验与人审

- **静默失败**：无 exception，输出 plausible but wrong。
- **Prompt 级 HITL 不可靠**：「请先询问用户」可被 injection / 幻觉绕过 → 须架构级闸门（interrupt / checkpoint）。
- 长链路需可见进度、可干预、可取消；人审 UI 需「意图 + 权限 + 依据」，非 raw log。

**HITL 模式**：执行前批准 · 置信度阈值升级 · 渐进放权 · 执行后审计抽样。

### 3.6 评测与回归

- 须控制任务复杂度：**depth**（推理链长度）与 **width**（能力广度）；否则 MAS vs SAS 对比无意义。
- depth 增益更显著，width 会饱和（Tang et al. 2025）。
- 端到端通过率不够 → 须按 MAST 类/组聚合；须 execution trace 而不只终稿。
- **系统健康 ≠ 输出质量**：latency / error rate 与 correctness / faithfulness 分开 pipeline。

---

## 四、错误传播（级联 · 共识惯性）

[From Spark to Fire](https://arxiv.org/html/2603.04474) 将协作抽象为有向依赖图，归纳三类脆弱性：

| 类 | 含义 |
|----|------|
| Cascade amplification | 单点误差沿依赖链放大 |
| Topological sensitivity | 图拓扑决定放大程度 |
| Consensus inertia | 独立重复采纳同一错误 → 假共识 |

**治理思路**：message 层溯源图插件，在不改协作拓扑的前提下抑制放大（论文报告 defense success 0.32 → 0.89）。

相关：[Hallucination Cascade](https://arxiv.org/html/2606.07937) · [Collective Hallucination](https://arxiv.org/html/2606.07941) · [CHARM（Agentic RAG 级联）](https://arxiv.org/html/2606.04435v1)

---

## 五、何时多 Agent 值得

[Tang et al. 2025](https://arxiv.org/html/2510.04311) 用 depth × width 刻画任务复杂度：

- MAS 相对 SAS 的收益随 **depth 与 width 均增**，**depth 效应更强**。
- width 增益会饱和；depth 增益理论上可持续增长。
- 子任务**相对独立**时 MARL 样本效率更好；强依赖则协调税压倒收益。

| 倾向单 Agent | 倾向多 Agent |
|--------------|--------------|
| 边界清晰、顺序、自包含 | 需自然分解、并行、专精角色 |
| 无显式 cross-check 需求 | 需对抗 / 红队 / 独立核验 |
| 成本/延迟敏感 | depth / width 均高且值得付协调税 |

**反面实证**：6 类异质任务上，单 Agent 在质量、成本、延迟全面优于固定多 Agent pipeline（2026 empirical comparison）。

---

## 六、全场景速查

| 场景 | 主要难点 | 常见 MAST 码 |
|------|----------|--------------|
| 层级委派（Orchestrator → Specialist） | 规格传递丢失、worker 跑偏、CEO 过早收口 | 1.1/1.2, 2.3, 3.1 |
| 辩论 / 对抗 | 假对抗、共识惯性、轮次空转 | 2.5, 2.6, 1.3 |
| 红队 / 核验 | 验证做错、对抗不够真 | 3.2/3.3 |
| 并行 Swarm | 状态一致、重复劳动 | 2.4/2.5, 1.4 |
| Agentic RAG 多阶段 | 早期幻觉级联到终稿 | 级联类 / 3.2 |
| 工具链 Handoff | 工具结果误读、静默 substitution | 2.6, 3.2 |
| 长期 / 多会话 | 记忆漂移 | 1.4 |
| 人审闸门 | Prompt 级 HITL 被绕过 | 2.2 |

---

## 七、业界缓解模式（跨场景）

1. **默认单 Agent**，多 Agent 需证明任务值得（分解 / 专精 / 核验三选一以上）。
2. **规格先行**：角色、终止条件、交付物写进架构，不只靠 prompt。
3. **Handoff 验语义**：每跳 content validation，不只 schema。
4. **溯源与 genealogy**：追踪 claim 来源，防假共识。
5. **Trace-first 可观测**：span 树（root → agent → LLM → tool）；跨 Agent 传播 trace context。
6. **架构级 HITL**：interrupt / checkpoint，不依赖「请询问用户」。
7. **按 MAST 类评测**：14 类分别压测，非只看 end-to-end pass rate。
8. **Benchmark 标注 depth/width**，否则 MAS vs SAS 对比无效。

---

## 八、AgentCore 交叉指针

| 主题 | 去哪读 |
|------|--------|
| 协作哲学、`escalate`、通信 | [Agent 协作模式](/docs/03-AI核心/Agent协作模式.md) |
| CEO 委派、检查点 | [编排器与 CEO 主 Agent](/docs/03-AI核心/编排器与CEO主Agent.md) |
| 辩论编排 | [辩论编排设计](/docs/03-AI核心/辩论编排设计.md) |
| MAST 14 类失败标签常量 | [`evals/mast.py`](/apps/server/agentcore/evals/mast.py) |
| 协作质量 · MAST 度量（在线看板 + 真数闸门） | [管理员后台 §四](/docs/05-平台与运维/管理员后台.md) + 远期规划 §2.4（详细提案不在公开仓 / 维护者本地） |
| 协作机制（便签墙 / lead / playbook / 验证两道） | [Agent 协作模式](/docs/03-AI核心/Agent协作模式.md) + [编排器与 CEO 主 Agent](/docs/03-AI核心/编排器与CEO主Agent.md) |

---

## 九、延伸阅读

| 资源 | 价值 |
|------|------|
| [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/html/2503.13657v1) | MAST taxonomy + 数据集 |
| [Task Complexity & MAS Effectiveness](https://arxiv.org/html/2510.04311) | depth/width · 何时 MAS 更值 |
| [Error Cascades in LLM-MAS](https://arxiv.org/html/2603.04474) | 级联 · 共识惯性 · 治理层 |
| [Collective Hallucination](https://arxiv.org/html/2606.07941) | 网络中的幻觉扩散 |
| [CHARM (Agentic RAG)](https://arxiv.org/html/2606.04435v1) | 阶段间一致性追踪 |
