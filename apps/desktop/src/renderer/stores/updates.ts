import { hasAutoUpdater } from "@/lib/capabilities";
import { clientVersion } from "@/lib/clientBuildInfo";
import { compareSemver, isDesktopVersionOutdated } from "@/lib/desktopVersion";
import { notifyInfo } from "@/lib/toast";
import { uiGet, uiSet } from "@/lib/uiStorage";
import { BASE_URL } from "@/services/api";
import { fetchUpdatesPolicy } from "@/services/system";
import type { UpdaterApi, UpdaterStatus } from "@shared/updater-contract";
import { create } from "zustand";

/**
 * 自动更新状态的前端落点（发布与门禁.md §7.6）。主进程权威持有状态机；发现新版本后
 * **不**自动下载——本 store 弹说明窗，用户同意后再 `download()`。订阅在应用外壳启动
 * （`startUpdates`），故说明窗 / 就绪 toast 与「关于」页状态在任何路由下都能更新。
 *
 * 另：强制更新硬闸（`outdatedMinVersion`）在启动时拉 `GET /updates/policy`，本地低于
 * `min_desktop_version` 时由 AppShell 全屏硬遮罩挡住；不可关闭，只能走更新流程。
 * 硬闸激活时 skip/snooze 无效。拉取失败 fail-open（不拦）。
 */

const PREFS_KEY = "updater-prefs";
const SNOOZE_MS = 24 * 60 * 60 * 1000;

/** Persisted skip / snooze prefs (via uiStorage → localStorage). */
export interface UpdatePrefs {
  /** Skip this version and below until a higher version appears. */
  skippedVersion?: string;
  /** Snooze auto-prompt for a specific version until `until` (epoch ms). */
  snooze?: { version: string; until: number };
}

function getUpdaterApi(): UpdaterApi | undefined {
  return typeof window !== "undefined" ? window.updaterApi : undefined;
}

export function loadUpdatePrefs(): UpdatePrefs {
  const raw = uiGet<UpdatePrefs>(PREFS_KEY);
  if (!raw || typeof raw !== "object") return {};
  const out: UpdatePrefs = {};
  if (typeof raw.skippedVersion === "string" && raw.skippedVersion.trim()) {
    out.skippedVersion = raw.skippedVersion.trim();
  }
  const snooze = raw.snooze;
  if (
    snooze &&
    typeof snooze === "object" &&
    typeof snooze.version === "string" &&
    typeof snooze.until === "number" &&
    Number.isFinite(snooze.until)
  ) {
    out.snooze = { version: snooze.version, until: snooze.until };
  }
  return out;
}

function saveUpdatePrefs(prefs: UpdatePrefs): void {
  const clean: UpdatePrefs = {};
  if (prefs.skippedVersion) clean.skippedVersion = prefs.skippedVersion;
  if (prefs.snooze) clean.snooze = prefs.snooze;
  if (!clean.skippedVersion && !clean.snooze) uiSet(PREFS_KEY, undefined);
  else uiSet(PREFS_KEY, clean);
}

/**
 * Whether an automatic prompt should open for `version`.
 * Skip: version ≤ skippedVersion. Snooze: same version within 24h window.
 * Hard force-update gate bypasses this — see {@link maybeOpenDialogForStatus}.
 */
export function shouldAutoPromptUpdate(
  version: string,
  prefs: UpdatePrefs = loadUpdatePrefs(),
  now = Date.now(),
): boolean {
  if (!version) return false;
  if (
    prefs.skippedVersion &&
    compareSemver(version, prefs.skippedVersion) <= 0
  ) {
    return false;
  }
  if (
    prefs.snooze &&
    prefs.snooze.version === version &&
    now < prefs.snooze.until
  ) {
    return false;
  }
  return true;
}

/** Fallback body when feed has no releaseNotes. */
export const UPDATE_NOTES_FALLBACK = "修复与体验改进";

/** True when the force-update hard gate is active (local below policy floor). */
export function isForceUpdateActive(
  state: { outdatedMinVersion: string | null } = useUpdatesStore.getState(),
): boolean {
  return state.outdatedMinVersion != null && state.outdatedMinVersion !== "";
}

interface UpdatesState {
  status: UpdaterStatus;
  /** Whether the update explanation dialog is open. */
  dialogOpen: boolean;
  /**
   * Force-update floor from policy when local build is older; null = no hard gate.
   * Non-null activates {@link ForceUpdateGate} (non-dismissible).
   */
  outdatedMinVersion: string | null;
  /** Open the update dialog (ignores snooze/skip — for About / force-gate CTA). */
  openUpdateDialog: () => void;
  /** Close the dialog without changing skip/snooze prefs. No-op under hard gate. */
  closeUpdateDialog: () => void;
  /**
   * 主动检查更新。手动检查后若发现可用版本会强制打开说明窗（忽略稍后提醒 /
   * 跳过偏好——用户显式点了检查）。
   */
  check: () => Promise<void>;
  /** Start downloading the available update. */
  download: () => Promise<void>;
  /** Snooze auto-prompt for current available version for 24h. No-op under hard gate. */
  remindLater: () => void;
  /** Persist skip for current available version (survives restart). No-op under hard gate. */
  skipVersion: () => void;
  /** 安装已下载的更新：退出 → 安装 → 重启。 */
  install: () => Promise<void>;
}

