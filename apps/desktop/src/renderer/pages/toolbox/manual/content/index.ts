import type { ManualChapterContent } from "../types";
import { collaborationChapter } from "./collaboration";
import { introChapter } from "./intro";
import { mechanismChapter } from "./mechanism";
import { referenceChapter } from "./reference";

/** 全部章节的内容源（顺序即侧栏章序）。侧栏目录与搜索索引均由此派生。 */
export const CONTENT_CHAPTERS: ManualChapterContent[] = [
  introChapter,
  collaborationChapter,
  mechanismChapter,
  referenceChapter,
];
