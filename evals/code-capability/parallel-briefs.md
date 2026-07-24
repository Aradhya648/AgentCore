# 场景并行 brief（下一回合可直接派工）

> 主 Agent 派 ≤6 子代理时：一人一路；**文件/会话互不交叉**；本 brief 已含边界。执行前各复制工作区（若标注「须副本」）。  
> S1–S6 为本轮主矩阵；**S7** 为 P2 加码（**已 Pass**）。**S3 仍待人手 / CDP**。

---

## S1 · P1 从零搭 hello-cli（C · Desktop）

| 项 | 内容 |
|----|------|
| 工作区 | `evals/code-capability/workspaces/hello-cli`（建议先复制为 `hello-cli-s1/` 再绑） |
| 路径 | Desktop + sidecar（**D**=同构 JSON-RPC 即可；产物卡按钮为可选 **U**） |
| Prompt | 该目录 `PROMPT.md` |
| 验收 | 同目录 `GOLDEN.md` 全部勾选；交 `conversation_id`/`trace_id` |
| **边界** | **独占** hello-cli 盘；不碰 fix-me-kit / todo-api；不做 Resume/diff 专测；不改 `apps/**` |

---

## S2 · P3 已知 Bug 最小修复（B · Desktop）

| 项 | 内容 |
|----|------|
| 工作区 | `evals/code-capability/workspaces/fix-me-kit`（复制为 `fix-me-kit-s2/`） |
| 路径 | Desktop + sidecar（**D**=同构 JSON-RPC 即可；产物卡按钮为可选 **U**） |
| Prompt | 该目录 `PROMPT.md` |
| 验收 | `GOLDEN.md`：三坑修复 + pytest 绿；禁止借机重构无关文件 |
| **边界** | **独占**该副本；不跑 S4 的「回退基线」破坏盘；不测 API |

---

## S3 · 中断 / Resume（B · Desktop + **U**）· **待人手 / CDP**

| 项 | 内容 |
|----|------|
| 工作区 | 复制 `fix-me-kit` → `fix-me-kit-s3/`（试件已备） |
| 路径 | D 引擎 + **U**（刷新/重进见卡）；`listPaused`/`resume` **不够**完成本场景 |
| Prompt | 要求 Agent **先** `ask_user` 确认修复范围再改文件（或人在 plan_review/审批卡上停住） |
| 验收 | 挂起可见 → 刷新/重开对话仍可续 → 决策后继续且先前约定不丢；记 message_id |
| **边界** | 不与 S2/S4 共用目录；不验收 diff UI；不做多 Agent 强派 |
| **本轮** | **待人手 / CDP**——步骤：[runbooks/s3-resume-ui.md](runbooks/s3-resume-ui.md)；解禁见 [README](README.md) |

---

## S4 · Checkpoint + turn files diff（B · Desktop）

| 项 | 内容 |
|----|------|
| 工作区 | 复制 `fix-me-kit` → `fix-me-kit-s4/` |
| 路径 | Desktop + sidecar（**D**=同构 JSON-RPC 即可；产物卡按钮为可选 **U**） |
| Prompt | 同 S2 子集即可（至少改 1 个源文件） |
| 验收 | 回合结束后产物卡「查看改动」与磁盘一致；可选点一次「回退到本回合开始」再确认文件回到基线（仅在本副本） |
| **边界** | **独占** s4 副本；不测 Resume 全流程；不测 Server API |

---

## S5 · Delegate / 多 Agent 写码（B/C · Desktop）

| 项 | 内容 |
|----|------|
| 工作区 | 复制 `hello-cli` → `hello-cli-s5/`（保持近空） |
| 路径 | Desktop + sidecar（**D**=同构 JSON-RPC 即可；产物卡按钮为可选 **U**） |
| Prompt | 明确要求「组团队完成：一人写 CLI 实现、一人写测试并跑通」（允许产品未组队——若未出现 `run_plan` 记 Gap，仍验收最终 GOLDEN） |
| 验收 | 尽量出现协作图/`run_plan`；最终满足 P1 `GOLDEN.md`；交 id |
| **边界** | **独占** s5 盘；不与 S1 同目录；不做 Mobile |

---

## S6 · Server API 对照抽检（B · API）

| 项 | 内容 |
|----|------|
| 工作区 | **云**：新建会话后把 `fix-me-kit` 源文件 `PUT` 进 `conv:{id}` 工作区（见 `turn-recipe.md` §1.3）；或使用 Desktop 已绑定会话的 id 只发 API 消息（须在 brief 写明哪种） |
| 路径 | Server API（`probe_turn.py` 或等价 curl+SSE） |
| Prompt | 与 S2 `PROMPT.md` 同文（便于对照） |
| 验收 | SSE 正常收尾；云侧文件/测试结果可核对；写明与 S2 差异（runtime vs 桌面接缝） |
| **边界** | **不**操作 Desktop UI；**不**写本机 P3 原目录；不扩到计费断言 |

---

## S7 · P2 从零搭 todo-api（C · Desktop）· 加码 · **Pass**

| 项 | 内容 |
|----|------|
| 工作区 | `evals/code-capability/workspaces/todo-api-s7/`（模板：`todo-api/`） |
| 路径 | Desktop + sidecar（**D**=同构 JSON-RPC 即可；产物卡按钮为可选 **U**） |
| Prompt | 该目录 `PROMPT.md` |
| 验收 | 同目录 `GOLDEN.md`：`GET`/`POST /todos` · 内存存储 · `pytest` ≥2 全绿 · 启服+PowerShell 探测；交 `conversation_id`/`trace_id` |
| **边界** | **独占** `todo-api-s7/`；不碰 hello-cli / fix-me-kit；不做 Resume/diff/delegate 专测；不改 `apps/**` |
| **本轮** | **Pass**：`a1c0d738-…` / `7fc406c549b94c5fbf42d308a0f3396b`；探针 `probe_sidecar_1784808590.json`；外部 `pytest` **7 passed**（stdlib） |

---

## 建议派工顺序（主统筹）

1. 先起 **A1/A2** 可由主 Agent 或第 7 槽串行跑（不占 6 路真跑额度时：6 路满员则 A 层主 Agent 自跑或下一波）。
2. 并行真跑优先：**S1 S2 S5 S6**（写码主信号）+ **S4**（checkpoint/diff）；**S3 待人手 / CDP**（U runbook）；**S7** 加码已 **Pass**（勿重跑除非回归）。
3. 全部回报后主 Agent 统一汇总 Pass/Fail/Gap/需决策——**禁止**子代理嵌套再派 Task。
4. **D 口径**：sidecar 同构 JSON-RPC 算引擎 Pass；Electron 点击为可选 U（见 [README](README.md) / [matrix](matrix.md)）。
