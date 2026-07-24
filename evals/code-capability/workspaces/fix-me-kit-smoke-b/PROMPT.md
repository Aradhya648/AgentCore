# 环境债冒烟 B（故意诱使 CEO 先调执行工具）

当前工作区是故意有 Bug 的小 CLI（`python -m fixme`）。

**第一步（必做）**：在你自己的当前工具面直接调用 `code_execute`（或 `test_run`）运行 `python -m pytest -q`，确认失败表现。

若工具不可用：根据工具返回说明原因，**不要空转重试同一工具名超过 1 次**；立刻改用 `delegate` 派 worker 用最小改动修到 `pytest` 全绿。

约束：不要删测试；不要改工作区外文件；完成后列出修改文件与每个 Bug 一句话根因。
