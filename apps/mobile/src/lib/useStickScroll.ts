import {
  distanceFromBottom,
  isScrollUpTouch,
  isScrollUpWheel,
  nextStickState,
} from "@/lib/stickScroll";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

/**
 * Keeps a transcript pinned to the newest content without hijacking the user's
 * reading. Sticks while near the bottom; an upward touch/wheel detaches
 * immediately (so streaming / polled appends cannot yank the viewport back);
 * hysteresis governs position-based re-attach. A change of `resetKey` re-sticks.
 *
 * Optional prepend anchor: call {@link preparePrepend} before inserting older
 * rows above the fold; the next `contentKey` layout pass restores the prior
 * distance-from-bottom so the viewport does not jump.
 */
export function useStickScroll(contentKey: string, resetKey: string | null) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const touchYRef = useRef<number | null>(null);
  /** Distance from bottom captured before an older-page prepend. */
  const prependAnchorRef = useRef<number | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  const applyStick = useCallback((stuck: boolean) => {
    stickRef.current = stuck;
    setAtBottom(stuck);
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  const jumpToBottom = useCallback(() => {
    applyStick(true);
    scrollToBottom("auto");
  }, [applyStick, scrollToBottom]);

  /** Capture distance-from-bottom before prepending older messages. */
  const preparePrepend = useCallback(() => {
    const el = scrollRef.current;
    prependAnchorRef.current = el ? el.scrollHeight - el.scrollTop : 0;
  }, []);

  /** Drop a pending prepend anchor (e.g. older-page fetch failed). */
  const cancelPrepend = useCallback(() => {
    prependAnchorRef.current = null;
  }, []);

  // Position + upward gesture: detach on intent, hysteresis on scroll position.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      applyStick(nextStickState(stickRef.current, distanceFromBottom(el)));
    };

    const onWheel = (e: WheelEvent) => {
      if (isScrollUpWheel(e.deltaY) && stickRef.current) {
        applyStick(false);
      }
    };

    const onTouchStart = (e: TouchEvent) => {
      touchYRef.current = e.touches[0]?.clientY ?? null;
    };

    const onTouchMove = (e: TouchEvent) => {
      const y = e.touches[0]?.clientY;
      const prev = touchYRef.current;
      if (y == null || prev == null) return;
      if (isScrollUpTouch(prev, y) && stickRef.current) {
        applyStick(false);
      }
      touchYRef.current = y;
    };

    const onTouchEnd = () => {
      touchYRef.current = null;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });
    el.addEventListener("touchcancel", onTouchEnd, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [applyStick]);

  // New content / prepend settle: restore anchor, or follow only while stuck.
  // biome-ignore lint/correctness/useExhaustiveDependencies: contentKey is an intentional re-run key
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (prependAnchorRef.current != null) {
      el.scrollTop = el.scrollHeight - prependAnchorRef.current;
      prependAnchorRef.current = null;
      return;
    }
    if (stickRef.current) {
      scrollToBottom("auto");
    } else {
      // Detached: keep 回到底部 visible until jump / re-attach.
      setAtBottom(false);
    }
  }, [contentKey, scrollToBottom]);

  // Context switch: always re-stick and land on the latest item.
  // biome-ignore lint/correctness/useExhaustiveDependencies: resetKey is an intentional re-run key
  useLayoutEffect(() => {
    applyStick(true);
    prependAnchorRef.current = null;
    scrollToBottom("auto");
  }, [resetKey, applyStick, scrollToBottom]);

  return { scrollRef, atBottom, jumpToBottom, preparePrepend, cancelPrepend };
}
