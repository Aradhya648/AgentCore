/**
 * LocalChromiumHost **顶级导航策略**（新模块 —— 禁止改 preview/navigation.lockPreviewNavigation）。
 *
 * 两种页模式（L1b 分 partition，锁也分）：
 * - **web**：仅放行 `http:` / `https:` 与 `about:blank`；`window.open` → deny；
 * - **workspace**：仅放行 `workspace://` 与 `about:blank`；安全 http(s) 外链转
 *   `shell.openExternal`（与旧 preview 外链行为同形，**不经** lockPreviewNavigation）；
 *   其余拒；`window.open` 同规则。
 *
 * 下载默认拒绝（见 {@link attachLocalBrowserDownloadGuard}，L1）。
 * URL 判定纯函数见 navigation-policy.ts。
 */

import { isSafeExternalUrl } from "@shared/safe-url";
import { type Session, type WebContents, shell } from "electron";
import {
  isAllowedWebBrowserUrl,
  isAllowedWorkspaceBrowserUrl,
} from "./navigation-policy";

export type LocalBrowserNavMode = "web" | "workspace";

export {
  LOCAL_BROWSER_BLANK,
  isAllowedLocalBrowserUrl,
  isAllowedWebBrowserUrl,
  isAllowedWorkspaceBrowserUrl,
  isNavigableLocalBrowserUrl,
  resolveBridgeNavigateKind,
} from "./navigation-policy";

/**
 * 给 WebContents 挂导航锁（创建视图时按 partition 模式调用一次）。
 */
export function lockLocalBrowserNavigation(
  wc: WebContents,
  mode: LocalBrowserNavMode = "web",
): void {
  if (mode === "workspace") {
    lockWorkspaceBrowserNavigation(wc);
    return;
  }

  wc.on("will-navigate", (event, target) => {
    if (isAllowedWebBrowserUrl(target)) return;
    event.preventDefault();
    console.warn(`[browser] blocked navigation to: ${target}`);
  });

  wc.setWindowOpenHandler(({ url }) => {
    console.warn(`[browser] denied window.open for: ${url}`);
    return { action: "deny" };
  });
}

function lockWorkspaceBrowserNavigation(wc: WebContents): void {
  wc.on("will-navigate", (event, target) => {
    if (isAllowedWorkspaceBrowserUrl(target)) return;
    event.preventDefault();
    if (isSafeExternalUrl(target)) {
      void shell.openExternal(target);
    } else {
      console.warn(`[browser/workspace] blocked navigation to: ${target}`);
    }
  });

  wc.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) {
      void shell.openExternal(url);
    } else {
      console.warn(`[browser/workspace] denied window.open for: ${url}`);
    }
    return { action: "deny" };
  });
}

const downloadGuardedSessions = new WeakSet<Session>();

/** 默认拒绝下载（L1）；同一 session 只挂一次。 */
export function attachLocalBrowserDownloadGuard(sess: Session): void {
  if (downloadGuardedSessions.has(sess)) return;
  downloadGuardedSessions.add(sess);
  sess.on("will-download", (event) => {
    event.preventDefault();
    console.warn("[browser] download denied (L1 default)");
  });
}
