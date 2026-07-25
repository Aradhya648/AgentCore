import { EscalationCard } from "@/components/chat/EscalationCard";
import { escalationRowKindLabel } from "@/components/graph/agentNode/shared";
import type { RunEscalation, RunNode } from "@/stores/execution";
import { ArrowUp } from "lucide-react";
import { Section } from "./shared";

/**
 * Stable React key for a run escalation row. Blocking escalations carry `id`; raised
 * banners have no wire id, so fall back to content fields (append-only list).
 */
function escalationRowKey(esc: RunEscalation): string {
  if (esc.id) return esc.id;
  return `${esc.status}:${esc.question}:${esc.assumption}:${esc.blocking}`;
}

/**
 * 升级实时可见 + 阻塞式求决策 §4.5B: a worker's escalations (`escalate`), rendered by
 * lifecycle `status` rather than a flat list:
 *
 *  - `raised` (非阻塞 `run_escalation`) — the worker flagged a 待决问题 but kept working
 *    under its assumption; the CEO resolves it at synthesis. Read-only here.
 *  - `pending` / `resolved` / `timeout` (阻塞·求决策) — reuse the SAME {@link EscalationCard}
 *    as the assistant bubble so a pending one is 就地可应答 while the turn is live
 *    (`interactive`), then shows the answer / 已按假设继续 / a dormant record once settled.
 */
export function EscalationSection({
  run,
  role,
  conversationId,
  interactive,
}: {
  run: RunNode;
  role: string;
  conversationId: string | null;
  interactive: boolean;
}) {
  return (
    <Section title={`向上升级 (${run.escalations.length})`}>
      <div className="space-y-2">
        {run.escalations.map((esc) =>
          esc.status === "raised" ? (
            <RaisedEscalationRow key={escalationRowKey(esc)} esc={esc} />
          ) : (
            <EscalationCard
              key={escalationRowKey(esc)}
              escalation={esc}
              role={role}
              conversationId={conversationId}
              interactive={interactive}
            />
          ),
        )}
      </div>
    </Section>
  );
}

/** A non-blocking escalation (`run_escalation`): the worker flagged a 待决问题 but kept
 * working under its assumption, so this is read-only — the CEO resolves it at synthesis.
 * A「阻断性」flag marks one where a wrong guess would void the product. */
function RaisedEscalationRow({ esc }: { esc: RunEscalation }) {
  const kindLabel = escalationRowKindLabel(esc);
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-2.5 py-2 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-muted-foreground">
        <ArrowUp size={12} className="shrink-0" />
        <span>向上求决策</span>
        {kindLabel && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-muted-foreground">
            {kindLabel}
          </span>
        )}
        {esc.blocking && (
          <span className="rounded-full bg-destructive/15 px-1.5 py-0.5 text-destructive">
            阻断性
          </span>
        )}
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-foreground">
        {esc.question}
      </p>
      {esc.assumption && (
        <p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">
          <span className="text-muted-foreground/70">暂用假设：</span>
          {esc.assumption}
        </p>
      )}
    </div>
  );
}
