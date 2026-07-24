# AI 代码能力全面测试

> **状态**：Phase 1 准备包已冻结；**Phase 2 真跑（2026-07-23）已汇总**。  
> **读本页即可**：本轮 verdict · 定案口径 · S1–S7 结论 · Gap 状态。  
> **规划索引**：[docs/06-规划/README.md](../../docs/06-规划/README.md)「AI 代码能力全面测试」。

## 本轮 Verdict（2026-07-23）

**D·引擎路径主验收通过**（S1 / S2 / S4 / S5·R2 / S6 / **S7** 均 Pass）。  
**S3 Resume UI 仍待人手 / CDP**（无 S4 式 RPC 等价；勿编造 Pass）。  
**S7 P2 todo-api**：**Pass**（sidecar 真跑 + 外部 GOLDEN：`pytest` 7 passed；stdlib `http.server`；`GET`/`POST /todos`）。  
**B 环境债冒烟**：**Pass**（环境债目标点）：配额解除后 CEO 调 `code_execute` → `not_assembled` → 改 `delegate`；盘上 `fix-me-kit-smoke-b` `pytest` 3 passed（早期 4×`LLM_RATE_LIMIT` 为配额债，已过时）。  
人手步骤见 [`runbooks/s3-resume-ui.md`](runbooks/s3-resume-ui.md)。  
本轮探测到的产品接缝均已收口：S5 R1（delegate 契约拒绝误烧熔断）**已修**；云 `files/diff` 500 **已修**；环境债报错/无 bash **已修**（单测 + B 真跑）。仍开放：**S3 待人手（U）**。

| ID | 场景 | D·引擎 | 备注 |
|----|------|--------|------|
| S1 | P1 从零搭 hello-cli | **Pass** | GOLDEN 全绿；sidecar RPC |
| S2 | P3 最小修 Bug | **Pass** | pytest 3→0 fail；sidecar RPC |
| S3 | 中断 / Resume | **待人手 / CDP** | 「刷新仍见卡」无 RPC 等价；runbook 已备 |
| S4 | Checkpoint + turnFilesDiff | **Pass** | diff↔盘一致 + restore 绿；RPC 等价 |
| S5 | Delegate 多 Agent | **Pass**（R2） | R1 曾 Fail（已修，见下）；R2 有 `run_plan` + GOLDEN |
| S6 | Server API 对照 | **Pass** | 云写码闭环；探测时 `files/diff` 500 **已修** |
| S7 | P2 从零搭 todo-api | **Pass** | 独占 `todo-api-s7/`；stdlib HTTP；外部 `pytest` 7 passed |
| B | 环境债 sidecar 冒烟 | **Pass**（目标点） | CEO `code_execute`→`not_assembled`→`delegate`；盘上 pytest 3 passed；`fix-me-kit-smoke-b/` |

## 本轮定案口径（勿再请示）

1. **sidecar JSON-RPC（与 Desktop 主进程同构）算「D·引擎路径」Pass**。人手点 Electron UI 单列为可选 **U 层**，**不挡**本轮 D 验收。
2. **S3**：「刷新/重进仍见卡」属 **U**；`listPaused`/`resume` 只证帧落盘+续跑，**不**完成本场景（无 `turnFilesDiff` 式按钮数据 RPC）。解禁 = 人手按 runbook 跑通或产品决策扩 CDP。矩阵标 **待人手 / CDP**，禁止探针冒充 Pass。
3. 其余场景证据链到既有 probes 即可（见下表路径）；不要求本页重贴全量事件。

## S1–S7 证据与结论

| ID | Verdict | 工作区 | conversation_id / trace_id | 探针 |
|----|---------|--------|----------------------------|------|
| S1 | Pass | `workspaces/hello-cli-s1/` | `3f1987ed-…` / `a76f753601e34fbc93e8bd1f2d9dec3d` | [`logs/probes/code_cap_s1_20260723.json`](../../logs/probes/code_cap_s1_20260723.json) |
| S2 | Pass | `workspaces/fix-me-kit-s2/` | `1358e023-…` / `511d6f4db643455990de6644b6788bed` | [`logs/probes/probe_sidecar_1784797063.json`](../../logs/probes/probe_sidecar_1784797063.json) |
| S3 | **待人手 / CDP** | `workspaces/fix-me-kit-s3/`（试件已备） | —（未发 turn） | 人手：[`runbooks/s3-resume-ui.md`](runbooks/s3-resume-ui.md)；回填 id 后方可 Pass（U） |
| S4 | Pass | `workspaces/fix-me-kit-s4/` | `575eb0b2-…` / `0ecb7abf998a4385bcda487e9fcf3c4b` | [`logs/probes/s4_checkpoint_diff_20260723_165108.json`](../../logs/probes/s4_checkpoint_diff_20260723_165108.json) |
| S5 R1 | Fail（探测）→ **已修** | `workspaces/hello-cli-s5/` | `32838baf-…` / `3d25e573b1664ac2a40e9ec2bddf968f` | [`logs/probes/s5_delegate_20260723_165900.json`](../../logs/probes/s5_delegate_20260723_165900.json) |
| S5 R2 | Pass | 同上（重跑） | `c7cc15f0-…` / `91df59383e1a41c193a893f7a05936de` | [`logs/probes/s5_delegate_r2_20260723_170127.json`](../../logs/probes/s5_delegate_r2_20260723_170127.json) |
| S6 | Pass | 云工作区（P3 播种） | `ebce442a-…` / `99737dc9ade84de98e96116fddf1efd3` | [`logs/probes/probe_20260723-165223.json`](../../logs/probes/probe_20260723-165223.json) |
| S7 | **Pass** | `workspaces/todo-api-s7/` | `a1c0d738-…` / `7fc406c549b94c5fbf42d308a0f3396b` | [`logs/probes/probe_sidecar_1784808590.json`](../../logs/probes/probe_sidecar_1784808590.json)；外部验收 `python -m pytest -q` → **7 passed**；栈 stdlib `http.server`；入口 `python -m todo_api`；`GET`/`POST /todos`（进程内/替用端口探测 OK；本机默认 `:8765` 曾 `WinError 10013`） |

