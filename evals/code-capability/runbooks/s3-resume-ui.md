# S3 · 中断 / Resume（U 层人手 Runbook）

> **Verdict 口径**：本场景 **仍待人手 / CDP**，**不要**用 sidecar `resume` / `listPaused` 探针冒充 Pass。  
> **为何不能 RPC 等价**（相对 S4 `turnFilesDiff`）：「刷新/重进仍见卡」断言的是 Electron 渲染层 `ResumePrompt` 是否画出拍板卡。桌面冷恢复走主进程 `sidecar:recovery`（读 `<userData>/sidecar/paused/*.json`）→ store → 卡组件；`listPaused`/`resume` 只覆盖**帧落盘 + 续跑**数据面，**不**覆盖「仍见卡」。扩 CDP / 改契约属产品决策，本 runbook 不代跑。

## 前置

| 项 | 要求 |
|----|------|
| 试件 | `evals/code-capability/workspaces/fix-me-kit-s3/`（独占；勿与 S2/S4 同盘） |
| Prompt | 同目录 `PROMPT.md`（要求先 `ask_user` 确认范围再改文件） |
| 黄金 | 同目录 `GOLDEN.md`（挂起前 pytest 应 3 failed；结束后全绿） |
| 客户端 | Desktop `pnpm dev`（`apps/desktop`）；登录 **dev**；**本地引擎**有效开 |
| 服务端 | 本地 API 可用（推理 token / BYOK 与现网一致） |

基线自检（绑盘前，在试件根）：

```powershell
cd evals/code-capability/workspaces/fix-me-kit-s3
python -m pytest -q
```

预期 **3 failed**。若不是 → 停，试件已漂移。

## 步骤

### 1. 绑根 + 开会话

1. Desktop：添加本地目录，指向仓库内  
   `C:\Project\AgentCore\evals\code-capability\workspaces\fix-me-kit-s3`  
   （或等价绝对路径；经产品「本地项目 Folder」/`mode=local` 亦可）。
2. 新建对话（标题建议 `code-cap-S3`），确认走 **本地引擎 / sidecar**（绑本机文件夹后默认如此）。
3. 记下侧栏或调试信息中的 **`conversation_id`**（后续回填）。

### 2. 贴 Prompt → 等挂起卡

1. 将 `PROMPT.md` **全文**粘贴进输入框发送。
2. 等待 Agent 调出交互挂起（优先 `ask_user` 确认修复范围；亦可能 `plan_review`）。
3. **可操作面**在对话下方 **`ResumePrompt` 拍板卡**（非内联灰记录卡）。  
   时间线可能出现「等你拍板 · …」单行标记——完整答题体在下方拍板卡。
4. **在拍板之前**：确认工作区源文件尚未被改（或仅有非源文件噪声）；Prompt 要求确认前禁止改源文件。

### 3. 刷新 / 重进仍见卡（本场景硬门槛）

任选其一（建议两种都做一次）：

| 方式 | 操作 | 期望 |
|------|------|------|
| A · 刷新 | 当前对话页 **硬刷新**（或关窗再开同一对话） | 重载后下方仍出现 **同一拍板卡**（问题/选项仍在） |
| B · 重进 | 切到其它会话再切回本会话；或退出 Desktop 再进、打开同一对话 | 同上：`ResumePrompt` 仍可见、可点 |

Fail 信号：重进后拍板卡消失、只剩正文且无法续跑、或卡变「确认已失效」。

### 4. 决策后继续

1. 在拍板卡上确认范围（`continue` / 选选项；若需调整用 `adjust`+备注）。
2. 等待回合继续：最小改动修三坑 → `python -m pytest -q` 全绿（Agent 侧或你在试件根手跑均可）。
3. 确认挂起前约定不丢：若确认时写了范围备注，续跑后行为与之一致；已有写盘（若挂起前偶发写了非源文件）不无故回滚。

### 5. 回填证据（主 Agent / README）

全部满足才可标 **Pass（U）**；否则 **Fail** + 现象，**禁止**标 D Pass。

| 字段 | 来源 |
|------|------|
| `conversation_id` | 会话 id |
| `trace_id` | 本回合日志 / 开发者工具 / `logs/dev.jsonl`（按 conversation 过滤） |
| `message_id` | 挂起助手消息 id（拍板卡 / journal / 恢复摘要） |
| 刷新验证 | 写明 A/B 哪条做过、卡是否仍见 |
| 磁盘 | `pytest -q` 退出码；可选列 diff 文件 |

回填入口：[`../README.md`](../README.md) S3 行、[`../matrix.md`](../matrix.md) 本轮列。

## 非目标 / 禁区

- **禁止**用 `evals/code-capability/probe_sidecar_turn.py`（或仅 `resume`/`listPaused`）把本场景记成 Pass。
- 不测产物卡「查看改动」（属 S4 U）；不做多 Agent 强派（属 S5）。
- 不与 S2/S4 共用 `fix-me-kit-s3` 盘做破坏性回退。
- 若要用 CDP 自动化「仍见卡」：先立项产品决策（选择器稳定面 / 是否扩 conformance），**本 runbook 不解禁**。

## 相关代码锚点（排障）

- 冷恢复：`apps/desktop/src/renderer/services/resume.ts` → `loadRecovery` → `window.sidecarApi.recovery`
- 拍板卡：`apps/desktop/src/renderer/components/chat/ResumePrompt.tsx`
- 本机 paused 帧：`<userData>/sidecar/paused/*.json`（与 sidecar `listPaused` 同源；列举无需引擎在跑）
