import { buildModeratorLedger } from "@/components/chat/detail/debateModerator";
import { Badge } from "@/components/ui";
import { useStreamAwareDisclosure } from "@/stores/disclosure";
import { type Execution, isDebate } from "@/stores/execution";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * 聊天默认面「认知推进线」：逐轮焦点 · 裁判小结骨架摘要。
 * 数据来自既有 debateRounds / debate_result 投影（{@link buildModeratorLedger}），
 * 不内联发言全文、不渲染记分（守过程归辩论室 + live 不亮分）。
 */
export function DebateProgressLine({
  execution,
  disclosureKey,
}: {
  execution: Execution;
  disclosureKey: string;
}) {
  const ledger = isDebate(execution) ? buildModeratorLedger(execution) : null;
  const live = execution.status === "running" || execution.status === "paused";
  const [expanded, toggle] = useStreamAwareDisclosure(disclosureKey, live);

  if (!ledger || ledger.rounds.length === 0) return null;

  const latest = ledger.rounds[ledger.rounds.length - 1];
  const collapsedHint = formatRoundHint(latest);

  return (
    <div
      className="border-t border-border px-4 py-2"
      data-testid="debate-progress-line"
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left"
        onClick={toggle}
        aria-expanded={expanded}
        aria-label={expanded ? "收起推进线" : "展开推进线"}
      >
        {expanded ? (
          <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={13} className="shrink-0 text-muted-foreground" />
        )}
        <Badge tone="primary" pill className="font-medium">
          推进线 {ledger.rounds.length}
        </Badge>
        {!expanded && collapsedHint && (
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            {collapsedHint}
          </span>
        )}
      </button>

      {expanded && (
        <ol className="mt-2 space-y-1.5 pl-0.5">
          {ledger.rounds.map((round) => (
            <li
              key={round.roundNo}
              className="text-xs leading-relaxed"
              data-testid={`debate-progress-round-${round.roundNo}`}
            >
              <div className="flex items-center gap-1.5">
                <span className="font-medium text-foreground">
                  {round.roundNo > 0 ? `第 ${round.roundNo} 轮` : "本场"}
                </span>
                {round.inFlight && <span className="text-primary">进行中</span>}
              </div>
              {round.focus ? (
                <p className="text-foreground">
                  <span className="text-muted-foreground">焦点 · </span>
                  {round.focus}
                </p>
              ) : round.inFlight ? (
                <p className="text-muted-foreground">等待焦点…</p>
              ) : null}
              {round.summary ? (
                <p className="text-muted-foreground">
                  <span className="text-foreground/80">小结 · </span>
                  {round.summary}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatRoundHint(round: {
  roundNo: number;
  focus: string;
  summary: string;
  inFlight: boolean;
}): string {
  const label = round.roundNo > 0 ? `第 ${round.roundNo} 轮` : "本场";
  if (round.inFlight && !round.focus) return `${label} · 进行中`;
  if (round.focus && round.summary) {
    return `${label} · ${round.focus} · ${round.summary}`;
  }
  if (round.focus) return `${label} · ${round.focus}`;
  if (round.summary) return `${label} · ${round.summary}`;
  return label;
}
