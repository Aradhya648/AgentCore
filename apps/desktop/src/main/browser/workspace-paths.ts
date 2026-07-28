/**
 * 本机浏览器「工作区 HTML」协议的**纯逻辑**（L1b 第二非持久 partition）。
 *
 * 与外网页 {@link BROWSER_PARTITION}、旧预览 {@link PREVIEW_PARTITION} **三分立**：
 * 不共用 session，防 cookie 串到产物页。路径守卫 / MIME / CSP 复用 preview/paths
 * （安全不变量不得削弱）；本文件只换 scheme + partition 名。
 */

import {
  PREVIEW_CSP,
  mimeForPath,
  normalizePreviewPath,
  workspaceFilePath,
} from "../preview/paths";

export const WORKSPACE_SCHEME = "workspace";

/**
 * 工作区 HTML 宿主所用的**非持久独立分区**（无 `persist:`）。
 * ≠ `agentcore-browser`（外网 http(s)）、≠ `agentcore-preview`（旧预览 tab/子窗）。
 */
export const WORKSPACE_PARTITION = "agentcore-browser-workspace";

/** 与预览相同的纵深 CSP（sandbox + 独立分区已是边界）。 */
export const WORKSPACE_CSP = PREVIEW_CSP;

export {
  mimeForPath,
  normalizePreviewPath,
  workspaceFilePath,
};

/**
 * 构造要在本机浏览器工作区页里加载的 `workspace://` URL。
 * 会话 id 作 host（小写 UUID）；路径经 {@link normalizePreviewPath} 守卫后逐段编码。
 */
export function buildWorkspaceUrl(conversationId: string, path: string): string {
  const host = conversationId.trim().toLowerCase();
  const rel = normalizePreviewPath(path);
  const encoded = rel
    ? rel.split("/").map(encodeURIComponent).join("/")
    : "";
  return `${WORKSPACE_SCHEME}://${host}/${encoded}`;
}

/** 是否本机浏览器允许的工作区协议 URL。 */
export function isWorkspaceBrowserUrl(url: string): boolean {
  if (typeof url !== "string" || url.trim() === "") return false;
  try {
    return new URL(url.trim()).protocol.toLowerCase() === `${WORKSPACE_SCHEME}:`;
  } catch {
    return false;
  }
}
