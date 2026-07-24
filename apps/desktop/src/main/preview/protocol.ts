/**
 * `preview://` 自定义协议处理器 —— 预览子窗口的字节来源。
 *
 * 请求 `preview://<conversationId>/<path>` → 主进程以 Bearer 代理后端「会话工作区文件」
 * 端点取字节（token 只在主进程读 cookie 罐，credentials:"omit"，401 刷新重试；见
 * auth-client），按扩展名推断 MIME 后 **inline** 返回，并下发独立 CSP。严格限定在该会话
 * 工作区内（路径穿越防护见 paths.normalizePreviewPath）。
 *
 * 处理器注册在**独立非持久分区**（PREVIEW_PARTITION）的 session 上，而非 defaultSession——
 * 主窗口所在的 defaultSession 没有该 scheme 的处理器，无法加载 preview://（隔离）。
 */

import { type Session, session } from "electron";
import { bearerFetch } from "../auth-client";
import {
  PREVIEW_CSP,
  PREVIEW_PARTITION,
  PREVIEW_SCHEME,
  mimeForPath,
  normalizePreviewPath,
  workspaceFilePath,
} from "./paths";

/** 预览宿主的独立会话（非持久分区；绝不触碰 defaultSession 的登录 cookie）。 */
export function previewSession(): Session {
  return session.fromPartition(PREVIEW_PARTITION);
}

let protocolRegistered = false;

/**
 * 幂等：在预览分区 session 上装 `preview://` 处理器，并把该分区权限全拒（预览页绝不
 * 可申请摄像头 / 麦克风 / 地理位置 / 通知 / 剪贴板等）。首帧加载前调用（openPreviewWindow
 * 与 registerPreviewIpc 都会调，重复调用安全）。
 */
export function registerPreviewProtocol(): void {
  const sess = previewSession();

  // 权限全拒（请求式 + 检查式双管）——AI 生成页面永远拿不到设备/敏感权限。
  sess.setPermissionRequestHandler((_wc, _permission, callback) =>
    callback(false),
  );
  sess.setPermissionCheckHandler(() => false);

  if (protocolRegistered) return;
  protocolRegistered = true;

  sess.protocol.handle(PREVIEW_SCHEME, async (request) => {
    let url: URL;
    try {
      url = new URL(request.url);
    } catch {
      return new Response("Bad Request", { status: 400 });
    }
    const conversationId = url.hostname;
    const rel = normalizePreviewPath(url.pathname);
    // 路径穿越防护 / 缺会话 → 403（越界条目在此被拒，绝不落到后端）。
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
    headers.set("Content-Security-Policy", PREVIEW_CSP);
    // MIME 完全由扩展名决定 → 关掉浏览器嗅探，杜绝「.txt 被当 HTML 执行」类混淆。
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: 200, headers });
  });
}

/** 测试接缝：重置注册标记（单测里可重新装处理器）。 */
export function resetPreviewProtocolForTests(): void {
  protocolRegistered = false;
}
