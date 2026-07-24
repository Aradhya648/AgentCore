/** Auto-hide scrollbars: flag the document as "scrolling" so CSS can briefly
 * reveal the (otherwise transparent) scrollbar thumb during active scrolling,
 * then fade it back out — mirroring the macOS / Linear overlay-scrollbar feel.
 *
 * Pure CSS reveals thumbs on `:hover`, but cannot react to wheel / keyboard /
 * momentum scroll that happens without a hover change. A single capture-phase
 * listener toggles a root class; `globals.css` owns all of the visuals.
 */
const SCROLLING_CLASS = "is-scrolling";
const HIDE_DELAY_MS = 900;

let hideTimer: number | undefined;
let installed = false;

export function initScrollReveal(): void {
  if (installed || typeof document === "undefined") return;
  installed = true;

  const root = document.documentElement;

  const onScroll = () => {
    if (!root.classList.contains(SCROLLING_CLASS)) {
      root.classList.add(SCROLLING_CLASS);
    }
    if (hideTimer !== undefined) window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      root.classList.remove(SCROLLING_CLASS);
      hideTimer = undefined;
    }, HIDE_DELAY_MS);
  };

  // Capture phase + a single window listener catches scroll from every nested
  // container, since scroll events don't bubble. Passive: we never preventDefault.
  window.addEventListener("scroll", onScroll, { capture: true, passive: true });
}
