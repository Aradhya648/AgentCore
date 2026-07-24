# AgentTown（Unity 6 LTS）

AgentCore 模拟观测客户端：**Unity 6 LTS + URP + C#**。产品名 AgentTown，路径 `apps/town/`。

当前架构与产品边界：[AgentTown 客户端](../../docs/04-前端/AgentTown客户端.md) · 后续路线：[多 AI 模拟愿景](../../docs/06-规划/多AI模拟愿景.md)

## 现状（2026-07-09 观测层）

| 层 | 状态 |
|----|------|
| Unity Phase 0/1 + Offline Demo | ✅ Session / REST / SSE / 建镇 / NPC / HUD / 决策·事件 / 跟踪 / 日夜 |
| **观测层（可演示）** | ✅ 名牌·热力·交互叠加·日夜·Offline Demo；HUD 为顶栏/底栏/左右轨 chrome（见下） |
| Kenney / Xbot **真资产** | ✅ sync → Import → `TownMeshCatalog`；无资产时 primitive / 胶囊回退 |
| Windows / WebGL **可分发构建** | ✅ 可构建；当前验收基线见 [AgentTown 客户端 §14](../../docs/04-前端/AgentTown客户端.md) |
| **恋综节目模式（离线第 3 期）** | ✅ 左轨「节目」或 `--episode=3` / `?episode=3`；manifest：`StreamingAssets/Fixtures/show/`；代码 `Assets/Scripts/Show/`；服务端节目 API 接入待接（见 [AI 恋综场景提案](../../docs/06-规划/AI恋综场景提案.md)） |
| CORS / WebGL spike Step A + C2 live | ✅（见 `sim.tick_*`；`webgl-jslib-smoke.mjs` 默认严格） |
| UE / Desktop R3F | ✅ **已删** |
| Desktop 启动器 | ✅ `#/simulation/town` 仅 Launcher；失败路径提示；开发期找 `Builds/Windows/AgentTown.exe` |

**收口决策**：删栈以 scripted + WebGL C2 live + FPS 顶栏为准；**真 LLM 涌现验证另线**。新需求只进 Unity。

### HUD 布局（观测台 chrome）

| 区域 | 内容 |
|------|------|
| **顶栏** | 状态 / 时钟 / Tick / SSE · **fps-label**（≥30 绿 / 20–29 黄 / &lt;20 红）· metrics · 修饰符 · 鸟瞰 |
| **底栏** | 推进/暂停 · 回放控件 · **时间轴滑块** · 倍速 |
| **左侧** | 离线 Demo / 新建·恢复 Run · 上帝模式 |
| **右侧** | 居民 / 决策 / 事件（Tab） |
| **中央** | 3D 小镇（主视野） |

资产：`Assets/UI/TownHud.uxml` + `TownHud.uss`；绑定：`TownHudController`。

### Demo 一键可见

Play → 左侧「离线 Demo」后应能看到：

- 头顶名牌 + activity、区域中文标签（**10 区**含图书馆/工坊/码头）、mood/密度热力色块
- 顶栏 metrics / 修饰符；底栏拖时间轴
- 每 3 tick 对话/交易交替、每 6 tick 世界事件、tick 9 投票；右侧事件 Tab 折叠 `sim.tick_*` 噪声
- 决策摘要可读（名 · 动作 · 理由）
- 对话气泡跟活体 NPC；Offline 交互可读停留后淡出；**图书馆 / 工坊 / 码头**在对应 story beat 有可观察对话或交易叠加
- 世界事件中央横幅 + 区域弱高亮
- 底栏「下一故事」跳到下一 interaction / world_event（过滤 tick 噪声）

**演示 = Offline（`--demo`）或后端 scripted**；**真 LLM 另线**（开跑前拧 `SIMULATION_MAX_AGENTS` / `SIMULATION_MAX_TICKS` / `SIMULATION_SCRIPTED`）。

连后端 **scripted**（无 DeepSeek）时：每 3 tick 对话/交易、每 6 tick `world_event`。Unity「新建 Run」默认带 `scripted: true`。上帝模式四预设仅 Live Run 可用。

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
| `pnpm town:shoot:webgl` | 对三 pack Offline Demo + 节目模式（`episode_3`）截 PNG → `apps/town/shoot-out/`（须先 `town:build:webgl` + Playwright） |
| `pnpm town:spike:webgl` | WebGL SSE spike（A=CORS；C2=页内 live `sim.*`） |

