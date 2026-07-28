/**
 * 对话侧栏「完整预览」落点：右坞 BrowserPanel 内一页加载工作区 HTML（M3a）。
 * 不再走 sidePanel.openPreview / PREVIEW_TAB。
 */

import { baseName } from "@/lib/fileSource";
import { useBrowserSessionsStore } from "@/stores/browserSessions";
import { useSidePanelStore } from "@/stores/sidePanel";

/**
 * 打开浏览器壳并在新页加载会话工作区 HTML（桌面 browserApi.openWorkspaceHtml）。
 * 失败抛错供 UI toast。
 */
export async function openWorkspaceHtmlInBrowser(
  conversationId: string,
  path: string,
): Promise<void> {
  const open = window.browserApi?.openWorkspaceHtml;
  if (!open) throw new Error("此环境不支持应用内预览");

  const pageId = useBrowserSessionsStore.getState().createPage({
    conversationId,
    url: "",
    title: baseName(path) || "预览",
    hostKind: "local",
  });
  useSidePanelStore.getState().showBrowser();

  const result = await open({ pageId, conversationId, path });
  if (!result.ok) throw new Error(result.reason);
}
