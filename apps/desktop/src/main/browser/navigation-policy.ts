/**
 * LocalChromiumHost 导航 URL 判定（纯函数，无 electron）——可单测。
 * 挂锁见 navigation.ts。
 */

import { isWorkspaceBrowserUrl } from "./workspace-paths";

/** 空白页初始地址（未导航前 WebContents 占位）。 */
export const LOCAL_BROWSER_BLANK = "about:blank";

/**
 * 外网页模式：是否允许在本机浏览器壳内加载该 URL（顶级导航 / loadURL 前置）。
 * `about:blank` 仅用于空页占位；业务导航须为 http(s)。
 */
export function isAllowedWebBrowserUrl(url: string): boolean {
  if (typeof url !== "string" || url.trim() === "") return false;
  const trimmed = url.trim();
  if (trimmed === LOCAL_BROWSER_BLANK || trimmed.startsWith("about:blank?")) {
    return true;
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return false;
  }
  const protocol = parsed.protocol.toLowerCase();
  return protocol === "http:" || protocol === "https:";
}

/**
 * 工作区 HTML 模式：仅放行 `workspace://` 与空页占位（相对页在同 scheme 内跳转）。
 * 不放行 http(s) 顶级进同 partition（外链由 navigation 锁转 shell / 拒）。
 */
export function isAllowedWorkspaceBrowserUrl(url: string): boolean {
  if (typeof url !== "string" || url.trim() === "") return false;
  const trimmed = url.trim();
  if (trimmed === LOCAL_BROWSER_BLANK || trimmed.startsWith("about:blank?")) {
    return true;
  }
  return isWorkspaceBrowserUrl(trimmed);
}

/**
 * 任一模式允许的壳内 URL（策略测 / 兼容旧名）。
 * = 外网页 http(s)|blank ∪ 工作区 workspace://|blank。
 */
export function isAllowedLocalBrowserUrl(url: string): boolean {
  return isAllowedWebBrowserUrl(url) || isWorkspaceBrowserUrl(url);
}

/**
 * Bridge navigate 入参 → 页模式（纯函数）。
 * ``null`` = 不可导航（非 http(s)/workspace://）。
 */
export function resolveBridgeNavigateKind(
  url: string,
): "web" | "workspace" | null {
  const trimmed = typeof url === "string" ? url.trim() : "";
  if (!trimmed || !isNavigableLocalBrowserUrl(trimmed)) return null;
  return isWorkspaceBrowserUrl(trimmed) ? "workspace" : "web";
}

/**
 * 用户地址栏 / Bridge navigate 入参：http(s) 或 workspace://（不含 about:blank）。
 */
export function isNavigableLocalBrowserUrl(url: string): boolean {
  if (typeof url !== "string" || url.trim() === "") return false;
  if (isWorkspaceBrowserUrl(url.trim())) return true;
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return false;
  }
  const protocol = parsed.protocol.toLowerCase();
  return protocol === "http:" || protocol === "https:";
}
