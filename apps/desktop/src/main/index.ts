import { join, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { is } from "@electron-toolkit/utils";
import { isSafeExternalUrl } from "@shared/safe-url";
import { WINDOW_CHANNELS } from "@shared/window-contract";
import { net, BrowserWindow, app, ipcMain, protocol, shell } from "electron";
// `?asset` 让 electron-vite 把图标拷入产物并解析为运行时绝对路径；用作窗口/任务栏图标
// （dev 与 Linux 主要靠它；打包后 Windows exe / macOS 包图标另由 electron-builder 从
// build/icon.png 派生）。
import icon from "../../resources/icon.png?asset";
import { registerAgentTownIpc } from "./agenttown-service";
import { registerFsIpc } from "./fs-service";
import { registerLocalStoreIpc } from "./local-store";
import { registerLogIpc } from "./log-service";
import { registerNotificationIpc } from "./notification-service";
import { registerOutboxIpc } from "./outbox-writeback";
import { registerPreviewIpc } from "./preview/ipc";
import { PREVIEW_SCHEME } from "./preview/paths";
import { registerProcessIpc } from "./process-service";
import { registerPtyIpc } from "./pty-service";
import { registerSidecarIpc } from "./sidecar-service";
import { registerTerminalIpc } from "./terminal-service";
import { initUpdater } from "./updater";
import { registerWindowFrameIpc } from "./window-frame";
import { loadWindowState, manageWindowState } from "./window-state";

// Production renderer is served from a custom app:// scheme instead of file://,
// so it gets a real, stable origin (app://agentcore). That origin is what makes
// credentialed cross-origin calls to the cloud API governable by CORS + cookies
// (前端技术与架构.md §7.2) — a file:// (null/opaque) origin can't be allowlisted.
// Scheme privileges must be registered before the app `ready` event.
const APP_SCHEME = "app";
const APP_ORIGIN_HOST = "agentcore"; // renderer origin = app://agentcore
const APP_ORIGIN = `${APP_SCHEME}://${APP_ORIGIN_HOST}`;
const RENDERER_ROOT = join(__dirname, "../renderer");

// SECURITY (XSS-001 前端XSS·纵深 CSP): the packaged renderer is served over app://, so we
// stamp a Content-Security-Policy on every app:// response — the containment layer for any
// future DOM-XSS.
//
// 设计取舍（最正确设计，非便利妥协）: `script-src 'self'` WITHOUT `'unsafe-eval'` /
// `'unsafe-inline'`. mermaid 的图表源是【攻击者可影响】的（模型 / 间接注入可吐 ```mermaid
// 块），而 `'unsafe-eval'` 会把 eval/new Function 在【整个文档】放开——正好是恶意 mermaid 块
// 把「解析图表」变成「主源代码执行」所需的原语，所以绝不全局放开 eval。
// 实测（apps/mobile 打包产物，同一 mermaid 包）证明严格策略可行：mermaid v11 把每种图表当成普通
// 动态 import() 的 ES chunk 从 'self' 加载（script-src 'self' 已覆盖），全程无 new Worker /
// createObjectURL / 真 eval；唯一的 Function 构造器用法是 lodash 取全局的 `Function("return this")()`，
// 在浏览器里被前面的 `self` 短路、根本不执行。`script-src 'self'` 可行的另一前提是 built index.html
// 无 inline `<script>`（electron.vite.config.ts 关掉 Vite 的 modulepreload polyfill）。
// `style-src` 必须留 'unsafe-inline'——React / Tailwind / KaTeX 用 style【属性】，CSP 的 nonce/hash
// 管不到 style 属性，且样式注入风险远低于脚本。
// NOTE: 此 header 仅作用于 app://（prod）；`pnpm dev` 经 loadURL 走 Vite server，HMR 不受影响。
// 兜底阶梯（若未来 mermaid 改为主线程 eval 而报错）: 升级为 mermaid securityLevel:'sandbox'
// （沙箱 iframe 隔离其动态代码），而【绝不】全局加 'unsafe-eval'。

// 后端源：由 electron.vite.config.ts 的 main.define 在构建期注入（= 渲染层 VITE_API_URL 的同源，
// 见 .env.production）。用于把 img-src 精确收窄到「自己 + 后端」——只放行后端头像 / favicon，任意
// 第三方远程图被 Chromium 拦死。无法解析（极端构建配置缺失）→ 空串 → 退化为「只允许自己 + data:」。
declare const __API_BASE_URL__: string;
function apiOriginForCsp(): string {
  try {
    return new URL(__API_BASE_URL__).origin;
  } catch {
    return "";
  }
}
const API_ORIGIN = apiOriginForCsp();

// connect-src（XSS-001·纵深）: connect-src 管的是渲染层 fetch / SSE / WebSocket 出网。后端源是
// 【构建期】烘焙的——渲染层 services/api.ts 的 BASE_URL 与本 CSP 的 __API_BASE_URL__ 同出一个
// VITE_API_URL（见 electron.vite.config.ts），故全应用只有一个后端源、可钉死它。渲染层每个请求都走
// `${BASE_URL}/...`（REST + fetch 式 SSE；今日无 WebSocket、无跨源 fetch），所以收窄到「自己 + 该源」
// 对真实流量是 no-op，却把 connect-src 变成 script-src 'self' 背后的【外泄墙】（未来即便出 DOM-XSS 也
// 无处 POST 数据 / 开 socket）。仅当源不可解析（极端构建缺 env）才【失败放开】退回宽策略——宁宽勿把
// 自己锁在 API 门外。ws/wss 收同源（后端 http→ws / https→wss），放行未来同主机实时通道。
const CONNECT_SRC = API_ORIGIN
  ? `connect-src 'self' ${API_ORIGIN} ${API_ORIGIN.replace(/^http/, "ws")}`
  : "connect-src 'self' https: http: ws: wss:";

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  // worker-src = 前瞻防御：当前 mermaid 不开 worker（走 dynamic import chunk），但若未来版本把
  // 解析挪进 Web Worker，self + blob 让动态能力留在 worker 边界内，仍不必污染主文档 script-src。
  "worker-src 'self' blob:",
  "style-src 'self' 'unsafe-inline'",
  // 渲染期外泄信标·纵深防线（红队 2026-06-30 · V1/V2/V3 同一类）：vega/mermaid/markmap 等引擎会在
  // 渲染期对 <img src=远程> / data.url 零点击取资源（DOMPurify 只清脚本/事件、不挡「取图」这种联网，
  // 故 mermaid strict 也挡不住）。img-src 只放行 自己 + data: 内联 + 你的后端源（头像/favicon），任意
  // 第三方远程图被浏览器拦在网络层——比逐引擎加门卫更治本（连未来新增的图表引擎一并覆盖）。
  `img-src 'self' data:${API_ORIGIN ? ` ${API_ORIGIN}` : ""}`,
  "font-src 'self' data:",
  CONNECT_SRC,
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
].join("; ");

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: {
      standard: true, // proper origin semantics (app://host/path)
      secure: true, // secure context → allows Secure cookies, etc.
      supportFetchAPI: true, // renderer can use fetch (API client + SSE)
      corsEnabled: true, // cross-origin requests go through CORS
    },
  },
  {
    // 预览宿主子窗口的字节协议（preview://<conversationId>/<path>，见 preview/protocol.ts）。
    // standard=true 才有层级 URL 语义 → 相对路径引用（./style.css、img/logo.png）能按文档
    // URL 正确解析；secure=true 给隔离预览页一个安全上下文；stream 支持大文件流式代理。
    scheme: PREVIEW_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);

