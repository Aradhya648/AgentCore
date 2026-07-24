/**
 * 根级约定目录（research/、debate/）的中性案卷元信息——文件树徽章与产物卡标签共用。
 * 可扩展：往表里加路径即可；无匹配则零噪音。
 */

export interface StageDirMeta {
  /** 目录短名（路径第一段） */
  key: string;
  /** 徽章主文案前缀，如「调研案卷」 */
  label: string;
  /** tooltip */
  tooltip: string;
}

/** 根级路径 → 元信息（仅精确匹配 `research` / `debate`）。 */
const STAGE_DIRS: Record<string, StageDirMeta> = {
  research: {
    key: "research",
    label: "调研案卷",
    tooltip: "团队协作阶段产物，后续阶段会读取",
  },
  debate: {
    key: "debate",
    label: "辩论产物",
    tooltip: "团队协作阶段产物，后续阶段会读取",
  },
};

/** 规范化：去尾斜杠，POSIX 相对路径。 */
function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "");
}

/** 根级约定目录元信息；非约定目录返回 null（零噪音）。 */
export function stageDirMeta(path: string): StageDirMeta | null {
  const p = normalizePath(path);
  if (!p || p.includes("/")) return null;
  return STAGE_DIRS[p] ?? null;
}

/** 文件落在约定目录下时的小标签（research/* / debate/*）。 */
export function stageFileLabel(path: string): string | null {
  const p = normalizePath(path);
  const slash = p.indexOf("/");
  if (slash <= 0) return null;
  const root = p.slice(0, slash);
  return STAGE_DIRS[root]?.label ?? null;
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
