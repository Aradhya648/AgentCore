import { ChapterRenderer } from "./ChapterRenderer";
import { referenceChapter } from "./content/reference";

/** 参考 · 排查 · 信任——由结构化内容源驱动。 */
export function ManualReference() {
  return (
    <ChapterRenderer
      chapter={referenceChapter}
      previewManual="manual-reference"
    />
  );
}
