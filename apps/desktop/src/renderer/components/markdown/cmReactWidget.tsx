/**
 * 在 CodeMirror6 的替换装饰里挂载 React 组件的通用 WidgetType（内联实时预览的底座）。
 *
 * - eq() 以 key 比对：内容不变时 CM 复用旧 DOM（不重挂 React），保住交互组件（如表格）焦点。
 * - destroy() 用 microtask 卸载 root，避开 React「渲染期间同步卸载」告警。
 * - interactive=true → ignoreEvent 返回 true，事件交给 widget 自理（表格输入）；
 *   false → 交给 CM 处理（点击移动光标 → 选区感知装饰还原源码以编辑）。
 */

import { type EditorView, WidgetType } from "@codemirror/view";
import type { ReactNode } from "react";
import { type Root, createRoot } from "react-dom/client";

export class ReactBlockWidget extends WidgetType {
  private root: Root | null = null;

  constructor(
    private readonly key: string,
    private readonly render: (dom: HTMLElement, view: EditorView) => ReactNode,
    private readonly interactive = false,
  ) {
    super();
  }

  eq(other: ReactBlockWidget): boolean {
    return other.key === this.key && other.interactive === this.interactive;
  }

  toDOM(view: EditorView): HTMLElement {
    const dom = document.createElement("div");
    dom.className = "cm-live-block";
    this.root = createRoot(dom);
    this.root.render(this.render(dom, view));
    return dom;
  }

  destroy(): void {
    const root = this.root;
    this.root = null;
    if (root) queueMicrotask(() => root.unmount());
  }

  ignoreEvent(): boolean {
    return this.interactive;
  }
}
