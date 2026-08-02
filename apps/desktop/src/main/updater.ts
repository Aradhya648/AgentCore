import { UPDATER_CHANNELS, type UpdaterStatus } from "@shared/updater-contract";
import { net, type BrowserWindow, app, ipcMain, powerMonitor } from "electron";
import { type UpdateInfo, autoUpdater } from "electron-updater";

// 检查频率（发布与门禁.md §7.6）：启动 + 每 4h + 系统唤醒。
const CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000;

let mainWindow: BrowserWindow | null = null;
let status: UpdaterStatus = { phase: "idle" };
// 下载中的目标版本：download-progress 事件不带版本，从 update-available 暂存补上。
let pendingVersion = "";
let intervalTimer: ReturnType<typeof setInterval> | null = null;
// 云 API 基址，由 renderer 经 `configure` 传入（它是 API 地址单一源）；null = 尚未配置。
let apiBaseUrl: string | null = null;
// 检查调度只起一次——在收到 API 基址后启动，确保首检也过远程熔断闸。
let scheduleStarted = false;
// 防重复点「立即更新」并发起多次 downloadUpdate。
let downloadInFlight = false;

function pushStatus(next: UpdaterStatus): void {
  status = next;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(UPDATER_CHANNELS.status, next);
  }
}

/** Normalize electron-updater releaseNotes (string | note list) to plain text. */
function normalizeReleaseNotes(info: UpdateInfo): string | null {
  const raw = info.releaseNotes;
  if (raw == null) return null;
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (Array.isArray(raw)) {
    const parts: string[] = [];
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const note = (item as { note?: string | null }).note;
      if (typeof note === "string" && note.trim()) parts.push(note.trim());
    }
    return parts.length > 0 ? parts.join("\n\n") : null;
  }
  return null;
}

/** Sum package file sizes from UpdateInfo when present. */
function packageSizeBytes(info: UpdateInfo): number | null {
  const files = info.files;
  if (!Array.isArray(files) || files.length === 0) return null;
  let total = 0;
  let any = false;
  for (const f of files) {
    const size = (f as { size?: number }).size;
    if (typeof size === "number" && Number.isFinite(size) && size > 0) {
      total += size;
      any = true;
    }
  }
  return any ? total : null;
}

/**
 * 远程熔断查询（发布与门禁.md §7.6, 部署与运维.md §7.9）：检查前查后端策略
 * `GET /updates/policy`，`enabled:false` 即暂停下载（坏版本急停闸）。**fail-open**——
 * 未配置基址 / 非 200 / 网络错一律视为放行（已发布的安全网络要保活，与特性开关的
 * fail-safe 刻意相反）。完整灰度 / 双通道仍依赖 §7.9 特性开关，未在此消费。
 */
async function updatesEnabled(): Promise<boolean> {
  if (!apiBaseUrl) return true;
  try {
    const res = await net.fetch(`${apiBaseUrl}/updates/policy`);
    if (!res.ok) return true;
    const policy = (await res.json()) as { enabled?: boolean };
    return policy.enabled !== false;
  } catch {
    return true;
  }
}

async function runCheck(): Promise<void> {
  if (!(await updatesEnabled())) return;
  try {
    await autoUpdater.checkForUpdates();
  } catch {
    // 网络等失败也会经 'error' 事件推状态；这里吞掉 reject 防未处理的 promise 异常。
  }
}

async function runDownload(): Promise<void> {
  if (downloadInFlight) return;
  if (status.phase !== "available" && status.phase !== "error") return;
  downloadInFlight = true;
  try {
    await autoUpdater.downloadUpdate();
  } catch {
    // 失败经 'error' 事件推状态。
  } finally {
    downloadInFlight = false;
  }
}

/** 启动检查调度（仅一次）：立即首检 + 每 4h + 系统唤醒（§7.6）。 */
function startSchedule(): void {
  if (scheduleStarted) return;
  scheduleStarted = true;
  void runCheck();
  intervalTimer = setInterval(() => void runCheck(), CHECK_INTERVAL_MS);
  powerMonitor.on("resume", () => void runCheck());
}

/**
 * 初始化自动更新。**始终**注册 IPC 句柄（renderer 不会命中缺通道）；仅打包态接入
 * electron-updater 与检查调度，dev / 未打包态状态恒为 `unsupported`。
 *
 * 只应调用一次（IPC 句柄全局唯一）——在 `app.whenReady` 里随首个窗口创建后调用。
 */
export function initUpdater(window: BrowserWindow): void {
  mainWindow = window;

  ipcMain.handle(UPDATER_CHANNELS.getStatus, () => status);

  if (!app.isPackaged) {
    status = { phase: "unsupported" };
    ipcMain.handle(UPDATER_CHANNELS.configure, () => {});
    ipcMain.handle(UPDATER_CHANNELS.check, () => {});
    ipcMain.handle(UPDATER_CHANNELS.download, () => {});
    ipcMain.handle(UPDATER_CHANNELS.quitAndInstall, () => {});
    return;
  }

  // 发现即说明、用户同意后再下载；安装仍须显式 quitAndInstall（§7.6）。
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;

  autoUpdater.on("checking-for-update", () =>
    pushStatus({ phase: "checking" }),
  );
  autoUpdater.on("update-available", (info) => {
    pendingVersion = info.version;
    pushStatus({
      phase: "available",
      version: info.version,
      releaseNotes: normalizeReleaseNotes(info),
      sizeBytes: packageSizeBytes(info),
    });
  });
  autoUpdater.on("update-not-available", () =>
    pushStatus({ phase: "not-available" }),
  );
  autoUpdater.on("download-progress", (progress) =>
    pushStatus({
      phase: "downloading",
      version: pendingVersion,
      percent: Math.round(progress.percent),
      bytesPerSecond: Math.max(0, Math.round(progress.bytesPerSecond || 0)),
      transferred: Math.max(0, Math.round(progress.transferred || 0)),
      total: Math.max(0, Math.round(progress.total || 0)),
    }),
  );
  autoUpdater.on("update-downloaded", (info) =>
    pushStatus({ phase: "downloaded", version: info.version }),
  );
  autoUpdater.on("error", (err) =>
    pushStatus({ phase: "error", message: err?.message ?? "更新检查失败" }),
  );

  // renderer 传入 API 基址后才启动调度——确保首次检查也先过远程熔断闸（fail-open）。
  ipcMain.handle(UPDATER_CHANNELS.configure, (_e, baseUrl: unknown) => {
    // IPC-004（第五轮 IPC 权限面审计）：边界结构校验——非 string 基址直接忽略（renderer 是
    // API 地址单一源，畸形仅可能来自被攻破的 renderer）。不抛：configure 契约为 Promise<void>。
    if (typeof baseUrl !== "string") return;
    apiBaseUrl = baseUrl;
    startSchedule();
  });
  ipcMain.handle(UPDATER_CHANNELS.check, () => runCheck());
  ipcMain.handle(UPDATER_CHANNELS.download, () => runDownload());
  ipcMain.handle(UPDATER_CHANNELS.quitAndInstall, () => {
    // isSilent=false：显示安装进度；isForceRunAfter=true：装毕重启应用。
    autoUpdater.quitAndInstall(false, true);
  });

  app.on("before-quit", () => {
    if (intervalTimer) {
      clearInterval(intervalTimer);
      intervalTimer = null;
    }
  });
}
