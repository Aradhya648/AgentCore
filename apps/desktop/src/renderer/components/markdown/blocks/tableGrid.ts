/**
 * GFM 表格 ↔ 网格数据的纯转换。供 CodeMirror 内联表格网格编辑 widget 使用。
 *
 * 「文本即典范」：网格只是 GFM 表格文本的可视编辑投影，parse/serialize 必须往返稳定。
 * 已知限制：不处理单元格内转义的 `\|`（按字面 `|` 切分）——P2 范围外。
 */

export type Align = "none" | "left" | "center" | "right";

export interface TableData {
  headers: string[];
  aligns: Align[];
  rows: string[][];
}

function splitCells(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function parseAlign(cell: string): Align {
  const l = cell.startsWith(":");
  const r = cell.endsWith(":");
  if (l && r) return "center";
  if (r) return "right";
  if (l) return "left";
  return "none";
}

/** 解析一段 GFM 表格文本；非合法表格返回 null。 */
export function parseGfmTable(src: string): TableData | null {
  const lines = src.split("\n").filter((l) => l.trim() !== "");
  const headerLine = lines[0];
  const delimLine = lines[1];
  if (headerLine === undefined || delimLine === undefined) return null;
  const delim = splitCells(delimLine);
  if (delim.length === 0 || !delim.every((c) => /^:?-+:?$/.test(c)))
    return null;
  const headers = splitCells(headerLine);
  const cols = headers.length;
  const aligns = Array.from({ length: cols }, (_, i) =>
    parseAlign(delim[i] ?? "---"),
  );
  const rows = lines.slice(2).map((l) => {
    const cells = splitCells(l).slice(0, cols);
    while (cells.length < cols) cells.push("");
    return cells;
  });
  return { headers, aligns, rows };
}

function delimCell(align: Align, width: number): string {
  switch (align) {
    case "center":
      return `:${"-".repeat(Math.max(1, width - 2))}:`;
    case "left":
      return `:${"-".repeat(Math.max(1, width - 1))}`;
    case "right":
      return `${"-".repeat(Math.max(1, width - 1))}:`;
    default:
      return "-".repeat(Math.max(3, width));
  }
}

/** 把网格数据序列化回对齐良好的 GFM 表格文本。 */
export function serializeGfmTable({
  headers,
  aligns,
  rows,
}: TableData): string {
  const cols = headers.length;
  const widths = Array.from({ length: cols }, (_, i) =>
    Math.max(3, headers[i]?.length ?? 0, ...rows.map((r) => r[i]?.length ?? 0)),
  );
  const pad = (s: string, w: number) =>
    s + " ".repeat(Math.max(0, w - s.length));
  const renderRow = (cells: string[]) =>
    `| ${Array.from({ length: cols }, (_, i) =>
      pad(cells[i] ?? "", widths[i] ?? 3),
    ).join(" | ")} |`;
  const head = renderRow(headers);
  const delim = `| ${aligns
    .map((a, i) => delimCell(a, widths[i] ?? 3))
    .join(" | ")} |`;
  const body = rows.map(renderRow);
  return [head, delim, ...body].join("\n");
}
