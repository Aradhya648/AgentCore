import { useEvidenceLedgerMap } from "@/components/EvidenceLedgerContext";
import {
  extractLedgerId,
  ledgerBadgeLabel,
  ledgerTierLabel,
  ledgerTierShortLabel,
} from "@/lib/evidenceLedger";
import type { EvidenceLedgerEntry } from "@agentcore/contract-types";
import { BadgeCheck, CircleHelp, FileText, X } from "lucide-react";
import {
  Children,
  type ReactNode,
  isValidElement,
  useCallback,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router-dom";

/**
 * Inline evidence-status chip for a debater's factual claim (举证责任 + 证据台账 M1) —
 * rendered by {@link import("@/components/remarkEvidence").remarkEvidence} in place of a
 * `【已核实·<出处|#eN>】` / `【待核实·推断】` marker inside debate speech markdown.
 *
 * - **已核实**：note 含 `#eN` 且台账命中 → 徽章文案换成 site/title；可点开溯源面板
 *   （含案卷路径 / 幕1 #rN，可跳转对话文件页）。
 * - 未命中 / 旧自由文本 → 今日纯文案徽章。
 * - **待核实** → muted 灰（非琥珀）。
 */
export function EvidenceBadge({
  "data-kind": kind,
  children,
}: {
  "data-kind"?: string;
  children?: ReactNode;
}) {
  const verified = kind === "verified";
  const Icon = verified ? BadgeCheck : CircleHelp;
  const label = verified ? "已核实" : "待核实";
  const note = nodeText(children).trim();
  const ledger = useEvidenceLedgerMap();
  const ledgerId = verified ? extractLedgerId(note) : null;
  const entry = ledgerId && ledger ? (ledger.get(ledgerId) ?? null) : null;
  const displayNote = entry ? ledgerBadgeLabel(entry) : note;
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { id: conversationId } = useParams<{ id: string }>();

  const openDossier = useCallback(() => {
    const path = (entry?.dossier_path ?? "").trim();
    if (!path || !conversationId) return;
    setOpen(false);
    navigate(`/c/${conversationId}/files`, { state: { openPath: path } });
  }, [conversationId, entry?.dossier_path, navigate]);

  const hint = verified
    ? entry
      ? `已核实来源：${displayNote}`
      : "辩手标注：这条事实主张有据可查（附出处）"
    : "辩手标注：这条主张暂无出处 / 属推断——拿它当决定性论据会被裁判追问、扣分；诚实存疑本身不扣分";
  const hasNote = displayNote.length > 0;

  if (entry) {
    return (
      <>
        <button
          type="button"
          title={hint}
          className="evidence-badge evidence-verified evidence-tappable"
          onClick={() => setOpen(true)}
          aria-label={`已核实 · ${displayNote}（查看来源）`}
        >
          <Icon size={11} className="evidence-icon" aria-hidden />
          {label}
          {hasNote ? (
            <span className="evidence-note">·{displayNote}</span>
          ) : null}
          {entry.tier ? (
            <span
              className={`evidence-tier evidence-tier-${entry.tier}`}
              title={`来源可信度：${ledgerTierLabel(entry.tier)}`}
            >
              {ledgerTierShortLabel(entry.tier)}
            </span>
          ) : null}
        </button>
        {open ? (
          <EvidenceLedgerSheet
            entry={entry}
            onClose={() => setOpen(false)}
            onOpenDossier={
              (entry.dossier_path ?? "").trim() && conversationId
                ? openDossier
                : undefined
            }
          />
        ) : null}
      </>
    );
  }

  return (
    <span
      title={hint}
      className={`evidence-badge${verified ? " evidence-verified" : " evidence-unverified"}`}
    >
      <Icon size={11} className="evidence-icon" aria-hidden />
      {label}
      {hasNote ? <span className="evidence-note">·{displayNote}</span> : null}
    </span>
  );
}

function EvidenceLedgerSheet({
  entry,
  onClose,
  onOpenDossier,
}: {
  entry: EvidenceLedgerEntry;
  onClose: () => void;
  onOpenDossier?: () => void;
}) {
  const title = (entry.title ?? "").trim();
  const site = (entry.site ?? "").trim();
  const url = (entry.url ?? "").trim();
  const dossierPath = (entry.dossier_path ?? "").trim();
  const dossierLabel = (entry.dossier_label ?? "").trim();
  const originId = (entry.origin_id ?? "").trim();
  const dossierName = dossierPath
    ? dossierPath.replace(/\\/g, "/").split("/").pop() || dossierPath
    : "";

  return (
    // biome-ignore lint/a11y/useSemanticElements: bottom sheet 非原生 <dialog> 生命周期；保留 ARIA dialog 语义。
    <div className="evidence-sheet-root" role="dialog" aria-modal="true">
      <button
        type="button"
        className="evidence-sheet-backdrop"
        aria-label="关闭"
        onClick={onClose}
      />
      <div className="evidence-sheet">
        <div className="evidence-sheet-head">
          <div className="evidence-sheet-head-meta">
            <span className="evidence-sheet-id">{entry.id}</span>
            <span
              className={`evidence-tier evidence-tier-${entry.tier ?? "unknown"}`}
              title={`来源可信度：${ledgerTierLabel(entry.tier)}`}
            >
              {ledgerTierLabel(entry.tier)}
            </span>
          </div>
          <button
            type="button"
            className="evidence-sheet-close"
            onClick={onClose}
          >
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className="evidence-sheet-title">{title || site || entry.id}</div>
        {site && title ? (
          <div className="evidence-sheet-meta">{site}</div>
        ) : null}
        {dossierPath ? (
          <div className="evidence-sheet-dossier">
            <div className="evidence-sheet-dossier-label">
              案卷来源{dossierLabel ? ` · ${dossierLabel}` : ""}
            </div>
            <div className="evidence-sheet-dossier-path">{dossierName}</div>
            {originId ? (
              <div className="evidence-sheet-meta">幕1 出处 {originId}</div>
            ) : null}
            {onOpenDossier ? (
              <button
                type="button"
                className="evidence-sheet-open-file"
                onClick={onOpenDossier}
              >
                <FileText size={14} aria-hidden />
                打开案卷文件
              </button>
            ) : null}
          </div>
        ) : null}
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="evidence-sheet-link"
          >
            打开来源
          </a>
        ) : !dossierPath ? (
          <div className="evidence-sheet-meta">底料条目（无外链）</div>
        ) : null}
      </div>
    </div>
  );
}

function nodeText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return nodeText(node.props.children);
  }
  return Children.toArray(node).map(nodeText).join("");
}
