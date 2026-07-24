/**
 * Derive a short Chinese device label from session `platform` + raw `user_agent`.
 * Best-effort heuristics only — unknown shapes fall back to the platform string.
 */
export function sessionDeviceLabel(
  platform: string | null | undefined,
  userAgent: string | null | undefined,
): string {
  const ua = userAgent ?? "";
  const p = (platform ?? "").trim().toLowerCase();

  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  if (/Android/i.test(ua)) return "Android";

  if (p === "admin") return "管理后台";

  // Plain browser (no Electron / Capacitor) → 网页, even when platform=desktop.
  if (looksLikeWebBrowser(ua)) return "网页";

  if (p === "mobile") return "移动端";

  if (p === "desktop" || isDesktopShell(ua)) {
    if (/Windows/i.test(ua)) return "Windows 桌面端";
    if (/Mac OS X|Macintosh/i.test(ua)) return "macOS 桌面端";
    if (/Linux/i.test(ua)) return "Linux 桌面端";
    if (p === "desktop") return "桌面端";
  }

  if (platform?.trim()) return platform.trim();
  return "未知设备";
}

function isDesktopShell(ua: string): boolean {
  return /Electron/i.test(ua);
}

/** Browser UA without Electron / Capacitor — treat as web client. */
function looksLikeWebBrowser(ua: string): boolean {
  if (!ua) return false;
  if (/Electron|Capacitor/i.test(ua)) return false;
  return /(Chrome|Firefox|Safari|Edg)\//i.test(ua);
}

/** Relative last-active phrasing for session rows (中文). */
export function sessionLastActiveLabel(
  iso: string,
  nowMs: number = Date.now(),
): string {
  const ms = nowMs - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "刚刚";
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const d = Math.floor(hr / 24);
  return `${d} 天前`;
}
