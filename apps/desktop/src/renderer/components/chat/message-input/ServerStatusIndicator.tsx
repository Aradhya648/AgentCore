import { SimpleTooltip } from "@/components/ui/tooltip";
import { probeServerHealth } from "@/services/serverHealth";
import { useServerHealthStore } from "@/stores/serverHealth";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";

/** Offline preview (#/preview) runs with no backend, so the heartbeat never
 *  starts there — suppress the connectivity UI rather than showing a permanent
 *  "连接中…". */
function isWebPreview(): boolean {
  return typeof window !== "undefined" && window.__WEB_PREVIEW__ === true;
}

/**
 * Compact, always-present connection chip for the composer toolbar, so the user
 * knows the backend is reachable **before** sending. Quiet when connected (a
 * small dot + "已连接"), a spinner while the first probe resolves, and a clickable
 * "未连接 · 重试" that forces an immediate re-probe when offline.
 */
export function ServerStatusIndicator() {
  const status = useServerHealthStore((s) => s.status);
  const reason = useServerHealthStore((s) => s.reason);
  const justRecovered = useServerHealthStore((s) => s.justRecovered);

  useEffect(() => {
    if (!justRecovered) return;
    const t = window.setTimeout(
      () => useServerHealthStore.getState().clearRecovered(),
      3000,
    );
    return () => window.clearTimeout(t);
  }, [justRecovered]);

  if (isWebPreview()) return null;

  if (status === "checking") {
    return (
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 size={12} className="animate-spin" />
        连接中…
      </span>
    );
  }

  if (status === "offline") {
    return (
      <SimpleTooltip label={reason ?? "无法连接后端服务，点击重试"}>
        <button
          type="button"
          onClick={() => void probeServerHealth()}
          className="flex items-center gap-1.5 text-xs font-medium text-destructive hover:underline"
        >
          <span className="size-2 shrink-0 rounded-full bg-destructive" />
          未连接 · 重试
        </button>
      </SimpleTooltip>
    );
  }

  return (
    <SimpleTooltip label="已连接后端服务">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="size-2 shrink-0 rounded-full bg-success" />
        {justRecovered ? "已恢复连接" : "已连接"}
      </span>
    </SimpleTooltip>
  );
}

/**
 * Prominent inline notice above the textarea, shown only while offline — mirrors
 * the composer's "回合执行中" hint styling so the disconnected state reads as loud
 * without a modal. The heartbeat auto-recovers; the chip's button offers a manual
 * retry. N4-A: send is hard-disabled while offline (button + handleSend guard).
 */
export function ComposerConnectionNotice() {
  const status = useServerHealthStore((s) => s.status);
  if (isWebPreview() || status !== "offline") return null;
  return (
    <div
      aria-live="polite"
      className="flex items-center gap-1.5 px-4 pt-2 text-xs text-destructive"
    >
      <Loader2 size={12} className="shrink-0 animate-spin" />
      与服务器断开连接。可浏览已缓存的对话与本地文件；发送已禁用。
    </div>
  );
}
