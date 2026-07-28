/**
 * `workspace://` 自定义协议 —— Local Browser 工作区 HTML 字节来源（L1b）。
 *
 * 请求 `workspace://<conversationId>/<path>` → 主进程 Bearer 代理会话工作区文件端点
 * （与 preview:// 同形安全不变量：路径穿越防护 / CSP / nosniff / 权限全拒）。
 *
 * 处理器注册在 **WORKSPACE_PARTITION** session 上（≠ BROWSER_PARTITION、≠ PREVIEW_PARTITION、
 * ≠ defaultSession）。不改 `lockPreviewNavigation`。
 */

import { type Session, session } from "electron";
import { bearerFetch } from "../auth-client";
import {
  WORKSPACE_CSP,
  WORKSPACE_PARTITION,
  WORKSPACE_SCHEME,
  mimeForPath,
  normalizePreviewPath,
  workspaceFilePath,
} from "./workspace-paths";

export function workspaceBrowserSession(): Session {
  return session.fromPartition(WORKSPACE_PARTITION);
}

let protocolRegistered = false;

/**
 * 幂等：在工作区分区装 `workspace://` 处理器 + 权限全拒。
 * 首帧加载前调用（openWorkspaceHtml / registerBrowserIpc 都会调）。
 */
export function registerWorkspaceProtocol(): void {
  const sess = workspaceBrowserSession();

  sess.setPermissionRequestHandler((_wc, _permission, callback) =>
    callback(false),
  );
  sess.setPermissionCheckHandler(() => false);

  if (protocolRegistered) return;
  protocolRegistered = true;

  sess.protocol.handle(WORKSPACE_SCHEME, async (request) => {
    let url: URL;
    try {
      url = new URL(request.url);
    } catch {
      return new Response("Bad Request", { status: 400 });
    }
    const conversationId = url.hostname;
    const rel = normalizePreviewPath(url.pathname);
    if (!conversationId || !rel) {
      return new Response("Forbidden", { status: 403 });
    }

    let upstream: Response;
    try {
      upstream = await bearerFetch(workspaceFilePath(conversationId, rel));
    } catch {
      return new Response("Bad Gateway", { status: 502 });
    }
    if (!upstream.ok) {
      const status = upstream.status === 404 ? 404 : 502;
      return new Response(status === 404 ? "Not Found" : "Upstream Error", {
        status,
      });
    }

    const headers = new Headers();
    headers.set("Content-Type", mimeForPath(rel));
    headers.set("Content-Security-Policy", WORKSPACE_CSP);
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: 200, headers });
  });
}

/** 测试接缝：重置注册标记。 */
export function resetWorkspaceProtocolForTests(): void {
  protocolRegistered = false;
}
