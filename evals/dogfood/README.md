# Dogfood 决策闭环 · 金标资产

> **状态**：金标槽位与结构校验已落地（N=20）；维护者从 logs 回填标注仍 ⏳。  
> **用途**：内部决策 / 回归观察——**不进 PR 硬门、不挂强制 nightly**。  
> **正交**：与 `apps/server/agentcore/evals/cases/gold/labels.json`（裁判 kappa 校准）**分列**；勿混名、勿改校准 loader。

## 定案摘要（E1–E4）

| 代号 | 定案 |
|------|------|
| **E1** | Dogfood gold-set 闭环。不做再建 R 真仓；不把 S3 当主线。 |
| **E2** | 仅内部决策 / 回归观察；不进 PR 硬门；不挂强制 nightly。 |
| **E3** | 窄维度 = **routing** + **deliverable 过硬** + **citation**（不适用标 `N/A`）。 |
| **E4** | 维护者 dogfood 日志为主 + 少量合成补洞；诚实声明证据等级。 |

槽位：**恰好 20**。可含 `synthetic_fill`（示范分）+ `pending_label`（拟从 logs 补）。无真实样本时 `conversation_id` / `trace_id` 显式 `null`，**禁止编造生产 ID**。

## 证据三档（能支撑什么）

| 档 | 来源 | 能支撑 | 不能冒充 |
|----|------|--------|----------|
| **L1 合成** | 本目录 `synthetic_fill` 手写场景 + 示范分 | 维度/分制示范、lint 与流程自检、讨论时的形状对照 | 产品真实质量结论、发布门禁、kappa 校准 |
| **R 真仓** | [`evals/code-capability/`](../code-capability/README.md) pinned 开源仓雷达 | 代码能力内部评测（Find/Fix/Extend 等） | 本 dogfood 闭环的主证据（本目录不扩建 R） |
| **Dogfood 金标** | 维护者 `logs/dev.jsonl` ⋈ Postgres，经本 manifest 标注 | 编排 / 交付 / 引用闸前的回归观察与决策对照 | PR/CI 硬门；对外「用户数据证明」 |

优化质量前须声明当前证据档；合成 ≠ 真实用户数据。

## 标注维度与分制

三维彼此独立。不适用写字符串 `"N/A"`；适用写整数：

| 维度 | 含义 | 分制 |
|------|------|------|
| `routing` | 该直答 vs 该委派；是否过派 / 跨域乱派 | `0` 错 · `1` 可辩/部分 · `2` 对 · 或 `"N/A"` |
| `deliverable` | 交付是否过硬（缺文件、空壳、验收缺口等） | 同上 |
| `citation` | 成篇引用是否站得住（弱引、无台账、该引未引等） | 同上 |

- `synthetic_fill`：必须带齐三维（分或 `N/A`）；`evidence_tier` = `L1_synthetic`；id 一般为 `null`。
- `pending_label`：待补时三维均为 `null`，用 `intended_coverage` 写拟覆盖场景；从 logs 回填后写入真实 id、`evidence_tier=dogfood`，并填齐三维（`kind` 仍为 `pending_label`）。

## 短流程：取样 → 标注 → 对照

1. **取样**：按 [对话日志分析指南](/docs/05-平台与运维/对话日志分析指南.md) / `conversation-logs.mdc`，用 `log_timeline` 从维护者 dogfood 日志挑候选（误派、弱交付、弱引用等）。
2. **入槽**：选一条 `pending_label` → 写入真实 `conversation_id` / `trace_id` → `evidence_tier=dogfood` → 按三维打分。
3. **对照**：改编排 / 引用闸 / 交付验收前，抽相关槽位做前后观察；**不**接入 CI。

## 门禁纪律

- ❌ 不进 `pnpm release:gate` / PR required checks  
- ❌ 不挂强制 GitHub nightly  
- ✅ 本地自愿跑下方 lint / pytest  
- ✅ 与 kappa gold-set、MAST、code-capability R 套件路径与命名均隔离  

## 目录与跑测

| 路径 | 说明 |
|------|------|
| [`manifest.json`](manifest.json) | 元数据 + 恰好 20 条槽位 |
| [`lint_manifest.py`](lint_manifest.py) | 零 LLM 结构校验（缺字段 / 重复 id / ≠20 → exit ≠0） |
| [`test_manifest_lint.py`](test_manifest_lint.py) | pytest 包装同一校验 |

```bash
# 仓库根
python evals/dogfood/lint_manifest.py

# 或
python -m pytest evals/dogfood/test_manifest_lint.py -q
```

## 非目标

再建 R 真仓、S3 Resume UI 主线、裁判 kappa 校准、对外基准宣传、自动打分 LLM。
