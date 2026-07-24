# 可复现 turn 调用配方（事实）

> 只记录仓库现状用法；不改产品契约。权威背景：[本地开发](../../docs/02-架构/本地开发.md)、[双模式工作区 §十 sidecar](../../docs/02-架构/双模式工作区.md)、[认证与会话](../../docs/05-平台与运维/认证与会话.md)。

## 0. 公共前置

1. 基础设施：`docker compose -f deploy/docker-compose.dev.yml up -d`
2. 后端（`apps/server`）：`uv sync` → `.env`（含 `ENCRYPTION_KEY`）→ `uv run python -m agentcore` 或 `powershell -File apps/server/scripts/start-dev-server.ps1`
3. **真跑窗口**：`.env` 设 `AGENTCORE_RELOAD=false`；禁止与黄金场/大批 evals 抢同一上游 key（见本地开发纪律）。
4. Dev 账号：`uv run python scripts/seed_dev_user.py` → 默认 `dev` / `devpassword`（可用 `DEV_USERNAME` / `DEV_PASSWORD` 覆盖）。
5. LLM：桌面设置页 BYOK，或平台免费档 / `PLATFORM_*`（见平台 LLM 接入文档）。无 key 则 turn 会失败——属环境，非矩阵 Fail。

默认 API 根：`http://localhost:8000`（可用 `PROBE_BASE_URL`）。

---

## 1. Server API（对照 / 探针）

### 1.1 鉴权

```http
POST /v1/auth/token
Content-Type: application/json

{"username":"dev","password":"devpassword"}
```

响应取 `access_token`，其后请求头：`Authorization: Bearer <token>`。

### 1.2 建会话 + 发 turn（云默认）

```http
POST /v1/conversations
Authorization: Bearer …
{"title":"code-cap-S6"}

POST /v1/conversations/{conversation_id}/messages
Authorization: Bearer …
Accept: text/event-stream
{"content":"<固定 prompt>"}
```

- 响应为 **SSE**：跟读至 `message_end` 或 `error`（与 `apps/server/scripts/probe_turn.py` 同口径）。
- 一键探针（从 `apps/server`）：

```powershell
uv run python scripts/probe_turn.py --conversation <id> "<固定 prompt>"
# 新建会话可省略 --conversation
```

产物事件 JSON：`logs/probes/probe_<ts>.json`。

### 1.3 工作区绑定要点

| 模式 | 做法 | 限制 |
|------|------|------|
| **云对照（推荐 S6）** | 裸聊默认 cloud；用 `PUT /v1/conversations/{id}/workspace/files/{path}`（或 `PUT /v1/workspaces/conv:{id}/files/{path}`）把 P3 文件字节写入云工作区，再发 messages | 执行在服务端工作区/沙箱语义，**≠** sidecar 本机盘 |
| **显式本地绑定** | `PUT /v1/conversations/{id}/workspace/binding` body `{"root_id":"<desktop-minted>"}` | `root_id` 来自桌面 `addRoot` / `fs-roots.json`；**纯 API 不能发明本机绝对路径**；项目会话（folder）绑定不可改 → 409 |
| **查绑定** | `GET /v1/conversations/{id}/workspace/binding` | 返回 `mode`/`scope`/`root_id`/`source` |

项目本地仓（可选）：`POST /v1/folders` 且 `mode=local` + `local_root_id`（创建后不可改）——仍依赖桌面已登记的 root。

### 1.4 回合后核对（云）

- 消息/成本：既有 `GET …/messages`、`GET …/messages/{message_id}/cost`
- 文件改动 diff（云基线）：`GET /v1/conversations/{id}/messages/{message_id}/files/diff`
- 日志：`logs/dev.jsonl` 按 `conversation_id` / `trace_id`（见对话日志分析指南）；**禁止**在文件系统搜 UUID 当文件名

### 1.5 Resume（API）

挂起后：`POST /v1/conversations/{id}/messages/{message_id}/resume`，body 决策词汇与 live resolve 同形（`continue` / `adjust`+`note` / `stop` 等，见 OpenAPI `Resume` schema）。探针参考：`scripts/probe_resume_memory.py`。

---

## 2. Desktop + sidecar（主路径）

