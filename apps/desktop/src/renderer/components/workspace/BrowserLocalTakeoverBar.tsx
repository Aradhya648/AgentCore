/**
 * Local 浏览器内容路径的接管条（非 Live 帧面）。
 *
 * 语义 = POST …/browser/takeover 打 registry mark（`user_in_control`），用户仍直接操作本机
 * WebContents——不挂帧捕获、不注入 CDP input。有 `sessionId` 才挂本组件（D8 随时可接管）。
 */
import { conversationHasPendingBrowserLogin } from "@/lib/browserActivity";
import {
  endBrowserTakeover,
  startBrowserTakeover,
  takeoverStartErrorMessage,
} from "@/services/browserTakeover";
import { useBrowserTakeoverStore } from "@/stores/browserTakeover";
import { useConversationStore } from "@/stores/conversation";
import { runtimeOf } from "@/stores/conversation/runtime";
import { useExecutionStore } from "@/stores/execution";
import { Hand, Loader2, MonitorOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

type TakeoverPhase = "idle" | "starting" | "active" | "ending";

export function BrowserLocalTakeoverBar({
  conversationId,
  sessionId,
}: {
  conversationId: string;
  sessionId: string;
}) {
  const [takeover, setTakeover] = useState<TakeoverPhase>("idle");
  const [takeoverError, setTakeoverError] = useState<string | null>(null);
  const [returnHint, setReturnHint] = useState(false);
  const pendingBrowserLogin = useExecutionStore((s) =>
    conversationHasPendingBrowserLogin(
      runtimeOf(useConversationStore.getState(), conversationId).messages,
      s.byId,
    ),
  );

  const takeoverActiveRef = useRef(false);
  const takeoverStartRef = useRef<string | null>(null);

  const endTakeoverCore = useCallback(() => {
    if (!takeoverActiveRef.current) return;
    const startedAt = takeoverStartRef.current;
    takeoverActiveRef.current = false;
    takeoverStartRef.current = null;
    void endBrowserTakeover(conversationId, { sessionId }).catch(() => {});
    if (startedAt) {
      useBrowserTakeoverStore
        .getState()
        .addLocal(conversationId, startedAt, new Date().toISOString());
    }
  }, [conversationId, sessionId]);

  const returnControl = useCallback(
    (opts?: { showReturnHint?: boolean }) => {
      if (!takeoverActiveRef.current) return;
      setTakeover("ending");
      endTakeoverCore();
      setTakeover("idle");
      setTakeoverError(null);
      if (opts?.showReturnHint) setReturnHint(true);
    },
    [endTakeoverCore],
  );

  const beginTakeover = useCallback(async () => {
    setTakeoverError(null);
    setReturnHint(false);
    setTakeover("starting");
    try {
      await startBrowserTakeover(conversationId, { sessionId });
      takeoverStartRef.current = new Date().toISOString();
      takeoverActiveRef.current = true;
      setTakeover("active");
    } catch (err) {
      setTakeover("idle");
      setTakeoverError(takeoverStartErrorMessage(err));
    }
  }, [conversationId, sessionId]);

  // 换页 / 卸载 → 尽力 end（幂等）。
  useEffect(() => {
    return () => endTakeoverCore();
  }, [endTakeoverCore]);

  const isTakingOver = takeover === "active" || takeover === "ending";

  return (
    <>
      {isTakingOver ? (
        <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-primary/30 bg-primary/10 px-3 text-xs">
          <Hand size={13} className="shrink-0 text-primary" />
          <span className="font-medium text-primary">
            接管中 · 你正在操作浏览器
          </span>
          <button
            type="button"
            onClick={() => returnControl({ showReturnHint: true })}
            className="ml-auto shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            归还控制
          </button>
        </div>
      ) : (
        <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border px-3 text-xs">
          <Hand size={13} className="shrink-0 text-muted-foreground/50" />
          <span className="text-muted-foreground">本机浏览器</span>
          {takeover === "starting" ? (
            <span className="ml-auto flex shrink-0 items-center gap-1 text-muted-foreground">
              <Loader2 size={12} className="animate-spin" /> 正在接管…
            </span>
          ) : (
            <button
              type="button"
              onClick={() => void beginTakeover()}
              className="ml-auto flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/15"
            >
              <Hand size={12} className="shrink-0" />
              接管
            </button>
          )}
        </div>
      )}

      {takeoverError && (
        <div className="flex shrink-0 items-center gap-1.5 border-b border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
          <MonitorOff size={13} className="shrink-0" />
          {takeoverError}
        </div>
      )}

      {returnHint && !takeoverError && (
        <div className="flex shrink-0 items-center gap-1.5 border-b border-primary/20 bg-primary/5 px-3 py-1.5 text-xs text-foreground">
          <Hand size={13} className="shrink-0 text-primary" />
          {pendingBrowserLogin
            ? "登录完成后，回到对话点「已登录，继续」"
            : "控制已归还"}
        </div>
      )}
    </>
  );
}
