/**
 * Front matter 元数据卡片（CodeMirror 内联实时预览用）。
 * 把文档头部的 YAML front matter 渲染成 key→value 表，替代裸 `---` 源码。
 */

import { useMemo } from "react";
import { type FrontmatterField, parseFrontmatterFields } from "./frontmatter";

export function FrontmatterCard({ yaml }: { yaml: string }) {
  const rows = useMemo<FrontmatterField[]>(
    () => parseFrontmatterFields(yaml),
    [yaml],
  );

  return (
    <div className="cm-frontmatter my-2 overflow-hidden rounded-lg border border-border bg-muted/20">
      <div className="border-b border-border px-3 py-1.5 text-xs font-medium tracking-wide text-muted-foreground">
        Front matter
      </div>
      {rows.length > 0 ? (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: 字段按解析顺序展示，索引即稳定身份。
              <tr key={i} className="border-t border-border first:border-t-0">
                <td className="w-40 px-3 py-1.5 align-top font-mono text-xs text-muted-foreground">
                  {r.key || "—"}
                </td>
                <td className="px-3 py-1.5 text-foreground/90">{r.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="px-3 py-1.5 text-xs text-muted-foreground">（空）</div>
      )}
    </div>
  );
}
