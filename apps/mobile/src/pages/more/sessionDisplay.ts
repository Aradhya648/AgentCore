/**
 * Pure display helpers for the 登录设备 list (platform + UA → Chinese label,
 * ISO timestamp → relative Chinese time). Kept side-effect-free for unit tests.
 */

/** Map platform + user_agent to a short Chinese device label. */
export function formatDeviceLabel(
  platform: string | null | undefined,
  userAgent: string | null | undefined,
): string {
  const ua = userAgent ?? "";
  const plat = (platform ?? "").toLowerCase().trim();

  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  if (/Android/i.test(ua)) return "Android";

  const isWindows = /Windows/i.test(ua);
  const isMac = /Macintosh|Mac OS X/i.test(ua);
  const isLinux = /Linux/i.test(ua);

  if (plat === "desktop") {
    if (isWindows) return "Windows 桌面端";
    if (isMac) return "Mac 桌面端";
    if (isLinux) return "Linux 桌面端";
    return "桌面端";
  }

  if (plat === "mobile") return "手机端";
  if (plat === "admin") {
    if (
      isWindows ||
      isMac ||
      isLinux ||
      /Mozilla|Chrome|Safari|Firefox/i.test(ua)
    ) {
      return "管理端（网页）";
    }
    return "管理端";
  }

  if (/Mozilla|Chrome|Safari|Firefox/i.test(ua)) return "网页";

  const raw = platform?.trim();
  if (raw) return raw;
  return "未知设备";
}

/** Format an ISO timestamp as a short Chinese relative time. */
export function formatRelativeTime(iso: string, nowMs = Date.now()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const sec = Math.max(0, Math.floor((nowMs - t) / 1000));
  if (sec < 60) return "刚刚";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  const month = Math.floor(day / 30);
  if (month < 12) return `${month} 个月前`;
  const year = Math.floor(day / 365);
  return `${year} 年前`;
}
