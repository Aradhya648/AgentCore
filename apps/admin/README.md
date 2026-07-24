# AgentCore 管理后台 (apps/admin)

平台运营者的**独立 web 控制台**（React + Vite + Tailwind v4）。与桌面端（Electron）解耦，单独部署、独立登录、内网访问。形态决策与后端契约见 [`docs/05-平台与运维/管理员后台.md`](../../docs/05-平台与运维/管理员后台.md)。

## 现状

五页（概览 / 用户 / 分析 / 系统 / **审计**），侧栏 + **URL 路由**（`react-router`）切换，默认「概览」：

- **概览**：今日脉搏摘要 + 部署健康灯带 + 近期错误 preview；点卡片深链到对应详情页（纯枢纽，不重渲染明细）。
- **用户**：账号名册（分页 + 搜索）、改角色（user/admin）、禁用 / 启用、改配额；点用户名下钻详情（`/users/:userId` 可书签）、详情页可**设置密码**与**重置密码**。
- **分析**：跨用户**成本**与**健康**两段切换（`/analytics/cost` · `/analytics/health`）；近期错误 / 会话 ID → `/replay/:conversationId` 会话复盘。
- **审计**：管理员特权操作记录（改用户 / 重置密码 / 注销 / 历史邀请码操作），分页 + 按操作类型筛选。
- **系统**：只读部署快照；**首次部署**时在管理员 ≤1 且用户极少时显示 `create_admin.py` 引导；注册关闸见 `REGISTRATION_OPEN`。
- 登录：复用后端 `/v1/auth/login`（cookie 会话），仅 `role==admin` 可进；非管理员落「需要管理员权限」墙。

> 邀请码控制台入口已下线（开放注册）；`/v1/auth/invites*` API 与 `InvitesPage` 文件可保留但不可达。

## 本地开发

```bash
pnpm install        # 同时经 postinstall 从 ../server/openapi.json 生成 API 类型
pnpm dev            # http://localhost:5174
```

需要后端在 `http://localhost:8000` 运行（或用 `VITE_API_URL` 指定，见 `.env.example`）。

### 跨 origin 鉴权（CORS + Cookie）

控制台跑在 `:5174`、后端在 `:8000`——不同 origin 但同站（localhost），故：

- 后端须把本 origin 加入 `cors_allow_origins`（默认已含 `http://localhost:5174`），`allow_credentials=True`。
- 请求一律 `credentials: "include"`；cookie 为 `SameSite=Lax`（同站可跨 origin 携带）。
- 生产：控制台部署在**内网独立 origin**，按需收紧 `COOKIE_SECURE` / `COOKIE_SAMESITE`。

## 类型

REST 类型从后端 OpenAPI 生成（单一真相源），勿手写：

```bash
pnpm gen:api        # openapi-typescript ../server/openapi.json -> src/types/api.generated.ts
```

改了后端 schema 后，先在 `apps/server` 跑 `uv run python scripts/dump_openapi.py`，再回此处 `pnpm gen:api`。

## 命令

| 命令 | 作用 |
|---|---|
| `pnpm dev` | 开发服务器（5174）|
| `pnpm build` | 类型检查 + 生产构建 |
| `pnpm typecheck` | 仅 `tsc --noEmit` |
| `pnpm gen:api` | 重生成 API 类型 |
