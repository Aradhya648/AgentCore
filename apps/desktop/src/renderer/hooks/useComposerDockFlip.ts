import { type RefObject, useLayoutEffect, useRef } from "react";

/** Duration / easing for empty-draft composer landing at the bottom bar. */
export const COMPOSER_DOCK_FLIP_MS = 420;
const COMPOSER_DOCK_FLIP_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";

/**
 * FLIP the composer chrome from the empty-draft center block down to the bottom
 * bar when the first message lands. Keeps a single mounted input (no remount jump)
 * and forbids an instant teleport.
 *
 * The animation is gated on `armToken` — a one-shot signal bumped ONLY when a draft
 * promotes to a brand-new conversation on first send. Because `ChatView` deliberately
 * stays mounted across conversation switches, keying off the passive centered→bottom
 * transition would also fire when merely SWITCHING to another conversation (which
 * briefly reports "no messages" while its history loads). That misfire is the
 * "输入框一直在跳动" bug; requiring an explicit arm confines the flight to real
 * first-sends and lets every switch settle in place.
 */
export function useComposerDockFlip(
  flipRef: RefObject<HTMLElement | null>,
  centered: boolean,
  armToken: number,
): void {
  const firstRectRef = useRef<DOMRect | null>(null);
  const armedRef = useRef(false);
  const seenArmRef = useRef(armToken);

  useLayoutEffect(() => {
    const el = flipRef.current;
    if (!el) return;

    // A bumped token = the draft just promoted to a new conversation; the coming
    // center→bottom transition is a genuine "landing" and may animate.
    if (armToken !== seenArmRef.current) {
      seenArmRef.current = armToken;
      armedRef.current = true;
    }

    if (centered) {
      firstRectRef.current = el.getBoundingClientRect();
      return;
    }

    // Only a first-send (armed, with a recorded start rect) plays. A conversation
    // switch never arms, so its composer settles at the bottom with no animation.
    if (!armedRef.current || !firstRectRef.current) {
      armedRef.current = false;
      firstRectRef.current = null;
      return;
    }

    const first = firstRectRef.current;
    const last = el.getBoundingClientRect();
    const dx = first.left - last.left;
    const dy = first.top - last.top;
    armedRef.current = false;
    firstRectRef.current = null;

    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;

    el.animate(
      [
        { transform: `translate(${dx}px, ${dy}px)` },
        { transform: "translate(0, 0)" },
      ],
      {
        duration: COMPOSER_DOCK_FLIP_MS,
        easing: COMPOSER_DOCK_FLIP_EASING,
      },
    );
  }, [centered, armToken, flipRef]);
}
