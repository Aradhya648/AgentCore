/**
 * `workspace://` 自定义协议 —— Local Browser 工作区 HTML 字节来源（L1b）。
 *
 * 请求 `workspace://<conversationId>/<path>` → 主进程 Bearer 代理会话工作区文件端点
 * （与 preview:// 同形安全不变量：路径穿越防护 / CSP / nosniff / 权限全拒）。
 *
 * 处理器按 **conversation 分区** 注册（`workspacePartitionFor(cid)`）；
 * URL host **必须等于**该 partition 绑定的 cid，否则 403（防跨对话灌 HTML）。
 */

import { type Session, session } from "electron";
import { bearerFetch } from "../auth-client";
import { normalizeBrowserConversationId } from "./paths";
import {
  WORKSPACE_CSP,
  WORKSPACE_SCHEME,
  mimeForPath,
  resolveWorkspaceProtocolRequest,
  workspaceFilePath,
  workspacePartitionFor,
} from "./workspace-paths";

/** 已注册协议处理器的 partition 名（幂等）。 */
const registeredPartitions = new Set<string>();

export function workspaceBrowserSessionFor(conversationId: string): Session {
  return session.fromPartition(workspacePartitionFor(conversationId));
}

export { resolveWorkspaceProtocolRequest };

/**
 * 幂等：在指定对话的工作区分区装 `workspace://` 处理器 + 权限全拒。
 * 建 workspace 页前调用。
 */
export function registerWorkspaceProtocolFor(conversationId: string): void {
  const cid = normalizeBrowserConversationId(conversationId);
  if (!cid) return;
  const partition = workspacePartitionFor(cid);
  const sess = session.fromPartition(partition);

  sess.setPermissionRequestHandler((_wc, _permission, callback) =>
    callback(false),
  );
  sess.setPermissionCheckHandler(() => false);

  if (registeredPartitions.has(partition)) return;
  registeredPartitions.add(partition);

  sess.protocol.handle(WORKSPACE_SCHEME, async (request) => {
    const resolved = resolveWorkspaceProtocolRequest(request.url, cid);
    if (!resolved.ok) {
      return new Response(
        resolved.status === 400 ? "Bad Request" : "Forbidden",
        { status: resolved.status },
      );
    }

    let upstream: Response;
    try {
      upstream = await bearerFetch(
        workspaceFilePath(resolved.conversationId, resolved.rel),
      );
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
    headers.set("Content-Type", mimeForPath(resolved.rel));
    headers.set("Content-Security-Policy", WORKSPACE_CSP);
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: 200, headers });
  });
}

/** @deprecated 首期按 cid 注册；无 cid 时 no-op（勿挂全局 partition）。 */
export function registerWorkspaceProtocol(): void {
  /* intentionally empty — callers must use registerWorkspaceProtocolFor(cid) */
}

/** 测试接缝：重置注册标记。 */
export function resetWorkspaceProtocolForTests(): void {
  registeredPartitions.clear();
}
