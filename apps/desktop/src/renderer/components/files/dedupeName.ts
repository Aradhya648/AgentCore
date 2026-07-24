/**
 * 为「复制-粘贴」算一个在目标目录中不冲突的名字：命中即追加「 副本」，再冲突则「 副本 2」…
 * 保留扩展名（`a.txt` → `a 副本.txt`）。前导点文件（`.env`）按无扩展名整体处理。
 */
export function dedupeName(name: string, existing: Set<string>): string {
  if (!existing.has(name)) return name;
  const dot = name.lastIndexOf(".");
  const hasExt = dot > 0; // 前导点（dot===0）不算扩展名
  const stem = hasExt ? name.slice(0, dot) : name;
  const ext = hasExt ? name.slice(dot) : "";
  let candidate = `${stem} 副本${ext}`;
  let n = 2;
  while (existing.has(candidate)) {
    candidate = `${stem} 副本 ${n}${ext}`;
    n++;
  }
  return candidate;
}