// Serve the built renderer bundle over app://agentcore/<path>. HashRouter keeps
// every route on index.html (only the hash changes), so no SPA path fallback is
// needed. Reads are confined to RENDERER_ROOT (path-traversal guard).
function registerAppProtocol(): void {
  protocol.handle(APP_SCHEME, async (request) => {
    const { pathname } = new URL(request.url);
    const relativePath =
      pathname === "/" ? "index.html" : decodeURIComponent(pathname.slice(1));
    const filePath = join(RENDERER_ROOT, relativePath);
    if (!filePath.startsWith(RENDERER_ROOT + sep)) {
      return new Response("Forbidden", { status: 403 });
    }
    const res = await net.fetch(pathToFileURL(filePath).toString());
    // Stamp the CSP on every app:// response (it only takes effect on the HTML document;
    // harmless on assets) so the renderer always loads under the policy.
    const headers = new Headers(res.headers);
    headers.set("Content-Security-Policy", CONTENT_SECURITY_POLICY);
    return new Response(res.body, {
      status: res.status,
      statusText: res.statusText,
      headers,
    });
  });
}

function createWindow(): BrowserWindow {
  // 恢复上次的窗口尺寸/位置/最大化（x/y 缺省时由 OS 居中）。
  const windowState = loadWindowState();
  const mainWindow = new BrowserWindow({
    width: windowState.width,
    height: windowState.height,
    x: windowState.x,
    y: windowState.y,
    title: is.dev ? "AgentCore [DEV]" : "AgentCore",
    minWidth: 800,
    minHeight: 600,
    show: false,
    frame: false,
    icon,
    ...(process.platform === "darwin" && {
      titleBarStyle: "hidden",
      trafficLightPosition: { x: 12, y: 12 },
    }),
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      // SECURITY (XSS-003 前端XSS·渲染进程沙箱): run the renderer in the OS sandbox. The
      // preload is sandbox-compatible — it only uses contextBridge + ipcRenderer (no Node
      // built-ins / npm Node deps), so the contextBridge API surface is unchanged. With
      // contextIsolation (default-on) + nodeIntegration (default-off), this shrinks the
      // blast radius of any renderer compromise to a sandboxed process.
      sandbox: true,
    },
  });
  if (windowState.isMaximized) mainWindow.maximize();
  manageWindowState(mainWindow);
  registerWindowFrameIpc(mainWindow);

  // Dev-only: forward the renderer's console warnings/errors to this process's
  // stdout so a renderer crash (e.g. a React error-boundary stack logged via
  // console.error) shows up in the `pnpm dev` terminal, not only in DevTools.
  // Electron 35+ passes details on the event object; level is a string.
  if (is.dev) {
    mainWindow.webContents.on(
      "console-message",
      ({ level, message, lineNumber, sourceId }) => {
        if (level !== "warning" && level !== "error") return;
        const tag = level === "error" ? "renderer:error" : "renderer:warn";
        // 父终端/管道已断时 console.log 会同步抛 EPIPE——吞掉，别弹主进程错误框。
        try {
          console.log(`[${tag}] ${message} (${sourceId}:${lineNumber})`);
        } catch {
          /* ignore */
        }
      },
    );
  }

  ipcMain.on(WINDOW_CHANNELS.minimize, () => mainWindow.minimize());
  ipcMain.on(WINDOW_CHANNELS.maximize, () => {
    mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize();
  });
  ipcMain.on(WINDOW_CHANNELS.close, () => mainWindow.close());

  mainWindow.on("ready-to-show", () => {
    mainWindow.show();
  });

  // SECURITY (XSS-002 前端XSS·外链交付): only hand http/https/mailto URLs to the OS shell.
  // `shell.openExternal` launches ANY registered URI scheme (file://, ms-msdt:, custom
  // protocols — Follina-class on Windows); a target=_blank anchor carrying an attacker-
  // influenceable URL (a web-source / tool-result card URL) would otherwise let a single
  // click launch a dangerous local handler. Unsafe schemes are denied + logged.
  mainWindow.webContents.setWindowOpenHandler((details) => {
    if (isSafeExternalUrl(details.url)) {
      void shell.openExternal(details.url);
    } else {
      console.warn(
        `[security] blocked openExternal for unsafe URL scheme: ${details.url}`,
      );
    }
    return { action: "deny" };
  });

  // SECURITY (XSS-004 前端XSS·导航逃逸): the SPA is HashRouter, so legitimate route changes
  // only mutate the URL hash and never fire will-navigate with a new document URL. Any
  // will-navigate to a URL outside the trusted renderer origin (prod: app://agentcore; dev:
  // the Vite server) is an attempted navigation away from the app — block it. Outbound
  // links go through setWindowOpenHandler above, not here.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const allowedBase =
      is.dev && process.env.ELECTRON_RENDERER_URL
        ? process.env.ELECTRON_RENDERER_URL
        : APP_ORIGIN;
    if (!url.startsWith(allowedBase)) {
      event.preventDefault();
      console.warn(`[security] blocked in-page navigation to: ${url}`);
    }
  });

  if (is.dev && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadURL(`${APP_ORIGIN}/index.html`);
  }

  return mainWindow;
}

app.whenReady().then(() => {
  // Windows 通知中心需要 AppUserModelId，否则 toast 静默失败。
  if (process.platform === "win32") {
    app.setAppUserModelId("com.agentcore.desktop");
  }
  registerAppProtocol();
  registerLogIpc();
  registerFsIpc();
  registerSidecarIpc();
  registerOutboxIpc();
  registerLocalStoreIpc();
  registerTerminalIpc();
  registerProcessIpc();
  registerPtyIpc();
  registerAgentTownIpc();
  registerNotificationIpc();
  registerPreviewIpc();
  const mainWindow = createWindow();
  // 自动更新随首个窗口创建后初始化一次（IPC 句柄全局唯一，不在 createWindow 内调用，
  // 以免 macOS 上 activate 重建窗口时重复注册）。
  initUpdater(mainWindow);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