Editor 接线核对：[EDITOR-WIRING.md](./EDITOR-WIRING.md)

## Quick start

1. **无后端也能看**：Play 后点左侧「离线 Demo」，或启动加 `--demo` / URL `?demo=1`（本地合成多帧，不依赖 LLM）。
2. 有后端时：`SIMULATION_ENABLED=true` → `pnpm town:open` → Play → 新建 Run（默认 scripted）→ Advance Tick。
3. **无 DeepSeek 时用 scripted**：后端设 `SIMULATION_SCRIPTED=true`，或 create body `{"scripted":true}`（Unity 新建默认如此；无凭据时也会自动降级）；每 3 tick 对话/交易、每 6 tick world_event；5 tick E2E 已绿。
4. **真 LLM 另线**：create 时显式 `scripted:false`，并确认 DeepSeek 凭据；开跑前拧 `SIMULATION_MAX_AGENTS`（默认 5）/ `SIMULATION_MAX_TICKS`（默认 48）。
5. Replay / 倍速：有后端时走 `GET /ticks/{n}`；Demo 只读本地缓存。Live 忽略 `tick_frame`。

### CLI / session.json

```powershell
# 离线演示（无需 API / token）
AgentTown.exe --demo

# 接后端
AgentTown.exe --api=http://localhost:8000 --token=<access_token> [--run-id=<run_id>]
```

取 token：

```powershell
# 示例：Bearer 登录
Invoke-RestMethod -Method POST -Uri http://localhost:8000/v1/auth/token `
  -ContentType application/json -Body '{"username":"dev","password":"devpassword"}'
```

无 CLI 时读 `%APPDATA%\AgentCore\session.json`（Desktop 登录后写入）：

```json
{
  "api_base": "http://localhost:8000",
  "access_token": "<jwt>"
}
```

WebGL：URL query `?api=&token=&run=`（不读本地 session 文件）；**Offline Demo** 用 `?demo=1`（无需 token）。

```powershell
# 先有构建产物：
pnpm town:build:webgl
# 一键静态服 + 浏览器打开 Offline Demo（无需后端 / LLM）
pnpm town:serve:webgl
# 渲染门禁截图（price_surge / festival / town_hall + 节目模式 episode_3 → apps/town/shoot-out/*.png）
# 需已有 WebGL 构建 + Playwright Chromium；缺构建会提示先 town:build:webgl
pnpm town:shoot:webgl

