import { continueRender, delayRender } from "remotion";

/*
 * Block the render until the self-hosted webfaces (declared in styles.css) have
 * loaded, so no frame is ever captured mid font-swap and the output is identical
 * across machines (no system-font fallback drift). Single-file woff2 (not
 * unicode-range split), so loading any one glyph fetches the whole face.
 */
const FACES = [
  '400 16px "Inter"',
  '500 16px "Inter"',
  '600 16px "Inter"',
  '400 16px "Noto Sans SC"',
  '500 16px "Noto Sans SC"',
];

let started = false;

/** Idempotent — safe to call from module scope and component bodies alike.
 *
 * Bulletproof against a render-worker hang: under concurrency each frame's page
 * re-evals this, and `document.fonts.load` can occasionally never settle on a
 * worker — which the old `.catch` couldn't rescue (a hang isn't a rejection),
 * timing the render out. So we race the font loads against a hard cap and ALWAYS
 * continueRender; the woff2 @font-face in styles.css still applies regardless. */
export function ensurePromoFonts(): void {
  if (started || typeof document === "undefined") return;
  started = true;
  const handle = delayRender("Loading promo fonts (Inter + Noto Sans SC)", {
    timeoutInMilliseconds: 60000,
  });
  const finish = () => {
    try {
      continueRender(handle);
    } catch {
      /* already continued (double-settle from the race) — ignore */
    }
  };
  const ready = Promise.all(FACES.map((spec) => document.fonts.load(spec))).then(
    () => document.fonts.ready,
  );
  Promise.race([
    ready,
    new Promise((resolve) => setTimeout(resolve, 8000)),
  ])
    .then(finish)
    .catch(finish);
}
