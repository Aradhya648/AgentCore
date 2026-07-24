/**
 * CodeMirror6 内联实时预览：把 mermaid / markmap / 数学块($$) / GFM 表格 / frontmatter 就地
 * 渲染成 React widget，光标进入块内（选区与块相交）时还原为源码以便编辑。「所见即所得是视图而非
 * 模型」——源仍是 markdown 文本本身，widget 只是装饰，故零 round-trip 债、diff 干净（见文档
 * 编辑器落地设计 §二）。
 *
 * 渲染源复用聊天侧：mermaid / markmap 走 {@link DiagramBlock}（自带缩放/复制/导出），公式走
 * {@link MathBlock}（同 KaTeX 引擎）；frontmatter 用 {@link FrontmatterCard} 渲成元数据表。
 *
 * 为何用 StateField 而非 ViewPlugin：块级 / 跨行 replace 装饰会改变垂直布局，必须经 StateField
 * 提供（CM 在算视口前就要拿到块高度；ViewPlugin 提供的此类装饰不被允许）。widget 需要的 view 在
 * toDOM(view) 拿。
 *
 * 性能（大文档逐键开销）：
 * 1. 抽取与装配分离 + 缓存：raw block 只在 docChanged 时重扫语法树；纯光标移动复用缓存，仅做
 *    O(块数) 的「选区是否相交」过滤，不再每次方向键全量重扫。
 * 2. 遍历剪枝：collectBlocks 不下钻段落/标题等只含行内内容的叶块，把语法树遍历从 O(全部节点)
 *    降到 O(块结构)。
 * 3. 兜底：超过 MAX_LINES 直接退化为纯源码（不挂装饰），避免病态大文档卡顿。
 */

import { DiagramBlock } from "@/components/chat/Diagram";
import { syntaxTree } from "@codemirror/language";
import {
  type EditorState,
  type Extension,
  RangeSetBuilder,
  StateField,
} from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView } from "@codemirror/view";
import { FrontmatterCard } from "./blocks/FrontmatterCard";
import { MathBlock } from "./blocks/MathBlock";
import { TableGridEditor } from "./blocks/TableGridEditor";
import { ReactBlockWidget } from "./cmReactWidget";

const MAX_LINES = 5000;

/** 只含行内内容、不可能嵌套目标块的叶块——遍历到此即停，省掉行内子树的下钻。 */
const SKIP_DESCENT = new Set([
  "Paragraph",
  "ATXHeading1",
  "ATXHeading2",
  "ATXHeading3",
  "ATXHeading4",
  "ATXHeading5",
  "ATXHeading6",
  "SetextHeading1",
  "SetextHeading2",
]);

interface RawBlock {
  from: number;
  to: number;
  widget: ReactBlockWidget;
}

interface FieldValue {
  /** 按 from 升序的原始块（仅 docChanged 时重算）。 */
  blocks: RawBlock[];
  deco: DecorationSet;
}

function lineAligned(
  state: EditorState,
  from: number,
  to: number,
): { from: number; to: number } {
  const a = state.doc.lineAt(from).from;
  const b = state.doc.lineAt(Math.max(from, to - 1)).to;
  return { from: a, to: b };
}

function makeFenceWidget(
  kind: "mermaid" | "markmap",
  code: string,
): ReactBlockWidget {
  return new ReactBlockWidget(`${kind}:${code}`, () => (
    <DiagramBlock kind={kind} code={code} streaming={false} />
  ));
}

function makeMathWidget(tex: string): ReactBlockWidget {
  return new ReactBlockWidget(`math:${tex}`, () => (
    <MathBlock tex={tex} display />
  ));
}

function makeFrontmatterWidget(yaml: string): ReactBlockWidget {
  return new ReactBlockWidget(`fm:${yaml}`, () => (
    <FrontmatterCard yaml={yaml} />
  ));
}

function makeTableWidget(src: string): ReactBlockWidget {
  return new ReactBlockWidget(
    `table:${src}`,
    (dom, view) => (
      <TableGridEditor
        source={src}
        onApply={(md) => applyTableEdit(view, dom, md)}
        onEditSource={() => revealSource(view, dom)}
      />
    ),
    true,
  );
}

function tableRangeAt(
  view: EditorView,
  dom: HTMLElement,
): { from: number; to: number } | null {
  const pos = view.posAtDOM(dom);
  const tree = syntaxTree(view.state);
  let node: ReturnType<typeof tree.resolve> | null = tree.resolve(pos, 1);
  while (node && node.name !== "Table") node = node.parent;
  if (!node) return null;
  return lineAligned(view.state, node.from, node.to);
}

function applyTableEdit(view: EditorView, dom: HTMLElement, md: string): void {
  const range = tableRangeAt(view, dom);
  if (!range) return;
  view.dispatch({
    changes: { from: range.from, to: range.to, insert: md },
    userEvent: "input",
  });
}

function revealSource(view: EditorView, dom: HTMLElement): void {
  const pos = view.posAtDOM(dom);
  view.dispatch({ selection: { anchor: pos + 1 }, scrollIntoView: true });
  view.focus();
}

