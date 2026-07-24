/**
 * CodeMirror6 源码编辑视图的外观（编辑器主题 + Markdown 语法高亮）。
 *
 * 配色**只用语义 token**（`globals.css` 的 `--foreground`/`--primary`/`--muted-foreground`
 * 与代码高亮 `--syntax-*`），禁硬编码 hex（见 `color-tokens.mdc`）；选区用 `color-mix`
 * 在品牌色上取透明度，亮/暗主题自动跟随。代码块高亮另在 `globals.css` 的 `.markdown-body`，
 * 此处只管源码编辑视图自身。
 */

import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import type { Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";

const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
// 内联实时预览 widget 用应用正文字体（否则继承 .cm-scroller 的等宽字体，表格/图文字会发虚）。
const SANS =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif';

const editorTheme = EditorView.theme({
  "&": {
    color: "var(--foreground)",
    backgroundColor: "transparent",
    height: "100%",
    fontSize: "14px",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: MONO, lineHeight: "1.7", overflow: "auto" },
  ".cm-content": {
    padding: "1.5rem 0",
    caretColor: "var(--foreground)",
    maxWidth: "56rem",
    margin: "0 auto",
  },
  ".cm-line": { padding: "0 1.5rem" },
  // 内联预览块：与源码行同列对齐（左右 1.5rem），换回正文字体与正常行高。
  ".cm-live-block": {
    padding: "0 1.5rem",
    fontFamily: SANS,
    lineHeight: "1.6",
  },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--foreground)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
    {
      backgroundColor: "color-mix(in oklch, var(--primary) 25%, transparent)",
    },
  ".cm-selectionMatch": {
    backgroundColor: "color-mix(in oklch, var(--primary) 18%, transparent)",
  },
});

const mdHighlight = HighlightStyle.define([
  {
    tag: t.heading1,
    fontWeight: "700",
    fontSize: "1.3em",
    color: "var(--foreground)",
  },
  {
    tag: t.heading2,
    fontWeight: "700",
    fontSize: "1.15em",
    color: "var(--foreground)",
  },
  {
    tag: [t.heading3, t.heading4, t.heading5, t.heading6],
    fontWeight: "600",
    color: "var(--foreground)",
  },
  { tag: t.strong, fontWeight: "700", color: "var(--foreground)" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "var(--primary)" },
  { tag: t.url, color: "var(--muted-foreground)" },
  { tag: t.monospace, fontFamily: MONO, color: "var(--syntax-string)" },
  { tag: t.quote, color: "var(--muted-foreground)", fontStyle: "italic" },
  {
    tag: [t.processingInstruction, t.meta],
    color: "var(--muted-foreground)",
  },
  {
    tag: t.contentSeparator,
    color: "var(--muted-foreground)",
    fontWeight: "600",
  },
  { tag: t.list, color: "var(--foreground)" },
]);

/** 源码编辑视图的完整外观（主题 + 语法高亮）。 */
export const markdownEditorTheme: Extension = [
  editorTheme,
  syntaxHighlighting(mdHighlight),
];
