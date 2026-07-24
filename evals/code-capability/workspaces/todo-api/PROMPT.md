# todo-api 固定 Prompt（S7）

请在**当前工作区**从零实现一个最小 HTTP Todo API（Python）：

1. 内存存储（进程内即可，不要求持久化）。
2. `GET /todos`：返回当前全部 todo 的 JSON 列表。
3. `POST /todos`：接受 JSON body（至少含 `title` 字符串），创建一条 todo 并返回；新建项须有稳定 `id`。
4. 实现优先用 **stdlib**（如 `http.server`）；若用 FastAPI/Starlette/Flask，须在工作区内声明依赖且可本地安装。
5. 补至少 **2** 个 pytest，覆盖 list + create，并在工作区内跑通 `python -m pytest -q`。

约束：只改本工作区；不要改工作区外的 AgentCore 产品代码；完成后简述创建了哪些文件，以及如何启动服务与探测。
