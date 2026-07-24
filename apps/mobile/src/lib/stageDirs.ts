/**
 * 根级约定目录（research/、debate/）的中性案卷元信息——文件浏览器徽章与产物卡标签共用。
 * 可扩展：往表里加路径即可；无匹配则零噪音。
 */

export interface StageDirMeta {
  key: string;
  label: string;
  tooltip: string;
}

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

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "");
}

export function stageDirMeta(path: string): StageDirMeta | null {
  const p = normalizePath(path);
  if (!p || p.includes("/")) return null;
  return STAGE_DIRS[p] ?? null;
}

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

export function stageDirCaption(meta: StageDirMeta, fileCount: number): string {
  return `${meta.label} · ${fileCount} 件`;
}
