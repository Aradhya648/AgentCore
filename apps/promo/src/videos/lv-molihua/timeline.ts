/*
 * Single source of truth for lv-molihua hybrid package segment boundaries (@30fps).
 * Design kit only: cold-open highlight reel + 7 chapter titles + end logo.
 * (No mid-film product-flow scenes — those come from screen recording later.)
 */

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** Cross-dissolve between adjacent phases. */
export const FADE = 10;

/** Per-cut length inside the cold-open reel (3.33s). */
export const COLD_CUT = 100;

/** Closing hook beat after the 4 cuts (~2s). */
export const COLD_HOOK = 50;

export const COLD_OPEN = {
  from: 0,
  frames: COLD_CUT * 4 + COLD_HOOK, // 450 = 15s
} as const;

/** Each act title card (~2s). */
export const CHAPTER_FRAMES = 60;

export const CHAPTERS = {
  from: COLD_OPEN.from + COLD_OPEN.frames, // 450
  frames: CHAPTER_FRAMES * 7, // 420 = 14s
} as const;

export const LOGO = {
  from: CHAPTERS.from + CHAPTERS.frames, // 870
  frames: 90, // 3s
} as const;

/** Full hybrid film length. */
export const FILM_FRAMES = LOGO.from + LOGO.frames; // 960 = 32s
