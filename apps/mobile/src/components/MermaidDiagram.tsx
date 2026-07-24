// Lazy mermaid renderer for the mobile Markdown stack (前端技术与架构 §七 · 富渲染).
//
// mermaid is heavy (~500KB), so it is dynamically imported only when a ```mermaid block
// actually appears — it never lands in the main bundle (the "minimal deps / lazy mermaid"
// decision). On a render error we fall back to the raw source as a code block.
import { normalizeMermaidSource } from "@/lib/mermaidNormalize";
import { useEffect, useRef, useState } from "react";

// Initialize once, module-wide (re-init on every render would reset config + leak work).
let mermaidMod: typeof import("mermaid").default | null = null;
async function getMermaid() {
  if (!mermaidMod) {
    const mod = (await import("mermaid")).default;
    mod.initialize({
      startOnLoad: false,
      theme: "neutral", // light only — 手机端暂不做暗色
      securityLevel: "strict",
    });
    mermaidMod = mod;
  }
  return mermaidMod;
}

export function MermaidDiagram({ chart }: { chart: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  // A unique, DOM-id-safe render target per instance.
  const idRef = useRef(`m${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setFailed(false);
    const normalized = normalizeMermaidSource(chart);
    getMermaid()
      .then((m) =>
        m.parse(normalized).then(() => m.render(idRef.current, normalized)),
      )
      .then(({ svg }) => {
        if (!cancelled) setSvg(svg);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (failed) return <pre className="tool-pre">{chart}</pre>;
  if (!svg) return <div className="mermaid-wrap muted">绘制图表中…</div>;
  // svg is mermaid's own serialized output (securityLevel "strict" sanitizes it).
  return (
    // biome-ignore lint/security/noDangerouslySetInnerHtml: trusted, sanitized mermaid SVG
    <div className="mermaid-wrap" dangerouslySetInnerHTML={{ __html: svg }} />
  );
}
