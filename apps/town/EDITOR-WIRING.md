# AgentTown — Editor 接线清单

> Unity **6000.0.78f1**。多数接线已由 `AgentTown/Setup Project`（`AgentTownProjectSetup`）与仓库内资产落地；本页用于**核对 / 补绑**，不是从零创建指南。
> 上层逻辑（建镇 / NPC / UI Toolkit / Bootstrap）以运行时代码 + 文本资产为主。

## 0. 打开工程

```powershell
pnpm town:open
# 或: pwsh apps/town/scripts/open-unity.ps1
```

首次导入会生成 `.meta`（GUID）——提交这些 `.meta`。确认 Package Manager 已解析：`com.unity.ai.navigation`、`com.unity.render-pipelines.universal`、`com.unity.nuget.newtonsoft-json`、`com.unity.test-framework`（见 `Packages/manifest.json`）。

批量自检（**须关闭 Editor**）：

```powershell
pnpm town:verify
```

## 1. URP（应已存在）

仓库已有 `Assets/Settings/URP-Asset.asset` + Renderer。核对：

- `Project Settings → Graphics` → Scriptable Render Pipeline Settings 指向该 URP Asset
- Quality 各档同样指向
- 若画面粉红/漆黑：菜单 **AgentTown → Setup Project** 重跑

占位材质由代码 `Shader.Find("Universal Render Pipeline/Lit")` 创建。

## 2. Town 场景 + Bootstrap（应已存在）

- 场景：`Assets/Scenes/Town.unity`（Build Settings 首场景）
- `TownBootstrap` 挂 `AgentTown.Town.TownBootstrap`；可复用 Main Camera / Directional Light
- 缺绑定时跑 Setup Project 或见 `TownBootstrapEditor`

## 3. UI Toolkit（应已存在）

| 资产 | 路径 |
|------|------|
| UXML | `Assets/UI/TownHud.uxml` |
| USS | `Assets/UI/TownHud.uss` |
| Panel Settings | `Assets/UI/TownHudPanelSettings.asset` |

Bootstrap 运行时自建 `UIDocument` + `TownHudController` 并绑定。Inspector 上 `Hud Uxml` / `Hud Panel Settings` / `Hud Style Sheet` 应已填；空则补绑或重跑 Setup。

**布局（2026-07-09）**：顶栏状态 · 底栏时间轴 · 左轨运行/上帝 · 右轨居民/决策/事件 Tab · 中央 3D。改 chrome 只动 UXML/USS + `TownHudController` 绑定名；元素 `name` 是绑定契约。产品边界见 [AgentTown 客户端 §7](../../docs/04-前端/AgentTown客户端.md)。

## 4. 真资产（Kenney / Xbot）

1. 资产已 vendored 于 `Assets/TownAssets/`（clone 即用）。新增 mesh 放入对应子目录后，Editor：`AgentTown → Import Town Assets`（或 `Setup Project` / `pnpm town:verify`）→ 写 `Resources/Town/TownMeshCatalog.asset`（building + nature + road 池）+ `TownAssets/Prefabs/`
2. 运行时：`TownBuilder` / `TownNpc` 有 catalog 则实例化 mesh（`TownMeshFit` 统一贴地与高度），否则回退 primitive / 胶囊；无资产也可跑
3. 尺度：Quaternius FBX 与 Kenney GLB 混用时由 `TownMeshFit` 按目标高度归一；道路 mesh 叠在色块路网上（`RoadTiles` 对齐 `Roads`）

## 5. NavMesh

`TownBuilder` 运行时 `NavMeshSurface.BuildNavMesh()`——无需场景内预烘焙。换真实碰撞建筑后可调 `useGeometry` / `NavMeshModifier`。

## 6. 启动参数 / 会话

- 桌面：`AgentTown.exe --api <url> --token <token> [--run-id <id>]`；或 `%APPDATA%/AgentCore/session.json`
- WebGL：`?api=&token=&run=`；Offline Demo：`?demo=1`（`pnpm town:serve:webgl`）；StreamingAssets 走 `UnityWebRequest`
- WebGL SSE：`Plugins/WebGL/AgentTownSse.jslib`；需后端 CORS 含 Web 宿主源（见 [AgentTown 客户端 §15.2](../../docs/04-前端/AgentTown客户端.md)）

## 7. 测试

- EditMode：`WireCoordinateTransformTests`、`SimulationSessionTests`、`TownVisualLayoutTests`、`TownPersonaTests`、`AgentTownLaunchConfigTests`、`TownMeshCatalogTests`
- `pnpm town:verify` = setup + EditMode + Play smoke
- Windows / WebGL 构建命令见 README；自动 CI 门禁仍待补

## 8. 构建目标

- Build Settings 含 `Town.unity`
- Windows / WebGL 目标；`pnpm town:build` / `town:build:webgl` → `build-unity.ps1`（UE 已退役）

## Related

- [apps/town/README.md](./README.md)
- [AgentTown 客户端](../../docs/04-前端/AgentTown客户端.md)
