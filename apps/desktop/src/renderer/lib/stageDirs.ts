/**
 * 案卷约定目录（``AgentCore/文档/{research,debate,reviews}/``）的中性元信息——
 * 文件树徽章与产物卡标签共用。与后端 ``workspace.stage_dirs`` 对齐；无匹配则零噪音。
 */

export const DOCS_PREFIX = "AgentCore/文档";
export const RESEARCH_DIR = `${DOCS_PREFIX}/research`;
export const DEBATE_DIR = `${DOCS_PREFIX}/debate`;
export const REVIEWS_DIR = `${DOCS_PREFIX}/reviews`;

export interface StageDirMeta {
  /** 目录短名（research / debate / reviews） */
  key: string;
  /** 徽章主文案前缀，如「调研案卷」 */
  label: string;
  /** tooltip */
  tooltip: string;
}

/** 约定目录完整相对路径 → 元信息（精确匹配）。 */
const STAGE_DIRS: Record<string, StageDirMeta> = {
  [RESEARCH_DIR]: {
    key: "research",
    label: "调研案卷",
    tooltip: "团队协作阶段产物，后续阶段会读取",
  },
  [DEBATE_DIR]: {
    key: "debate",
    label: "辩论产物",
    tooltip: "团队协作阶段产物，后续阶段会读取",
  },
  [REVIEWS_DIR]: {
    key: "reviews",
    label: "审查",
    tooltip: "审查与质检副产物",
  },
};

/** 规范化：去尾斜杠，POSIX 相对路径。 */
function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "");
}

/** 约定目录元信息；非约定目录返回 null（零噪音）。 */
export function stageDirMeta(path: string): StageDirMeta | null {
  const p = normalizePath(path);
  if (!p) return null;
  return STAGE_DIRS[p] ?? null;
}

/** 文件落在约定目录下时的小标签。 */
export function stageFileLabel(path: string): string | null {
  const p = normalizePath(path);
  for (const [dir, meta] of Object.entries(STAGE_DIRS)) {
    if (p === dir || p.startsWith(`${dir}/`)) return meta.label;
  }
  return null;
}

export type ChildrenLookup = (
  dir: string,
) => { isDir: boolean; path: string }[] | undefined;

/** 统计目录下已加载的后代文件数（不含子目录本身）。未加载则按 0。 */
export function countDescendantFiles(
  dirPath: string,
  childrenOf: ChildrenLookup,
): number {
  const kids = childrenOf(dirPath);
  if (!kids) return 0;
  let n = 0;
  for (const c of kids) {
    if (c.isDir) n += countDescendantFiles(c.path, childrenOf);
    else n += 1;
  }
  return n;
}

/** 「调研案卷 · 3 件」副文案。 */
export function stageDirCaption(meta: StageDirMeta, fileCount: number): string {
  return `${meta.label} · ${fileCount} 件`;
}
