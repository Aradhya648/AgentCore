# P1 hello-cli · 黄金验收

> **角色**：C 全真主试件。目录初始 intentionally 近空——由 Agent **从零**实现。  
> **并行**：开跑前复制本目录，勿多场景共用。

## 初始状态（Phase 1 已备好）

- 仅有本文件、`PROMPT.md`、`README.md`（无业务源码）。
- 验收命令在 Agent 落盘后、于**工作区根**执行。

## 通过标准（全部满足才 Pass）

1. 存在可导入/可执行的 CLI 入口（推荐：`hello_cli/` 包 + `__main__.py`，或根级 `main.py`——二选一写进报告）。
2. 帮助：

```powershell
python -m hello_cli --help
# 若入口不同：python main.py --help
```

退出码 **0**，stdout 含用法说明。

3. 子命令 **greet**（名字参数）：

```powershell
python -m hello_cli greet Ada
```

退出码 0，stdout 含 `Hello, Ada`（允许前后缀空白/换行）。

4. 子命令 **add**（两整数）：

```powershell
python -m hello_cli add 2 3
```

退出码 0，stdout 为 `5`（允许仅数字行）。

5. 至少 1 个自动测试且通过，例如：

```powershell
python -m pytest -q
```

退出码 0。

6. 报告附：`conversation_id`、`trace_id`（或 assistant `message_id`）、实际入口模块名。

## 非要求

- 不要求打包发布、不要求 git commit、不要求类型检查全绿。
- 不要求实现 P2 todo-api。
