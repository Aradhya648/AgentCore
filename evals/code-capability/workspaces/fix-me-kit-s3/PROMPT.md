# fix-me-kit-s3 · S3 中断/Resume 固定 Prompt（B · Desktop+sidecar）

当前工作区是一个故意有 Bug 的小 CLI（`python -m fixme`）。本回合**只做中断/Resume 验收**，请严格按顺序：

1. **先**用 `ask_user`（或等价交互卡）确认修复范围：列出你认为要改的文件与每个 Bug 一句话根因，问我是否按此最小改动继续。**在我确认之前禁止改任何源文件。**
2. 我确认（或调整范围）后，再用最小改动让 `python -m pytest -q` 全绿。
3. 不要删测试、不要重写整个项目、不要改工作区外文件。

> 执行者验收（非模型任务）：挂起卡可见 → 刷新/重开本对话仍见卡 → 决策后继续且挂起前约定不丢；记下 `conversation_id` / `trace_id` / `message_id`。