function inRanges(
  pos: number,
  ranges: { from: number; to: number }[],
): boolean {
  return ranges.some((r) => pos >= r.from && pos < r.to);
}

/** 文档首行为 `---` 且后续存在闭合 `---` 时识别为 front matter（否则首行 `---` 仍是分隔线）。 */
function collectFrontmatter(
  state: EditorState,
  out: RawBlock[],
): { from: number; to: number } | null {
  const doc = state.doc;
  if (doc.line(1).text.trim() !== "---") return null;
  let m = 2;
  while (m <= doc.lines && doc.line(m).text.trim() !== "---") m++;
  if (m > doc.lines) return null;
  const open = doc.line(1);
  const close = doc.line(m);
  const yaml = doc.sliceString(open.to + 1, close.from).replace(/\n+$/, "");
  out.push({
    from: open.from,
    to: close.to,
    widget: makeFrontmatterWidget(yaml),
  });
  return { from: open.from, to: close.to };
}

function collectMath(
  state: EditorState,
  out: RawBlock[],
  skip: { from: number; to: number }[],
): void {
  const doc = state.doc;
  let n = 1;
  while (n <= doc.lines) {
    const line = doc.line(n);
    if (inRanges(line.from, skip)) {
      n++;
      continue;
    }
    const trimmed = line.text.trim();
    const single = /^\$\$(.+?)\$\$$/.exec(trimmed);
    if (single) {
      out.push({
        from: line.from,
        to: line.to,
        widget: makeMathWidget((single[1] ?? "").trim()),
      });
      n++;
      continue;
    }
    if (trimmed === "$$") {
      let m = n + 1;
      while (m <= doc.lines && doc.line(m).text.trim() !== "$$") m++;
      if (m <= doc.lines) {
        const closeLine = doc.line(m);
        const tex = doc
          .sliceString(line.to + 1, closeLine.from)
          .replace(/\n+$/, "");
        out.push({
          from: line.from,
          to: closeLine.to,
          widget: makeMathWidget(tex),
        });
        n = m + 1;
        continue;
      }
    }
    n++;
  }
}

function collectBlocks(state: EditorState): RawBlock[] {
  const out: RawBlock[] = [];
  const skip: { from: number; to: number }[] = [];
  const fm = collectFrontmatter(state, out);
  if (fm) skip.push(fm); // front matter 区不再当 math 扫描

  const tree = syntaxTree(state);
  tree.iterate({
    enter: (node) => {
      if (node.name === "FencedCode" || node.name === "CodeBlock") {
        // 代码块整体跳过 math 扫描（块内的 $$ 不是公式）；mermaid/markmap 围栏额外渲成图。
        skip.push({ from: node.from, to: node.to });
        if (node.name === "FencedCode") {
          const info = node.node.getChild("CodeInfo");
          const lang = info
            ? state.sliceDoc(info.from, info.to).trim().toLowerCase()
            : "";
          if (lang === "mermaid" || lang === "markmap") {
            const text = node.node.getChild("CodeText");
            const code = text ? state.sliceDoc(text.from, text.to) : "";
            const r = lineAligned(state, node.from, node.to);
            out.push({ ...r, widget: makeFenceWidget(lang, code) });
          }
        }
        return false;
      }
      if (node.name === "Table") {
        const r = lineAligned(state, node.from, node.to);
        out.push({
          ...r,
          widget: makeTableWidget(state.sliceDoc(r.from, r.to)),
        });
        return false;
      }
      return SKIP_DESCENT.has(node.name) ? false : undefined;
    },
  });
  collectMath(state, out, skip);
  out.sort((a, b) => a.from - b.from);
  return out;
}

/** 从已抽取的块按当前选区装配装饰（廉价：O(块数)，光标移动时复用块缓存）。 */
function assemble(state: EditorState, blocks: RawBlock[]): DecorationSet {
  if (blocks.length === 0) return Decoration.none;
  const sel = state.selection.ranges;
  const builder = new RangeSetBuilder<Decoration>();
  let lastTo = -1;
  for (const b of blocks) {
    if (b.from <= lastTo || b.from >= b.to) continue;
    if (sel.some((r) => r.from <= b.to && r.to >= b.from)) continue;
    builder.add(
      b.from,
      b.to,
      Decoration.replace({ widget: b.widget, block: true }),
    );
    lastTo = b.to;
  }
  return builder.finish();
}

function extractBlocks(state: EditorState): RawBlock[] {
  if (state.doc.lines > MAX_LINES) return [];
  try {
    return collectBlocks(state);
  } catch {
    return [];
  }
}

const livePreviewField = StateField.define<FieldValue>({
  create(state) {
    const blocks = extractBlocks(state);
    return { blocks, deco: assemble(state, blocks) };
  },
  update(value, tr) {
    if (tr.docChanged) {
      const blocks = extractBlocks(tr.state);
      return { blocks, deco: assemble(tr.state, blocks) };
    }
    if (tr.selection) {
      return { blocks: value.blocks, deco: assemble(tr.state, value.blocks) };
    }
    return value;
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.deco),
});

export function livePreview(): Extension {
  return livePreviewField;
}
