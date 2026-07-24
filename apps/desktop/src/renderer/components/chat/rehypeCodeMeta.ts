/**
 * 解析栅栏代码块的 `lang:path/to/file` 信息串（给代码块命名的常见约定）。
 *
 * 在 `rehype-highlight` **之前**运行：把 `language-ts:src/foo.ts` 改写回可被 hljs 识别的
 * `language-ts`（否则带路径的语言名会让高亮静默失效），并把路径存到 `data-file` 属性，
 * 供 `CodeBlock` 渲染成代码块的文件名头。纯 hast 树变换，无副作用。
 */

/** 最小 hast 节点结构（避免引入 @types/hast）；真实 hast Root/Element 结构上兼容。 */
interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

const LANG_PREFIX = "language-";

function rewriteCodeMeta(node: HastNode): void {
  if (node.tagName === "code" && node.properties) {
    const cn = node.properties.className;
    const classes = Array.isArray(cn)
      ? [...(cn as unknown[])]
      : typeof cn === "string"
        ? cn.split(/\s+/)
        : [];
    let changed = false;
    for (let i = 0; i < classes.length; i++) {
      const c = classes[i];
      if (typeof c !== "string" || !c.startsWith(LANG_PREFIX)) continue;
      const info = c.slice(LANG_PREFIX.length);
      const colon = info.indexOf(":");
      if (colon < 0) continue;
      const lang = info.slice(0, colon).trim();
      const path = info.slice(colon + 1).trim();
      if (!path) continue;
      classes[i] = `${LANG_PREFIX}${lang || "text"}`;
      node.properties.dataFile = path;
      changed = true;
    }
    if (changed) node.properties.className = classes;
  }
  if (node.children) for (const child of node.children) rewriteCodeMeta(child);
}

/** rehype 插件入口：返回一个就地改写树的 transformer。 */
export function rehypeCodeMeta() {
  return (tree: HastNode): void => {
    rewriteCodeMeta(tree);
  };
}