### 关键 Gap / 收口

| Gap | 来源 | 性质 | 状态 |
|-----|------|------|------|
| `delegate` 契约拒绝（playbook⊕tasks / 须 hoist `completion_criteria` 等）未标 `contract_failure` → 连拒烧穿熔断；熔断后 CEO 无写盘（**设计如此**） | S5 R1 | 校验归因 + 提示 | **已修**：契约拒绝标 `contract_failure` + 更清晰报错 + schema/CEO 提示防踩坑；**已定案不给 CEO 加 `file_write`**。R2 组队 + GOLDEN Pass |
| `GET …/messages/{mid}/files/diff` → 500（`conv` 为 None → `folder_id`） | S6 | 云 diff 接缝 Bug | **已修**：`turn_files_diff.py` 误用 `_require_owned_conversation`（无返回）→ 改为 `_get_owned_conversation`；`test_turn_files_diff` 10 passed |
| S3 刷新/重进仍见挂起卡 | S3 | U 层 | **待人手 / CDP**（无 RPC 等价；见 runbook） |
| U 层产物卡按钮未点 | S4 等 | 可选 U | 不挡 D；RPC `turnFilesDiff` / `restoreTurnBaseline` 已通 |
| 环境摩擦（`code_execute` WSL、`test_run` framework） | S1/S2/S5/S6 | 环境噪音 | **部分已清**：① CEO/未装配面误调执行类工具 → 可操作报错 + `policy_failure`（不烧熔断）；② 本机无 bash 时 `code_execute` 启动前失败并提示改用 python/js。`test_run` 在近空仓 `framework=unknown` 仍属试件早期噪音；S1 探针 900s 超时视为空转后果，随①②减轻。**不**给 CEO 加执行/写盘工具（定案不变） |

## 交付物（Phase 1 + 本轮）

| 路径 | 内容 |
|------|------|
| [`matrix.md`](matrix.md) | 场景 × 能力 × 验收；含 **D / U** 口径与 S3 待人手 |
| [`turn-recipe.md`](turn-recipe.md) | Desktop sidecar / Server API 调用配方（已同步 D=RPC 同构） |
| [`parallel-briefs.md`](parallel-briefs.md) | S1–S7 brief（S3 待人手 / CDP；S7 已 Pass） |
| [`runbooks/s3-resume-ui.md`](runbooks/s3-resume-ui.md) | **S3 U 层人手步骤**（绑盘 · 见卡 · 刷新 · 回填 id） |
| [`workspaces/hello-cli/`](workspaces/hello-cli/) | **P1** 主试件模板 |
| [`workspaces/todo-api/`](workspaces/todo-api/) | **P2** 近空模板（S7 真跑副本 `todo-api-s7/`） |
| [`workspaces/fix-me-kit/`](workspaces/fix-me-kit/) | **P3** 并行专用模板 |
| `workspaces/*-s{1..5,7}/` | 本轮独占副本（真跑落盘；含 `todo-api-s7/`） |
| `workspaces/fix-me-kit-smoke-b/` | B 环境债冒烟副本（CEO 诱使误调执行工具） |

**P2 `todo-api`**：S7 加码真跑 + 外部 GOLDEN **Pass**。

## 非目标（写死）

计费/账本精度、多租户、Mobile、Admin、Unity 小镇、无边界大项目、压测。

## 仍有效的架构备注（非本轮新决策）

1. **Server API「真本地盘」对照**：`PUT …/workspace/binding` 的 `root_id` 须为桌面 `addRoot` 铸造的句柄；纯 curl **无法**单独铸造本机根。对照抽检默认走 **云工作区 + `PUT …/workspace/files/{path}` 播种试件**（S6 已按此跑通），或人手在 Desktop 绑根后只把 `conversation_id` 交给 API 探针。
