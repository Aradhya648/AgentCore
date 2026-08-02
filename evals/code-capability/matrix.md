# 场景 × 能力 × 验收

> Phase 1 冻结稿 · 2026-07-23 · 执行期禁止悄悄扩 scope；缺口记 Gap / 需决策。  
> **口径修订（同日 Phase 2）**：D = 引擎路径（含同构 sidecar JSON-RPC）；U = 可选 Electron UI；**S3 = 待人手 / CDP**（无 RPC「见卡」等价）。Runbook：[runbooks/s3-resume-ui.md](runbooks/s3-resume-ui.md)。详见 [README](README.md)。

## 图例

| 列 | 含义 |
|----|------|
| 层 | **A** 离线门禁 / **B** 半真（固定 prompt+试件） / **C** 全真项目 / **U** 人手 Electron UI（可选，不挡 D） |
| 路径 | **D** Desktop+sidecar **引擎**（主进程同构 JSON-RPC 算 Pass） / **S** Server API（对照） / **O** 离线命令（无 LLM turn） / **U** 仅当场景显式要求 UI 断言 |
| 工作区 | P1=`workspaces/hello-cli` · P2=`workspaces/todo-api` · P3=`workspaces/fix-me-kit` · —=不绑试件 |
| 本轮状态 | 执行结果见 [README · 本轮 Verdict](README.md)；矩阵行上的「本轮」列仅摘要 |

## 矩阵

| ID | 场景 | 层 | 路径 | 工作区 | 能力焦点（勾选须真打通） | 验收（可检查产物） | 本轮 |
|----|------|----|------|--------|--------------------------|-------------------|------|
| S1 | P1 从零搭 hello-cli | C | D | P1（近空副本） | `file_*` 写盘 · `code_execute`/`terminal` 跑命令 · 工作区画像 · （可选）`git` | 见 P1 `GOLDEN.md`：`--help`+子命令退出 0；约定文件存在；记下 `conversation_id`/`trace_id` | **Pass**（RPC） |
| S2 | P3 已知 Bug 最小修复 | B | D | P3 副本 | `file_list`/`file_read`/`grep`/`code_search` · 最小 `str_replace`/`file_write` · 跑测 | 见 P3 `GOLDEN.md`：三坑修好；`python -m pytest` 绿；禁止大重构；记 id | **Pass**（RPC） |
| S3 | 中断 / Resume | B+U | D+U | P1 或 P3（**独立会话副本**） | 挂起帧 · `resume` · AskUser/plan_review 结算 | **U 层**：人为挂起 → **刷新/重进仍见卡** → 决策后继续且**不丢**已有写盘；journal/UI 一致；记 id。`listPaused`/`resume` RPC **不**等于「仍见卡」（无 S4 `turnFilesDiff` 式等价）。人手：[runbooks/s3-resume-ui.md](runbooks/s3-resume-ui.md) | **待人手 / CDP** |
| S4 | Checkpoint + turn files diff | B | D（U 可选） | P3 独立会话 | 回合基线 · `turnFilesDiff` / 云 `files/diff` · （U）产物卡「查看改动」 | 回合改 ≥1 文件后：diff 路径与磁盘一致；有基线时可「回退到本回合开始」（可选破坏性，用副本）；记 message_id。**D 验收以 RPC/API 等价为准**；产物卡按钮属 U | **Pass**（RPC） |
| S5 | Delegate / 多 Agent 协作写码 | B/C | D | P1 独立近空副本 | `delegate` · worker `file_*`/`code_execute` · 交付契约 `files`/`code_verified`（若声明） | 出现 `run_plan`；≥1 worker 落盘；CEO 收口；黄金命令可跑；记 id；**不**与 S1 同盘互踩 | **Pass**（R2）；R1 探测 Fail **已修**（见 README） |
| S6 | Server API 对照抽检 | B | S | P3 播种到**云**工作区 | 同 S2 的 prompt 子集 · 云 `file_*`/`code_execute` | 与 S2 对照：runtime 通/不通 vs 仅桌面接缝；SSE `message_end`；产物可用 workspace files GET 核对；记 id | **Pass**（探测时 diff 500 **已修**，见 README） |
| S7 | P2 从零搭 todo-api | C | D | P2（近空副本 `todo-api-s7/`） | `file_*` 写盘 · `code_execute`/`terminal` 跑测/启服 · 工作区画像 | 见 P2 `GOLDEN.md`：`GET`/`POST /todos`；内存存储；`pytest` ≥2 且全绿；启服+探测命令可跑；记 id | **Pass**（RPC + 外部 `pytest` 7 passed） |
| A1 | 协议 fold 门禁 | A | O | — | conformance 向量 fold | 根目录 `pnpm conformance` 绿（桌面+手机） | 另报 |
| A2 | 代码工具单测门禁 | A | O | — | `file_ops` / `code_search` / `git` 等既有单测 | `apps/server`：`uv run pytest tests/test_file_ops_tools.py tests/test_code_search.py -q` | 另报 |
| A3 | preview 代码相关向量抽检 | A | O | — | `#/preview` 回放含工具/协作的既有向量 | 按 `frontend-preview.mdc`：相关 fixture 可打开、无白屏 | 另报 |

## 能力覆盖清单（跨场景）

| 能力 | 主覆盖场景 | 备注 |
|------|------------|------|
| 读仓定位（list/read/grep/code_search） | S2 | P3 故意埋可搜符号 |
| 写盘与最小 diff | S1 S2 S4 S7 | S4：D=`turnFilesDiff`；U=产物卡按钮（可选） |
| 跑命令 / 测 | S1 S2 S5 S7 | sidecar 本地盘；S6 云沙箱语义可能不同——对照记差异；S7 含启服+HTTP 探测 |
| git 子命令 | S1 可选 | 非硬门槛；普通 push 可审批确认，force / 保护分支仍拒 |
| checkpoint / Resume / AskUser | S3 S4 | S3 待人手 / CDP（U runbook）；S4 D 已通 |
| delegate 多 Agent | S5 | 简单任务也可能不组队——若未组队记 Gap；契约拒绝须标 `contract_failure`（勿烧熔断）；CEO **无**写盘为设计（已定案不加 `file_write`） |
| Desktop sidecar 路由 | S1–S5 S7 | 须绑本地根 +「本地引擎」有效开（默认开）；**同构 JSON-RPC 探针算 D** |
| Server API | S6 | 云播种默认路径；见 README「仍有效的架构备注」 |

## 成功标准（执行期统一）

- 禁止「看起来对」：每条场景交付 **产物路径断言 + 命令退出码 + conversation_id/trace_id**（S3 未人手跑通前不可 Pass）。
- **D Pass**：sidecar JSON-RPC（initialize / startTurn / respond / resume / turnFilesDiff…）与 Desktop 主进程同契约即可；**不要求** Electron 点击。
- **U**：仅当场景显式需要产品面（如 S3 刷新见卡、产物卡按钮）时另记；S3 未跑 **不**可标场景 Pass；S4 等可选 U 未跑不挡 D。
- Fail 分类：环境（key/限流/sidecar 起不来） / 模型弱 / 产品接缝 Bug / 需决策。
- 发现补丁绊线类问题：记入报告提根因，测试轮不堆特例逻辑。
