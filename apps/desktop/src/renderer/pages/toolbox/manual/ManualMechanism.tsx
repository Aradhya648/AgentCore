import { ChapterRenderer } from "./ChapterRenderer";
import { mechanismChapter } from "./content/mechanism";

/** 看懂协作（选读）——由结构化内容源驱动。 */
export function ManualMechanism() {
  return (
    <ChapterRenderer
      chapter={mechanismChapter}
      previewManual="manual-mechanism"
    />
  );
}
