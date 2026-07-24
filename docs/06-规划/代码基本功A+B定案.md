---
status: confirmed
related:
  - docs/03-AI核心/Agent记忆与知识系统.md
  - docs/03-AI核心/工具与能力系统.md
  - docs/04-前端/前端UX设计.md
  - docs/02-架构/双模式工作区.md
---

# 代码基本功 A+B 定案（2026-07-23）

> **状态**：已拍板，开始落地。结论迁入 `01`–`05` 时删本文。  
> **谁用 / 问题 / 呈现**：开发者在本地仓用产品 AI 改代码时，要「找得准」+「改动能审」；对标 Cursor 基本功，**不做** AI 代码编辑器正面对抗。

## 目标

| 包 | 目标 | 非目标 |
|---|---|---|
| **B 本地感知** | 绑本地仓时 `code_search` 与云端同质量（含 sidecar ✅ 与云遥控 `LocalWorkspace` 通道） | 不做 prompt 自动 RAG；不做 CommandPalette Tier 3 |
| **A 可审落盘** | 用户能审本回合文件改动（diff），敢用、可回退 | 不做 IDE 内联 Composer / Tab 补全；不照搬 Cursor rules |

## 关键取舍

1. **差异化边界**：品类仍是协作智能平台；A/B 补基本功，不为「变成 Cursor」。
2. **B 路径事实**：sidecar（默认本地引擎）已用 `ServerWorkspace` + `IndexManager`；缺口在云引擎经 `WorkspaceChannel` 遥控桌面的 `LocalWorkspace` stub。B 落地 = 通道路径接同一索引核（读经 backend，索引可落服务端 cache）。
3. **A 分期**：A1 事后可审 → A1+ 基线真 diff → **A2′ 回退到回合基线**（`restore_snapshot`）。**否决**默认预写暂存（A2 完整档）：与现有直写+审批门重叠、接缝成本高。
4. **明确不做（本批）**：MCP、git push/PR 闭环、LSP lint 环、`.cursor/rules` 形态、默认写前暂存。

## 验收

- **B ✅**：`LocalWorkspace.code_search` 样例仓非空命中；单测覆盖；文档已更新。
- **A1 ✅** / **A1+ ✅**：桌面产物卡「查看改动」；云端回合基线快照 + `GET …/messages/{id}/files/diff` 真 before/after；**本地** sidecar 本机基线 zip + RPC 真 diff；失败降级工具参数预览。
- **A2′ ✅**：有基线时「回退到本回合开始」→ 确认后云 `restore_snapshot` / 本机 unzip；整树覆盖；无基线则无此按钮。

## 落地顺序

1. **B ✅** → 2. **A1 ✅** → 3. **A1+ ✅** → 4. **A2′ ✅**（2026-07-23）
