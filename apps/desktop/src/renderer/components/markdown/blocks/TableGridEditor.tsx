/**
 * GFM 表格的内联网格编辑器（CodeMirror live preview widget 用）。
 *
 * 编辑保存在本地 state，焦点离开整个网格时才回写一次源码（onApply）——避免逐格回写
 * 触发编辑器重建导致输入焦点丢失。源码未变期间 widget 的 DOM 稳定（见 cmReactWidget eq）。
 */

import { Button, IconButton } from "@/components/ui";
import { Code2, Plus, Trash2 } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { type TableData, parseGfmTable, serializeGfmTable } from "./tableGrid";

interface TableGridEditorProps {
  source: string;
  /** 焦点离开网格时回写 GFM 文本。 */
  onApply: (markdown: string) => void;
  /** 切换到源码编辑（把光标移进表格文本）。 */
  onEditSource: () => void;
}

export function TableGridEditor({
  source,
  onApply,
  onEditSource,
}: TableGridEditorProps) {
  const [data, setData] = useState<TableData | null>(() =>
    parseGfmTable(source),
  );
  const dirtyRef = useRef(false);
  useEffect(() => {
    setData(parseGfmTable(source));
    dirtyRef.current = false;
  }, [source]);

  if (!data) {
    return (
      <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs text-muted-foreground">
        {source}
      </pre>
    );
  }

  const mutate = (next: TableData) => {
    dirtyRef.current = true;
    setData(next);
  };
  const commit = () => {
    if (dirtyRef.current && data) {
      dirtyRef.current = false;
      onApply(serializeGfmTable(data));
    }
  };

  const setHeader = (i: number, v: string) =>
    mutate({ ...data, headers: data.headers.map((h, j) => (j === i ? v : h)) });
  const setCell = (r: number, c: number, v: string) =>
    mutate({
      ...data,
      rows: data.rows.map((row, ri) =>
        ri === r ? row.map((cell, ci) => (ci === c ? v : cell)) : row,
      ),
    });
  const addRow = () =>
    mutate({ ...data, rows: [...data.rows, data.headers.map(() => "")] });
  const delRow = (r: number) =>
    mutate({ ...data, rows: data.rows.filter((_, ri) => ri !== r) });
  const addCol = () =>
    mutate({
      ...data,
      headers: [...data.headers, "列"],
      aligns: [...data.aligns, "none"],
      rows: data.rows.map((r) => [...r, ""]),
    });
  const delCol = (c: number) => {
    if (data.headers.length <= 1) return;
    mutate({
      ...data,
      headers: data.headers.filter((_, i) => i !== c),
      aligns: data.aligns.filter((_, i) => i !== c),
      rows: data.rows.map((r) => r.filter((_, i) => i !== c)),
    });
  };

  return (
    <div
      className="cm-table-grid my-2 overflow-hidden rounded-lg border border-border bg-background"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) commit();
      }}
    >
      <div className="flex items-center gap-1 border-b border-border bg-muted/40 px-2 py-1">
        <span className="mr-auto text-xs text-muted-foreground">表格</span>
        <GridBtn title="添加行" onClick={addRow}>
          <Plus className="size-3.5" />行
        </GridBtn>
        <GridBtn title="添加列" onClick={addCol}>
          <Plus className="size-3.5" />列
        </GridBtn>
        <GridBtn title="编辑源码" onClick={onEditSource}>
          <Code2 className="size-3.5" />
          源码
        </GridBtn>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              {data.headers.map((h, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: 网格按位置编辑，索引即稳定身份。
                <th key={i} className="border border-border bg-muted/30 p-0">
                  <div className="flex items-center">
                    <input
                      value={h}
                      onChange={(e) => setHeader(i, e.target.value)}
                      className="w-full bg-transparent px-2 py-1.5 font-semibold text-foreground outline-none focus:bg-accent/40"
                    />
                    {data.headers.length > 1 && (
                      <IconButton
                        title="删除列"
                        aria-label="删除列"
                        onClick={() => delCol(i)}
                        className="size-6 shrink-0 px-1 text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="size-3.5" />
                      </IconButton>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, r) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: 网格按位置编辑，索引即稳定身份。
              <tr key={r} className="group/row">
                {row.map((cell, c) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: 网格按位置编辑，索引即稳定身份。
                  <td key={c} className="border border-border p-0">
                    <div className="flex items-center">
                      <input
                        value={cell}
                        onChange={(e) => setCell(r, c, e.target.value)}
                        className="w-full bg-transparent px-2 py-1.5 text-foreground outline-none focus:bg-accent/40"
                      />
                      {c === row.length - 1 && (
                        <IconButton
                          title="删除行"
                          aria-label="删除行"
                          onClick={() => delRow(r)}
                          className="size-6 shrink-0 px-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover/row:opacity-100"
                        >
                          <Trash2 className="size-3.5" />
                        </IconButton>
                      )}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GridBtn({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button
      variant="ghost"
      title={title}
      onClick={onClick}
      className="h-6 gap-0.5 px-1.5 py-0 text-xs font-normal text-muted-foreground"
    >
      {children}
    </Button>
  );
}
