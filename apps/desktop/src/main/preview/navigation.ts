/**
 * 预览宿主的**顶级导航锁**（安全不变量，两种宿主共用：独立子窗口 window.ts + 主窗口内嵌
 * embed.ts）。抽成单一函数，杜绝两处各写一份而漂移削弱。
 *
 * 规则（缺一不可）：
 * - 仅放行 `preview://` 顶级导航（预览页在隔离分区内自我跳转 / 相对页导航）；
 * - 其余顶级导航一律 preventDefault；安全 http/https 外链经 {@link isSafeExternalUrl} 校验后
 *   转系统浏览器（shell.openExternal），非安全 scheme 记日志并丢弃（绝不 openExternal 危险 scheme）；
 * - window.open / target=_blank 同规则处理（安全外链转 shell，其余一律 deny）——绝不放开新预览
 *   宿主逃逸。
 */

import { isSafeExternalUrl } from "@shared/safe-url";
import { type WebContents, shell } from "electron";
import { PREVIEW_SCHEME } from "./paths";

export function lockPreviewNavigation(wc: WebContents): void {
  wc.on("will-navigate", (event, target) => {
    if (target.startsWith(`${PREVIEW_SCHEME}://`)) return;
    event.preventDefault();
    if (isSafeExternalUrl(target)) {
      void shell.openExternal(target);
    } else {
      console.warn(`[preview] blocked navigation to: ${target}`);
    }
  });

  wc.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) {
      void shell.openExternal(url);
    } else {
      console.warn(`[preview] blocked window.open for: ${url}`);
    }
    return { action: "deny" };
  });
}