### 2.1 启动

```powershell
cd apps/desktop
pnpm install
pnpm dev
```

登录 dev 账号；设置 → 模型配置：确认 **本地引擎** 有效开（默认开；显式关过的用户须再打开）。

### 2.2 绑定试件工作区

1. 将本机目录指到仓库内：
   - P1：`evals/code-capability/workspaces/hello-cli`
   - P3：`evals/code-capability/workspaces/fix-me-kit`
2. 产品入口（二选一，与现状 UX 一致即可）：
   - **裸聊绑本地目录**：添加本地目录 → 服务端 `PUT …/workspace/binding`（桌面代发 `root_id`）
   - **本地项目 Folder**：创建项目 `mode=local`，选择已授权根
3. 桌面主进程把根记入 userData `fs-roots.json`（`id` + `absPath`）；sidecar 以解析后的 **绝对工作区路径** 为 `workspaceRoot` 跑同一 `run_chat_pipeline`。

路由事实（[双模式工作区 §十](../../docs/02-架构/双模式工作区.md)）：

- **绑本机本地文件夹**的对话默认走 sidecar；裸聊未绑 / 云项目 / 带附件仍走云。
- sidecar 通道：主进程 spawn `python -m agentcore.sidecar`，stdio **JSON-RPC**（`initialize` / `startTurn` / `respond` / `resume` / `cancel`…）；事件经 `turn/event` 桥回，复用同一套 `dispatchSSEEvent`。
- 启动失败且尚未产出：自动降级云重跑；中途失败不自动降级。

### 2.3 发起一轮 turn

1. 打开已绑定会话，输入框粘贴该场景 `PROMPT.md`（或 parallel-briefs 指定文案）。
2. 发送 → UI 走 sidecar `startTurn`（或降级云 `POST …/messages`）。
3. 交互卡（AskUser / plan_review / 审批）：在 UI 决策；冷恢复走 `sidecar:recovery` / `resume`（与云 paused 投影同形）。

**D·引擎验收**：与 Desktop 主进程同构的 sidecar **JSON-RPC**（`initialize` / `startTurn` / `respond` / `resume` / `turnFilesDiff`…）算 Pass；人手点 Electron UI 为可选 **U 层**，不挡 D。勿用无关 curl/云 `POST …/messages` **冒充**本地 sidecar 主路径；云 API 仅作 **S6** 对照。

> **S3 例外**：验收含「刷新/重进仍见卡」——属渲染层 `ResumePrompt`，**无** `turnFilesDiff` 式 RPC 等价；`listPaused`/`resume` 不够。人手步骤见 [runbooks/s3-resume-ui.md](runbooks/s3-resume-ui.md)。

### 2.4 回合后核对（本地主路径）

- 磁盘：直接在试件目录看文件 / 跑 `GOLDEN.md` 命令。
- 产物卡「查看改动」：本地走 sidecar `turnFilesDiff`；云走 `GET …/files/diff`（见 `apps/desktop/src/renderer/services/turnFilesDiff.ts`）。
- 回退到回合基线（若有基线按钮）：确认后本机 unzip / 云 `restore_snapshot`——**S4 建议用工作区副本**，避免毁掉其它并行场景的盘。
- 失败复盘：同一套 `conversation_id` / `trace_id` + `logs/dev.jsonl`；本地 outbox 回写见双模式工作区 §10.3。

---

## 3. A 层离线（无 turn）

```powershell
# 协议 fold
pnpm conformance

# 后端代码工具相关单测（矩阵 A2；文件名以仓库现状为准）
cd apps/server
uv run pytest tests/test_file_ops_tools.py tests/test_code_search.py -q
```

preview 回放：见 `.cursor/rules/frontend-preview.mdc`（`pnpm dev:web` + `#/preview`）。

---

## 4. 并行纪律（执行期）

- 每场景 **独立 conversation**；P1/P3 若多场景同试件，先 **复制工作区目录** 再绑，禁止多子代理写同一 absPath。
- 同时 ≤6；共享上游 key 时串行重活、错峰。
- 每条报告必带：场景 ID、工作区路径、`conversation_id`、`trace_id`（或 message_id）、Pass/Fail/Gap。
