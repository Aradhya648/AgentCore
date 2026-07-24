import { Easing, interpolate } from "remotion";

/*
 * Frame-driven motion primitives (apps/promo/README.md). The product animates
 * node entrance / running pulse / terminal flash / streaming on the CSS wall
 * clock, which a frame-accurate render cannot sync to (styles.css neutralizes
 * them). These pure helpers re-derive the same motions from the current frame so
 * every render is identical and the timeline can scrub freely.
 *
 * All take an absolute `frame` (within the clip) and return plain values, so they
 * compose in any component that has called useCurrentFrame().
 */

/** Node entrance — fade + slight rise, staggered per node by `enterFrame`. */
export function entranceStyle(
  frame: number,
  enterFrame: number,
  durationFrames = 9,
): { opacity: number; transform: string } {
  const p = interpolate(
    frame,
    [enterFrame, enterFrame + durationFrames],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );
  return { opacity: p, transform: `translateY(${(1 - p) * 6}px)` };
}

/** Running pulse — a calm opacity breathe while a node is executing (replaces
 * the product's `animate-pulse`). Returns 1 when inactive. */
export function pulseOpacity(frame: number, active: boolean): number {
  if (!active) return 1;
  // ~1.4s period, gently dipping to 0.78 and back — alive but not flickery.
  const phase = (frame / 42) * Math.PI * 2;
  return 0.89 + 0.11 * Math.cos(phase);
}

/** Terminal flash — a one-shot colored glow growing then fading when a run
 * reaches a terminal state (replaces `animate-graph-node-flash`). Returns a
 * box-shadow string ("none" outside the window). Alpha is faked via blur/spread
 * growth so the color stays a semantic token (no hardcoded rgba). */
export function flashShadow(
  frame: number,
  terminalFrame: number | null,
  ok = true,
): string {
  if (terminalFrame == null) return "none";
  const g = interpolate(
    frame,
    [terminalFrame, terminalFrame + 8, terminalFrame + 18],
    [0, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  if (g <= 0.001) return "none";
  const color = ok ? "var(--success)" : "var(--destructive)";
  return `0 0 ${14 * g}px ${4 * g}px ${color}`;
}

/** Stream a string in by frame (typewriter), ~`cps` chars/second. */
export function typeOut(
  text: string,
  frame: number,
  startFrame: number,
  fps: number,
  cps = 36,
): string {
  if (frame <= startFrame) return "";
  const chars = Math.floor(((frame - startFrame) / fps) * cps);
  return text.slice(0, Math.max(0, chars));
}

/** A blinking caret's visibility (~2 blinks/sec), for streaming previews. */
export function caretVisible(frame: number, fps: number): boolean {
  return Math.floor((frame / fps) * 4) % 2 === 0;
}

/**
 * Position fractions [0,1) of N evenly-phased particles riding an edge toward a
 * running node. One full traversal every `periodFrames`. The caller maps each
 * fraction onto the real edge path via getPointAtLength so particles follow the
 * exact StepEdge routing.
 */
export function particleFractions(
  frame: number,
  count = 3,
  periodFrames = 45,
): number[] {
  const base = (frame % periodFrames) / periodFrames;
  return Array.from({ length: count }, (_, i) => (base + i / count) % 1);
}
