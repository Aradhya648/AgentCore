/**
 * Stick-to-bottom semantics for mobile AI chat and IM threads.
 *
 * Position alone is not enough while a stream (or poll) is appending: a user
 * trying to leave the bottom band loses the race to the next layout-effect
 * `scrollTo`. Callers therefore also detach on upward touch/wheel intent, and
 * use hysteresis so re-attach requires a tighter band than detach.
 *
 * Mobile-local copy of the desktop stick contract — do not import from desktop.
 */

/** Leave stick once farther from the bottom than this. */
export const STICK_DETACH_PX = 80;
/** Re-attach only once closer to the bottom than this (hysteresis). */
export const STICK_ATTACH_PX = 24;

export function distanceFromBottom(el: HTMLElement): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

/** Hysteresis update: stuck → detach at DETACH; free → attach at ATTACH. */
export function nextStickState(currentlyStuck: boolean, gap: number): boolean {
  if (currentlyStuck) return gap < STICK_DETACH_PX;
  return gap < STICK_ATTACH_PX;
}

/** True when the gesture is scrolling toward older content (up the transcript). */
export function isScrollUpWheel(deltaY: number): boolean {
  return deltaY < 0;
}

/** True when a touch move drags the transcript toward older content. */
export function isScrollUpTouch(prevClientY: number, clientY: number): boolean {
  return clientY > prevClientY;
}