/** Next status push after a user-initiated check should force-open the dialog. */
let forcePromptAfterCheck = false;

export const useUpdatesStore = create<UpdatesState>(() => ({
  status: { phase: "idle" },
  dialogOpen: false,
  outdatedMinVersion: null,
  openUpdateDialog: () => {
    useUpdatesStore.setState({ dialogOpen: true });
  },
  closeUpdateDialog: () => {
    if (isForceUpdateActive()) return;
    useUpdatesStore.setState({ dialogOpen: false });
  },
  check: async () => {
    const api = getUpdaterApi();
    if (!api) return;
    forcePromptAfterCheck = true;
    try {
      await api.check();
    } catch {
      // 检查失败经主进程 'error' 状态推送呈现；此处吞掉调用层异常。
    }
  },
  download: async () => {
    const api = getUpdaterApi();
    if (!api) return;
    try {
      await api.download();
    } catch {
      /* error phase via status push */
    }
  },
  remindLater: () => {
    if (isForceUpdateActive()) return;
    const { status } = useUpdatesStore.getState();
    if (status.phase !== "available") {
      useUpdatesStore.setState({ dialogOpen: false });
      return;
    }
    const prefs = loadUpdatePrefs();
    prefs.snooze = {
      version: status.version,
      until: Date.now() + SNOOZE_MS,
    };
    saveUpdatePrefs(prefs);
    useUpdatesStore.setState({ dialogOpen: false });
  },
  skipVersion: () => {
    if (isForceUpdateActive()) return;
    const { status } = useUpdatesStore.getState();
    if (status.phase !== "available") {
      useUpdatesStore.setState({ dialogOpen: false });
      return;
    }
    const prefs = loadUpdatePrefs();
    prefs.skippedVersion = status.version;
    // Clearing snooze for this version keeps prefs tidy.
    if (prefs.snooze?.version === status.version) prefs.snooze = undefined;
    saveUpdatePrefs(prefs);
    useUpdatesStore.setState({ dialogOpen: false });
  },
  install: async () => {
    const api = getUpdaterApi();
    if (!api) return;
    await api.quitAndInstall();
  },
}));

// 已弹过「就绪」提示的版本——防同一版本在多次轮询 / 系统唤醒后重复 toast。
let notifiedVersion = "";

function maybeOpenDialogForStatus(
  status: UpdaterStatus,
  opts: { force: boolean },
): void {
  if (status.phase !== "available") return;
  const forceGate = isForceUpdateActive();
  if (opts.force || forceGate || shouldAutoPromptUpdate(status.version)) {
    useUpdatesStore.setState({ dialogOpen: true });
  }
}

/** Fail-open: fetch errors / empty min leave the hard gate hidden. Electron-only. */
async function pollOutdatedPolicy(): Promise<void> {
  if (!hasAutoUpdater()) return;
  try {
    const policy = await fetchUpdatesPolicy();
    const min = policy.minDesktopVersion;
    if (!isDesktopVersionOutdated(clientVersion(), min)) return;
    useUpdatesStore.setState({ outdatedMinVersion: min });
  } catch {
    /* fail-open — no hard gate */
  }
}

/**
 * 在应用外壳挂载时启动：同步初始状态 + 订阅推送写入 store。发现可用版本时按
 * skip/snooze 决定是否弹说明窗（硬闸激活时忽略 skip/snooze）；下载完毕弹 sticky
 * 「重启安装」（§7.6）。返回取消订阅函数。
 *
 * 非 Electron / preload 未注入 `window.updaterApi`（如纯浏览器打开 Vite 端口）时 no-op，
 * 状态置 `unsupported`，与契约「dev 态不生效」一致。
 */
export function startUpdates(): () => void {
  const api = getUpdaterApi();
  if (!api) {
    useUpdatesStore.setState({ status: { phase: "unsupported" } });
    return () => {};
  }

  // Hand the cloud API base URL to the main process (it can't read import.meta.env)
  // so the updater can poll the remote circuit breaker; this also triggers its first
  // check (发布与门禁.md §7.6).
  void api.configure(BASE_URL);

  void api.getStatus().then((status) => {
    useUpdatesStore.setState({ status });
    maybeOpenDialogForStatus(status, { force: false });
  });

  // Force-update hard gate (部署与运维.md §7.6) — Electron only; web skips.
  void pollOutdatedPolicy();

  return api.onStatus((status) => {
    useUpdatesStore.setState({ status });

    if (status.phase === "available") {
      const force = forcePromptAfterCheck;
      forcePromptAfterCheck = false;
      maybeOpenDialogForStatus(status, { force });
    } else if (status.phase !== "checking") {
      forcePromptAfterCheck = false;
    }

    if (status.phase === "downloaded" && status.version !== notifiedVersion) {
      notifiedVersion = status.version;
      notifyInfo(`新版本 ${status.version} 已就绪`, {
        description: "将在重启后安装",
        duration: Number.POSITIVE_INFINITY,
        action: {
          label: "重启安装",
          onClick: () => {
            const installApi = getUpdaterApi();
            if (installApi) void installApi.quitAndInstall();
          },
        },
      });
    }
  });
}

/** @internal vitest — reset module-level prompt flags between tests. */
export function __resetUpdatesModuleForTests(): void {
  forcePromptAfterCheck = false;
  notifiedVersion = "";
}
