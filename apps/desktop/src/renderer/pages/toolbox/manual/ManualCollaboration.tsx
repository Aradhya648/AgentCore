import { ChapterRenderer } from "./ChapterRenderer";
import { collaborationChapter } from "./content/collaboration";

/** 指挥你的团队——由结构化内容源驱动。 */
export function ManualCollaboration() {
  return (
    <ChapterRenderer
      chapter={collaborationChapter}
      previewManual="manual-collaboration"
    />
  );
}
