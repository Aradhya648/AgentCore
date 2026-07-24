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
 * reading. The view sticks while near the bottom; an upward wheel/touch detaches
 * immediately (so streaming cannot yank the viewport back), and hysteresis keeps
 * re-attach from flickering at the band edge. A change of `resetKey` re-sticks.
 *
 * Auto-follow uses instant scrolling (a smooth animation can't keep pace with a
 * fast token stream and fights the scroll listener); the manual jump can afford
 * to be instant too.
 *
 * Shared by the IM 消息 thread (ChatThread). AI 对话 uses {@link useChatScroll},
 * which applies the same stick helpers plus bidirectional windowing.
 */
export function useStickToBottom(contentKey: string, resetKey: string | null) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const touchYRef = useRef<number | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  const applyStick = useCallback((stuck: boolean) => {
    stickRef.current = stuck;
    setAtBottom(stuck);
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  const jumpToBottom = useCallback(() => {
    applyStick(true);
    scrollToBottom("auto");
  }, [applyStick, scrollToBottom]);

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

  // New content (streaming tokens / new message): follow only while stuck;
  // otherwise just refresh the button state since the gap to the bottom grew.
  // biome-ignore lint/correctness/useExhaustiveDependencies: contentKey is an intentional re-run key; the helpers it pairs with are stable.
  useLayoutEffect(() => {
    if (stickRef.current) scrollToBottom("auto");
    // Detached on purpose: keep the 回到底部 affordance visible until the user
    // scrolls back into the attach band or taps jump (don't re-hide from gap alone).
    else setAtBottom(false);
  }, [contentKey, scrollToBottom]);

  // Context switch: always re-stick and land on the latest item.
  // biome-ignore lint/correctness/useExhaustiveDependencies: resetKey is an intentional re-run key.
  useLayoutEffect(() => {
    applyStick(true);
    scrollToBottom("auto");
  }, [resetKey, applyStick, scrollToBottom]);

  return { scrollRef, atBottom, jumpToBottom };
}
