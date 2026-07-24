/**
 * KaTeX 数学块渲染（与聊天预览共享同一 KaTeX 引擎，外观一致）。
 *
 * 读路径（{@link Markdown} via rehype-katex）与写路径（CodeMirror 内联实时预览此组件）
 * 同引擎渲染 `$$...$$`。KaTeX 样式已在 `styles/globals.css` 全局引入，无需在此重复 import。
 */

import katex from "katex";
import { useMemo } from "react";

export function MathBlock({
  tex,
  display = true,
}: {
  tex: string;
  display?: boolean;
}) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, {
        displayMode: display,
        throwOnError: false,
      });
    } catch {
      return null;
    }
  }, [tex, display]);

  if (html == null) {
    return (
      <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs text-muted-foreground">
        {tex}
      </pre>
    );
  }

  return (
    <div
      className="my-2 overflow-x-auto text-center"
      // biome-ignore lint/security/noDangerouslySetInnerHtml: KaTeX(throwOnError=false) 仅输出受信的标记，不含脚本。
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
