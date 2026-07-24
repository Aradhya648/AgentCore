import raw from "./manual-scenes.json";

export interface ManualPreviewScene {
  id: string;
  description: string;
  path: string;
  /** Scroll target section id (`?s=`). Omit for page top. */
  section?: string;
  /** Matches `ChapterRenderer` `previewManual` / `data-preview-manual`. */
  previewManual?: string;
  /** Wait for these `data-manual-embed` keys (lazy embeds / real graphs) before shot. */
  waitEmbeds?: string[];
}

/** Static manual pages for offline screenshot harness (`pnpm shoot:manual`). */
export const MANUAL_PREVIEW_SCENES = raw as ManualPreviewScene[];
