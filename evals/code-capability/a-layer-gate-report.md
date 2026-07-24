# A 层离线门禁报告

> **跑次**：2026-07-23 · 本机 Windows  
> **定案**：matrix A1 / A2（及矩阵点名的 git 工具单测）；A3 preview 抽检不在本轮自动化范围  
> **结论总览**：**FAIL**（整锅 `pnpm conformance` 红；根因属**门禁/产品接缝**，非环境）

## 摘要

| ID | 门禁 | 命令 | 退出码 | 结果 |
|----|------|------|--------|------|
| A1 | 协议 fold + 跨端 parity | 根目录 `pnpm conformance` | **1** | **FAIL** |
| A1′ | 桌面向量（拆跑确认） | `pnpm --filter agentcore-desktop run conformance` | 0 | PASS（110/110） |
| A2 | 代码工具单测 | `cd apps/server && uv run pytest tests/test_file_ops_tools.py tests/test_code_search.py -q` | 0 | **PASS**（54） |
| A2′ | git 工具单测（矩阵点名） | `cd apps/server && uv run pytest tests/test_git_ops_tool.py -q` | 0 | **PASS**（37） |
| A3 | preview 向量抽检 | 人工 `#/preview`（见 `frontend-preview.mdc`） | — | **未跑**（非本轮自动化） |

**整层判定：FAIL** —— A1 未过即整层不过；A2/A2′ 绿。

## 失败用例列表

### A1 · `pnpm conformance`（exit 1）

| 端 | 阶段 | 结果 |
|----|------|------|
| mobile | vectors | PASS 110/110 |
| mobile | parity | **FAIL · 1 problem** |
| desktop | （同跑时被 `ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL` 打断输出；拆跑见上） | 拆跑 PASS 110/110 |

**唯一失败项：**

```
✗ [desktop-card] TurnFileChangesReview
  — 桌面交互面未在 DESKTOP_CHAT_PARITY 给出手机对等裁决（新增/漏分类）
```

**分类：门禁红 / 产品接缝**（非环境）

- 桌面已有 `apps/desktop/src/renderer/components/chat/TurnFileChangesReview.tsx`（及单测），但手机侧 `DESKTOP_CHAT_PARITY`（`apps/mobile/src/protocol/parity.ts`）未登记该交互面。
- 向量 fold 本身全绿；失败在 **desktop↔mobile parity 裁决表漏项**。
- 本轮**未改产品代码刷绿**（约束：只读/加报告）。

## 原始日志（同目录）

| 文件 | 内容 |
|------|------|
| [`a1-conformance.log`](a1-conformance.log) | 整锅 `pnpm conformance` |
| [`a1-desktop-conformance.log`](a1-desktop-conformance.log) | 桌面单独 conformance |
| [`a2-pytest.log`](a2-pytest.log) | A2 file_ops + code_search |
| [`a2-git-pytest.log`](a2-git-pytest.log) | A2′ git_ops |

## 复现命令

```powershell
# A1
pnpm conformance
# 期望 exit 1，直至 DESKTOP_CHAT_PARITY 补上 TurnFileChangesReview 裁决

# A2
cd apps/server
uv run pytest tests/test_file_ops_tools.py tests/test_code_search.py -q
# exit 0 · 54 passed

# A2′（矩阵「git」）
uv run pytest tests/test_git_ops_tool.py -q
# exit 0 · 37 passed
```

## Gap / 交接

- 修 bug 代理若要刷绿 A1：在 `DESKTOP_CHAT_PARITY` 为 `TurnFileChangesReview` 给出手机对等裁决（实现 / 明确降级 / 桌面专用），**勿**静默关掉 parity 检查。
- A3 仍需人工或 shoot 抽检含工具/协作的 preview fixture。
