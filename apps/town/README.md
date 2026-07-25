# AgentTown（Unity 6 LTS）

AgentCore 模拟观测客户端：**Unity 6 LTS + URP + C#**。产品名 AgentTown，路径 `apps/town/`。

设计权威（架构边界、状态机、Live/Replay、验收基线）→ [AgentTown 客户端](../../docs/04-前端/AgentTown客户端.md)  
运行时 / 后端模拟入口 → [运行时总览 · AI 小镇](../../docs/03-AI核心/运行时总览.md#ai-小镇模拟)  
已知方向摘要 → [产品路线图摘要](../../docs/01-产品/产品路线图摘要.md)（提案全文不在公开仓）

桌面 `#/simulation/town` 仅为**启动器**；3D 在本工程。

## Prerequisites

- **Unity 6000.0.78f1**（与 `ProjectSettings/ProjectVersion.txt` 一致）+ **WebGL Build Support** + Windows Standalone
- 安装脚本：`pwsh apps/town/scripts/install-unity.ps1`（国内可用 `-LocalOnly` 离线旁载）
- 后端：`SIMULATION_ENABLED=true`（`apps/server/.env`），默认 `http://localhost:8000`
- 认证：Bearer（`POST /v1/auth/token`）或 Desktop 写入的 `%APPDATA%/AgentCore/session.json`

## 常用命令（仓库根）

| 命令 | 作用 |
|------|------|
| `pnpm town:open` | 用 Unity Editor 打开本工程 |
| `pnpm town:verify` | batch：URP/场景 setup → EditMode 测试 → Play smoke（**须先关闭 Editor**） |
| `pnpm town:build` | Unity Windows 打包（`build-unity.ps1`） |
| `pnpm town:build:webgl` | Unity WebGL 打包 |
| `pnpm town:serve:webgl` | 静态服 `Builds/WebGL` 并打开 `?demo=1` Offline Demo（无需后端） |
| `pnpm town:shoot:webgl` | 对三 pack offline Demo + 节目模式（`episode_3`）截 PNG → `apps/town/shoot-out/`（须先 `town:build:webgl` + Playwright） |
| `pnpm town:spike:webgl` | WebGL SSE spike（A=CORS；C2=页内 live `sim.*`） |

Editor 接线核对：[EDITOR-WIRING.md](./EDITOR-WIRING.md)

## Quick start

1. **无后端也能看**：Play 后点左侧「离线 Demo」，或启动加 `--demo` / URL `?demo=1`（本地合成多帧，不依赖 LLM）。
2. 有后端时：`SIMULATION_ENABLED=true` → `pnpm town:open` → Play → 新建 Run（默认 scripted）→ Advance Tick。
3. **无 DeepSeek 时用 scripted**：后端设 `SIMULATION_SCRIPTED=true`，或 create body `{"scripted":true}`（Unity 新建默认如此；无凭据时也会自动降级）。
4. **真 LLM 另线**：create 时显式 `scripted:false`，并确认 DeepSeek 凭据；开跑前拧 `SIMULATION_MAX_AGENTS` / `SIMULATION_MAX_TICKS`。
5. Replay / 倍速：有后端时走 `GET /ticks/{n}`；Demo 只读本地缓存。细节 → [AgentTown 客户端](../../docs/04-前端/AgentTown客户端.md)。

### CLI / session.json

```powershell
# 离线演示（无需 API / token）
AgentTown.exe --demo

# 接后端
AgentTown.exe --api=http://localhost:8000 --token=<access_token> [--run-id=<run_id>]
```

取 token：

```powershell
Invoke-RestMethod -Method POST -Uri http://localhost:8000/v1/auth/token `
  -ContentType application/json -Body '{"username":"dev","password":"devpassword"}'
```

无 CLI 时读 `%APPDATA%\AgentCore\session.json`（Desktop 登录后写入）。WebGL：URL query `?api=&token=&run=`；Offline Demo 用 `?demo=1`。

```powershell
pnpm town:build:webgl
pnpm town:serve:webgl
pnpm town:shoot:webgl
pnpm town:spike:webgl
# 仅打印 URL 并开浏览器（不跑 headless）：
powershell -File apps/town/scripts/spike-webgl-sse.ps1 -SkipJslibSmoke -OpenBrowser
```

## 工程布局

```
apps/town/
├── Assets/
│   ├── Scripts/          # Simulation / Town / UI / Show
│   ├── Scenes/Town.unity
│   ├── UI/               # TownHud.uxml / .uss
│   ├── Plugins/WebGL/    # AgentTownSse.jslib
│   ├── StreamingAssets/  # fixtures + personas + show
│   ├── Editor/ · Tests/EditMode/
│   └── TownAssets/       # vendored mesh（见该目录 README）
├── Packages/ · ProjectSettings/
├── scripts/              # open / verify / build / spike / shoot
└── EDITOR-WIRING.md
```

资产真源与 Import workflow → [`Assets/TownAssets/README.md`](./Assets/TownAssets/README.md)。

## 测试

```powershell
pnpm town:verify
```

HTTP 后端烟测（不测 3D）：`pnpm -C apps/desktop sim:smoke:e2e`（可加 `SMOKE_MOCK=1`）。

## Related

- [AgentTown 客户端](../../docs/04-前端/AgentTown客户端.md) · [产品路线图摘要](../../docs/01-产品/产品路线图摘要.md)
- Region fixture：`packages/protocol-conformance/fixtures/simulation-region-positions.json`
- 故事剧本包 SoT：`packages/town-story-packs/`（改完跑 `pnpm gen:story-packs`）
- Desktop 启动器：`apps/desktop/src/main/agenttown-service.ts`
