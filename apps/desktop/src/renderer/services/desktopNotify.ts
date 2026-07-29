import { fulfillClientToolOnce } from "@/services/clientToolFulfill";
import type { DesktopNotifyRequiredPayload } from "@/types/events";

/**
 * Desktop half of the ``desktop_notify`` client-tool channel.
 *
 * After the user approves the GRANTABLE tool call, the server suspends and streams
 * ``desktop_notify_required``; we show an OS notification and settle the paused op
 * over the unified interaction bridge (kind ``client_tool``). Same ``request_id``
 * is de-duplicated in-process so attach rehang does not re-show the notification.
 */
export async function performDesktopNotify(
  payload: DesktopNotifyRequiredPayload,
  conversationId: string,
): Promise<void> {
  await fulfillClientToolOnce({
    requestId: payload.request_id,
    conversationId,
    logLabel: "desktopNotify",
    perform: () => runDesktopNotify(payload, conversationId),
  });
}

type ClientToolResult =
  | { ok: true; value: { shown: true } }
  | { ok: false; error: { kind: string; detail: string } };

async function runDesktopNotify(
  payload: DesktopNotifyRequiredPayload,
  conversationId: string,
): Promise<ClientToolResult> {
  const api =
    typeof window !== "undefined" ? window.notificationApi : undefined;
  if (!api?.show) {
    return {
      ok: false,
      error: {
        kind: "DesktopNotifyError",
        detail: "非桌面环境，无法显示系统通知",
      },
    };
  }
  try {
    const result = await api.show({
      title: payload.title,
      body: payload.body ?? "",
      conversationId,
    });
    if (!result.ok) {
      return {
        ok: false,
        error: { kind: "DesktopNotifyError", detail: result.reason },
      };
    }
    return { ok: true, value: { shown: true } };
  } catch (e) {
    return {
      ok: false,
      error: {
        kind: "DesktopNotifyError",
        detail: e instanceof Error ? e.message : String(e),
      },
    };
  }
}
