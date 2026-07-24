# P2 todo-api · 黄金验收

> **角色**：C 全真加码试件。目录初始 intentionally 近空——由 Agent **从零**实现。  
> **并行**：开跑前复制本目录为 `todo-api-s7/`，勿多场景共用。

## 初始状态（已备好）

- 仅有本文件、`PROMPT.md`、`README.md`（无业务源码）。
- 验收命令在 Agent 落盘后、于**工作区根**执行。

## 规格（须全部满足）

| 项 | 要求 |
|----|------|
| 栈 | **优先** Python stdlib（`http.server` / `urllib` 可测）；允许极简 FastAPI/Starlette/Flask，但须可本地安装且 pytest 可测 |
| 存储 | **内存**（进程内 list/dict 即可；不要求 DB/文件持久化） |
| 路由 | `GET /todos` · `POST /todos`（路径可带尾斜杠，报告写明实际路径） |
| `GET /todos` | `200`；`Content-Type` 含 `application/json`；body 为 **JSON 数组**（初始可 `[]`） |
| `POST /todos` | 请求 JSON 至少含 `title`（string）；`201` 或 `200`；返回 JSON 对象，须含稳定 `id` 与写入的 `title` |
| 测试 | ≥ **2** 个 pytest；建议直接打 handler / 起临时 server（勿依赖外部已起的服务） |

推荐布局（非强制，二选一写进报告即可）：

- `todo_api/server.py` + `todo_api/__main__.py`（`python -m todo_api`）
- 或根级 `main.py` / `app.py`

## 通过标准（全部满足才 Pass）

1. 存在可启动的 HTTP 入口（报告写明模块/命令）。

2. 测试全绿：

```powershell
python -m pytest -q
```

退出码 **0**；至少 2 条用例通过。

3. 手工启动与探测（Windows PowerShell；端口可改，报告写明）：

```powershell
# 终端 A：启动（示例：stdlib 包入口）
python -m todo_api --host 127.0.0.1 --port 8765
# 若入口不同，用报告中的实际命令替代

# 终端 B：探测
Invoke-RestMethod -Uri http://127.0.0.1:8765/todos -Method GET
# 期望：空列表或已有项的数组

Invoke-RestMethod -Uri http://127.0.0.1:8765/todos -Method POST -ContentType 'application/json' -Body '{"title":"buy milk"}'
# 期望：含 id 与 title=buy milk 的对象

Invoke-RestMethod -Uri http://127.0.0.1:8765/todos -Method GET
# 期望：列表中含刚创建的项
```

退出码 0（cmdlet 无抛错）；JSON 形状符合上表。

4. 报告附：`conversation_id`、`trace_id`（或 assistant `message_id`）、实际入口命令、选用栈（stdlib / FastAPI / …）。

## 非要求

- 不要求鉴权、分页、PUT/DELETE、OpenAPI 文档、Docker、持久化、类型检查全绿。
- 不要求实现 P1 hello-cli / P3 fix-me-kit。
