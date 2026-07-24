/*
 * Single source of truth for brand-30s segment boundaries (@30fps).
 * Video.tsx Sequences, Root composition durations, and subtitle cues all read here.
 */

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** Cross-dissolve length between adjacent phases (does not shift phase starts). */
export const FADE = 10;

export const OPENING = { from: 0, frames: 210 } as const; // 0–7s
export const RUN = { from: 210, frames: 510 } as const; // 7–24s
export const SCENARIOS = { from: 720, frames: 90 } as const; // 24–27s
export const LOGO = { from: 810, frames: 90 } as const; // 27–30s

/** Full film length. */
export const PROMO_FRAMES = LOGO.from + LOGO.frames; // 900

/**
 * Scene-local length of the graph execution beat inside Run (7–20s of the film).
 * Convergence / answer begins at this frame within RunMain.
 */
export const GRAPH_SCENE_FRAMES = 390;
