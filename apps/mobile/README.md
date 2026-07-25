# AgentCore 手机端（apps/mobile）

独立 **Vite + React** 应用（非桌面端裁剪包）：自有 stores / services / 协议 fold / 组件。Web 可本地或 Cloudflare Pages 部署；原生壳为 **Capacitor 8**（**Android 侧载 APK 已落地**，见下文「Android 发版」）。鉴权走 **Bearer**（与桌面 cookie 会话不同）。

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
| Android 发版 / CORS / FCM 闸 | [`部署与运维` §7.6a](../../docs/05-平台与运维/部署与运维.md)；下文清单 |
| clone 后跑通 | [`本地开发`](../../docs/02-架构/本地开发.md) §3 |

产品减法与商店 / iOS 余项以设计文档为准；远期能力见 [`产品路线图摘要`](../../docs/01-产品/产品路线图摘要.md)（提案全文不在公开仓）。

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
| `pnpm -C apps/mobile android:sync-version` | 把 `package.json` version 写入 Gradle |
| `pnpm -C apps/mobile android:assemble` | 同步版本 + 签名 `assembleRelease` |
| `pnpm -C apps/mobile release:android` | 打正式 APK 并上传发布仓 draft |
| 仓库根 `pnpm gen:types` | 同步共享 REST / 事件类型 |
| 仓库根 `pnpm release:gate --only mobile` | 仅跑门禁手机段 |

改 SSE / fold / 跨端投影后：务必仓库根 `pnpm conformance`，勿只改一端。

## Android 发版（侧载 APK）

官网侧载；App 内仅软提示「去下载」（浏览器打开 APK URL），**不强制、不静默换包、不做 Capacitor OTA**。

| 项 | 约定 |
|----|------|
| 产物 | `AgentCore-<ver>-android.apk` |
| Tag | `android-v<ver>`（与桌面 `v<ver>` 分轨） |
| 发布仓 | [`Lawofall/AgentCore-releases`](https://github.com/Lawofall/AgentCore-releases) |
| 烘焙 API | `VITE_API_URL` / `AGENTCORE_APP_API_URL` / `AGENTCORE_APP_HOST`（与 `deploy:pages` 同口径） |

### 签名

1. 生成 release keystore（只做一次，离线妥善保管）。
2. 复制 `android/keystore.properties.example` → `android/keystore.properties`，填入 `storeFile` / 密码 / `keyAlias`。
3. **`keystore.properties` 与 `*.keystore` 已 gitignore，勿提交。**
4. 无 `keystore.properties` 时 `release:android` / `android:assemble` **会明确失败**（不会默默打出 unsigned 当正式包）。

### 本机构建环境

- **JDK 21**（Capacitor 8 / AGP 要求；`JAVA_HOME` 指向 JDK 21）
- Android SDK（`android/local.properties` 的 `sdk.dir`，或 `ANDROID_HOME`）
- 首次 Gradle 若下载超时：已将 wrapper `networkTimeout` 调大；也可手动预置 `gradle-*-all.zip`

### 发第一包 checklist

1. 确认 `apps/mobile/package.json` 的 `version`（会写入 `versionName`；`versionCode = major*1e6 + minor*1e3 + patch`）。
2. Android SDK：`android/local.properties` 的 `sdk.dir=…`，或环境变量 `ANDROID_HOME`。
3. 配置好 `android/keystore.properties`。
4. `gh auth login`（对 `Lawofall/AgentCore-releases` 有写权限）。
5. 跑：

```bash
pnpm -C apps/mobile release:android
# draft 已存在时可：
pnpm -C apps/mobile release:android -- --skip-draft
```

6. 真机侧载 `release/<ver>/AgentCore-<ver>-android.apk` 冒烟后转正：

```bash
gh release edit android-v<ver> --repo Lawofall/AgentCore-releases --draft=false
```

脚本末尾会跑 `sync-release-cdn --android`（品牌域 `downloads.*/android/` + `latest.json`）。若该步因路径空格失败，可手动：

```bash
node deploy/scripts/sync-release-cdn.mjs --android apps/mobile/release/<ver>/AgentCore-<ver>-android.apk --version <ver>
```

7. App 内更新提示：原生壳拉 `https://downloads…/android/latest.json`，与本地 `clientVersion()` 做 semver 比较；仅 Android；`dev` 不提示。官网下载按钮另走 GitHub Releases 资产探测。

8. **生产 CORS**：后端 `CORS_ALLOW_ORIGINS` 须含 `https://localhost`（及 `capacitor://localhost` / `http://localhost`）。缺则壳内「无法连接后端」。补洞脚本：`node deploy/scripts/add-capacitor-cors.mjs`。

## FCM 推送（原生）

**无 `google-services.json` 时千万不要调用 `PushNotifications.register()`**——Android 会原生闪退（`FirebaseApp is not initialized`），JS `try/catch` 拦不住。`release:android` 仅在检测到 `android/app/google-services.json` 时注入 `VITE_PUSH_ENABLED=true`；否则推送整段 no-op，App 可正常用。

客户端：把 Firebase 控制台下载的 `android/app/google-services.json` 放到工程内（**已 gitignore，勿提交**），再重新 `release:android`。

服务端（`apps/server/.env`）：

- `PUSH_ENABLED=true`
- `FCM_SERVICE_ACCOUNT_PATH=/path/to/firebase-service-account.json`（服务账号 JSON，勿入仓）

真机验收要点：登录后设备出现在 `/v1/devices`；触发「需要你」暂停应收到通知；点通知应深链到对应会话。

## 贡献

[`CONTRIBUTING.md`](../../CONTRIBUTING.md)
