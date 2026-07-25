# AgentCore 手机端（apps/mobile）

独立 **Vite + React** 应用（非桌面端裁剪包）：自有 stores / services / 协议 fold / 组件。Web 可本地或 Cloudflare Pages 部署；原生壳为 **Capacitor 8**（Android 工程已 scaffold）。鉴权走 **Bearer**（与桌面 cookie 会话不同）。

## 何时读这里

- 改手机布局、会话列表、跨端 fold 投影 → 从本目录动手
- 改桌面专属能力（Sidecar、本地 FS、Electron）→ [`apps/desktop`](../desktop/README.md)
- 改 API / 执行语义 → [`apps/server`](../server/README.md)

## 文档入口

| 主题 | 文档 |
|------|------|
| 手机定位、减法、Capacitor | [`前端技术与架构` §七](../../docs/04-前端/前端技术与架构.md) |
| 跨端 fold / 协议 | 同文档 §十二；根目录 `pnpm conformance` |
| 前端总读序 | [`前端地图`](../../docs/04-前端/前端地图.md) |
| 目录边界 | [`项目结构` §四](../../docs/02-架构/项目结构.md) |
| clone 后跑通 | [`本地开发`](../../docs/02-架构/本地开发.md) §3 |

产品减法与商店余项以设计文档为准；远期壳能力见 [`产品路线图摘要`](../../docs/01-产品/产品路线图摘要.md)（提案全文不在公开仓）。

## 本地启动

后端需在本机 `:8000`。依赖在**仓库根** `pnpm install`。

```bash
pnpm -C apps/mobile dev
# 本机：http://localhost:5175/
```

- **真机 LAN**：同一 WiFi 打开 `http://<开发机局域网 IP>:5175/`（Vite `host: true`）。API 经同源 `/api/*` 反代到 `localhost:8000`，一般无需改 CORS 或把 IP 写进 `.env.local`。
- **离线看 UI 态**：`http://localhost:5175/preview`（或 `?s=<向量名>`）回放 conformance 向量，零后端。
- 可选：`apps/mobile/.env.local` 配 `VITE_DEV_USERNAME` / `VITE_DEV_PASSWORD`（先跑后端 `seed_dev_user.py`）自动登录。

截图示例：

```bash
pnpm -C apps/mobile shot http://localhost:5175/preview?s=single_agent_tool
```

## 常用命令

| 命令 | 作用 |
|------|------|
| `pnpm -C apps/mobile dev` | 开发服务器（5175） |
| `pnpm -C apps/mobile build` | 类型检查 + 生产构建 |
| `pnpm -C apps/mobile test` | Vitest |
| `pnpm -C apps/mobile typecheck` | `tsc --noEmit` |
| `pnpm -C apps/mobile lint` | Biome + UI token 门禁 |
| `pnpm -C apps/mobile conformance` | 本端协议 conformance |
| `pnpm -C apps/mobile shot <url>` | 页面截图 |
| `pnpm -C apps/mobile cap:sync` | 构建并 `cap sync` |
| `pnpm -C apps/mobile android:open` | 打开 Android 工程 |
| 仓库根 `pnpm gen:types` | 同步共享 REST / 事件类型 |
| 仓库根 `pnpm release:gate --only mobile` | 仅跑门禁手机段 |

改 SSE / fold / 跨端投影后：务必仓库根 `pnpm conformance`，勿只改一端。

## 贡献

[`CONTRIBUTING.md`](../../CONTRIBUTING.md)
