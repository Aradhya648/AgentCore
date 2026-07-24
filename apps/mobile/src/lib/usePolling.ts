// Visibility-aware polling for the REST-only domains (人际 IM has no SSE, so the chat
// list + open thread refresh on an interval). Calls `fn` immediately, then every
// `intervalMs` while the tab is visible, and once more whenever it regains visibility
// (so a backgrounded app catches up on resume instead of waiting a full interval).
import { useEffect, useRef } from "react";

export function usePolling(
  fn: () => void | Promise<void>,
  intervalMs: number,
  enabled = true,
): void {
  const saved = useRef(fn);
  saved.current = fn;

  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      if (!document.hidden) void saved.current();
    };
    tick();
    const timer = window.setInterval(tick, intervalMs);
    const onVisible = () => {
      if (!document.hidden) void saved.current();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, enabled]);
}
