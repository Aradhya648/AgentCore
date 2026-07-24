/**
 * 源码工具栏命令：对 CodeMirror 选区做 Markdown 文本变换。
 *
 * 全部是「文本进、文本出」的纯变换——契合「文本即典范」：工具栏只是帮用户敲对 Markdown，
 * 不引入任何富文本中间态。
 */

import { type ChangeSpec, EditorSelection } from "@codemirror/state";
import type { EditorView } from "@codemirror/view";

/** 用 before/after 包裹选区（加粗/斜体/删除线/行内代码）。 */
export function wrapInline(
  view: EditorView,
  before: string,
  after = before,
): void {
  const { state } = view;
  const tr = state.changeByRange((range) => {
    const selected = state.sliceDoc(range.from, range.to);
    return {
      changes: {
        from: range.from,
        to: range.to,
        insert: before + selected + after,
      },
      range: EditorSelection.range(
        range.from + before.length,
        range.from + before.length + selected.length,
      ),
    };
  });
  view.dispatch(state.update(tr, { userEvent: "input", scrollIntoView: true }));
  view.focus();
}

/** 对选区覆盖的每一行套用文本映射（标题/列表/引用等行级标记）。 */
function eachSelectedLine(
  view: EditorView,
  map: (text: string) => string,
): void {
  const { state } = view;
  const changes: ChangeSpec[] = [];
  for (const range of state.selection.ranges) {
    const startLine = state.doc.lineAt(range.from);
    const endLine = state.doc.lineAt(range.to);
    for (let n = startLine.number; n <= endLine.number; n++) {
      const line = state.doc.line(n);
      const next = map(line.text);
      if (next !== line.text) {
        changes.push({ from: line.from, to: line.to, insert: next });
      }
    }
  }
  if (changes.length)
    view.dispatch(state.update({ changes, userEvent: "input" }));
  view.focus();
}

export function setHeading(view: EditorView, level: number): void {
  eachSelectedLine(
    view,
    (text) => `${"#".repeat(level)} ${text.replace(/^#{1,6}\s+/, "")}`,
  );
}

export function toggleBulletList(view: EditorView): void {
  eachSelectedLine(view, (text) =>
    /^\s*[-*+]\s+/.test(text)
      ? text.replace(/^(\s*)[-*+]\s+/, "$1")
      : `- ${text}`,
  );
}

export function toggleOrderedList(view: EditorView): void {
  eachSelectedLine(view, (text) =>
    /^\s*\d+\.\s+/.test(text)
      ? text.replace(/^(\s*)\d+\.\s+/, "$1")
      : `1. ${text}`,
  );
}

export function toggleTaskList(view: EditorView): void {
  eachSelectedLine(view, (text) =>
    /^\s*[-*+]\s+\[[ xX]\]\s+/.test(text)
      ? text.replace(/^(\s*)[-*+]\s+\[[ xX]\]\s+/, "$1")
      : `- [ ] ${text}`,
  );
}

export function toggleQuote(view: EditorView): void {
  eachSelectedLine(view, (text) =>
    /^>\s?/.test(text) ? text.replace(/^>\s?/, "") : `> ${text}`,
  );
}

/** 在当前行之后另起空行插入一个独立块（表格/分割线/代码块骨架）。 */
function insertBlock(view: EditorView, block: string): void {
  const { state } = view;
  const line = state.doc.lineAt(state.selection.main.from);
  const text = `\n\n${block}\n`;
  view.dispatch(
    state.update({
      changes: { from: line.to, insert: text },
      selection: EditorSelection.cursor(line.to + text.length),
      userEvent: "input",
      scrollIntoView: true,
    }),
  );
  view.focus();
}

export function insertHr(view: EditorView): void {
  insertBlock(view, "---");
}

export function insertTable(view: EditorView): void {
  insertBlock(
    view,
    ["| 列 1 | 列 2 | 列 3 |", "| --- | --- | --- |", "|  |  |  |"].join("\n"),
  );
}

export function insertCodeBlock(view: EditorView): void {
  const { state } = view;
  const range = state.selection.main;
  const selected = state.sliceDoc(range.from, range.to);
  const insert = `\`\`\`\n${selected}\n\`\`\``;
  view.dispatch(
    state.update({
      changes: { from: range.from, to: range.to, insert },
      selection: EditorSelection.cursor(range.from + 4),
      userEvent: "input",
    }),
  );
  view.focus();
}

/**
 * 插入链接：套 `[文本](url)` 模板并选中 `url` 占位，便于直接键入地址。
 *
 * 不用 `window.prompt`——Electron 渲染进程不支持 prompt（会抛错），选中占位的就地编辑
 * 既绕开限制、UX 也更顺。
 */
export function insertLink(view: EditorView): void {
  const url = "https://";
  const { state } = view;
  const tr = state.changeByRange((range) => {
    const selected = state.sliceDoc(range.from, range.to) || "链接文本";
    // 偏移：`[` + 文本 + `](` 之后即 url 起点
    const urlFrom = range.from + 1 + selected.length + 2;
    return {
      changes: {
        from: range.from,
        to: range.to,
        insert: `[${selected}](${url})`,
      },
      range: EditorSelection.range(urlFrom, urlFrom + url.length),
    };
  });
  view.dispatch(state.update(tr, { userEvent: "input", scrollIntoView: true }));
  view.focus();
}