# WebGL SSE：Step A CORS+SSE →（有 Builds/WebGL）起静态服 + Playwright jslib 冒烟
# 默认优先 :8080；被占用（如本机 Sub2API）则回退 :4173（须在 CORS_ALLOW_ORIGINS）
pnpm town:spike:webgl
# 仅打印一键 URL 并开浏览器（不跑 headless）：
powershell -File apps/town/scripts/spike-webgl-sse.ps1 -SkipJslibSmoke -OpenBrowser
# 自动冒烟依赖当前 WebGL 构建能跑完 Boot（到 SSE）；shader 崩则先 town:build:webgl
```

### 观看打磨（本迭代）

| 项 | 入口 |
|----|------|
| **30 FPS 可观测** | 顶栏 `fps-label`：≥30 绿 / 20–29 黄 / &lt;20 红；`FpsSampler` EditMode 单测；Boot 设 `targetFrameRate=60` |
| **建筑 / 自然物距离 LOD** | `TownBuildingLod`：近全模 → 远低模方块 → 更远剔除；自然物用更紧距离（`EnsureNature`）；无资产 primitive 同样生效 |
| **WebGL Demo 分发** | `pnpm town:serve:webgl` → `?demo=1`（缺省剧本包 `price_surge`）；`?pack=festival` / `town_hall` 切换短弧；无 token/run 时自动进 Offline；WebGL 构建关软阴影 |

## Live vs Replay

| Mode | SSE | 位置更新 |
|------|-----|----------|
| **Live**（`playhead == null`） | 处理 `tick_started/ended`、`agent_*` 等；**忽略 `tick_frame`** | `tick_ended` 后 **仅** `GET /ticks/{n}` → `ApplySnapshot` |
| **Replay** | 忽略改世界态的 SSE | 仅 `GET /ticks/{playhead}`；NPC 瞬移 |
| **Offline / Demo** | 无 | 本地 `OfflineDemoBuilder` 帧 → `ApplySnapshot`；播放/倍速同 playhead |
| **Playing** | 同 Replay / Offline | 定时 `playhead++` |
| **到尾** | `GoLive()` | Live 拉最新帧；Offline 跳末帧 |

单一状态机：`SimulationSession`（`Assets/Scripts/Simulation/`）。

## 坐标

契约见 [AgentTown 客户端 §6.2](../../docs/04-前端/AgentTown客户端.md)。Wire（Y-up 右手）→ Unity（Y-up 左手），**仅**在 `WireCoordinateTransform` / `ApplySnapshot`：

```
unity = (wire.x, wire.y, -wire.z)   // S=1，1 wire 单位 = 1 m
```

验收 oracle：`市场` `(36,0,0)` → Unity `(36,0,0)`。EditMode：`WireCoordinateTransformTests`。

## 工程布局

```
apps/town/
├── Assets/
│   ├── Scripts/
│   │   ├── Simulation/     # Session, REST, SSE, 坐标, RegionPositions
│   │   ├── Town/           # Bootstrap, Builder, NPC, Camera, Personas
│   │   └── UI/             # TownHudController
│   ├── Scenes/Town.unity
│   ├── UI/                 # TownHud.uxml / .uss / PanelSettings
│   ├── Settings/           # URP Asset
│   ├── Plugins/WebGL/      # AgentTownSse.jslib
│   ├── StreamingAssets/    # fixtures + town-personas.json
│   ├── Editor/             # ProjectSetup, BatchVerify
│   └── Tests/EditMode/
├── Packages/manifest.json  # URP, AI Navigation, Newtonsoft.Json, Test Framework
├── ProjectSettings/        # 6000.0.78f1
├── scripts/                # open-unity / verify-unity / build-unity / spike-webgl / …
└── EDITOR-WIRING.md
```

## 资产

真源在 `Assets/TownAssets/`（vendored 入库，clone 即用）。新增 mesh 放入对应子目录后，Editor：`AgentTown → Import Town Assets`（或 `pnpm town:verify` / Setup Project）。

- Catalog：`Assets/Resources/Town/TownMeshCatalog.asset`（建筑 prefab 池 + nature 池 + roads 池 + 可选 Xbot）
- FE-18：`Quaternius/` 10 栋 LowPoly Buildings（CC0）为区域主 mesh；缺省时 `RegionKenneyFallbackMeshNames` → Kenney；再缺则 `PickBuilding` 池填充
- 自然物：`Nature/` Kenney Nature Kit 精选 10 GLB（CC0）→ catalog nature 池；`TownVisualLayout.NatureProps` 公园加密 + 路边点缀；无资产绿色 primitive 回退
- 道路：色块加宽底图 + Kenney City Kit (Roads) 精选 8 GLB 主干/路口 mesh（`Roads/` → catalog road 池）；无资产仅色块、不崩
- 无资产 / Import 失败 → `TownBuilder` / `TownNpc` 回退 primitive / 胶囊
- 建筑距离 LOD：`TownBuildingLod`（近全模 → 远低模 → 剔除）；自然物更激进 cull（`EnsureNature`）；与 catalog / 回退共用
- 说明与 workflow：[`Assets/TownAssets/README.md`](./Assets/TownAssets/README.md)

## 测试

```powershell
pnpm town:verify
# 或 Editor: Window → General → Test Runner → EditMode
```

HTTP 后端烟测（不测 3D）：`pnpm -C apps/desktop sim:smoke:e2e`（可加 `SMOKE_MOCK=1`）。

## Related

- 当前设计：[AgentTown 客户端](../../docs/04-前端/AgentTown客户端.md)
- 后续规划：[多 AI 模拟愿景](../../docs/06-规划/多AI模拟愿景.md)
- Region fixture：`packages/protocol-conformance/fixtures/simulation-region-positions.json`
- 故事剧本包 SoT：`packages/town-story-packs/`（改完跑 `pnpm gen:story-packs`）
- Desktop 启动器：`apps/desktop/src/main/agenttown-service.ts`
