import { formatCrossModelRosterLine } from "@/components/chat/debate/model";
import { shouldHostPreviewInGraph } from "@/components/chat/debatePreviewPlacement";
import {
  ResolvedDecisionRecord,
  teamPendingMarkerLabel,
  teamResolvedOutcome,
} from "@/components/chat/decision";
import { Button } from "@/components/ui";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { TeamPreviewDisplay } from "@/stores/conversation";
import { useMessageExecution } from "@/stores/execution";
import { PendingDecisionMarker } from "./PendingDecisionMarker";

/**
 * Inline team_preview card — thin preflight before fan-out / moderator start.
 * Actionable surface is the durable ResumePrompt (挂起即收口). 方案 C（一个焦点 +
 * 一个入口）: inline pending is a single-line {@link PendingDecisionMarker} — the
 * full 分工表 / 辩题立场 live on the ResumePrompt 拍板中心; resolved keeps its
 * settled trace (collapsed one-line conclusion; expand for plan details + note),
 * same posture as PlanReviewCard.
 *
 * Branches on ``primitive``: delegate = 队员分工表; debate = 辩题 / 立场 / 轮次预算.
 *
 * Resolved + team already started: content hosts in {@link GraphTeamPreview}
 * on the inline StatusStrip (see {@link shouldHostPreviewInGraph}); this card
 * returns null so the timeline does not keep a spare card slot.
 *
 * Resolved copy / icons come from the shared decision meta ({@link TEAM_PRIMITIVE_META}).
 */
export function TeamPreviewCard({
  preview,
  messageId,
}: {
  preview: TeamPreviewDisplay;
  /** Assistant message id — used to gate resolved embed into the graph. */
  messageId?: string;
}) {
  const execution = useMessageExecution(messageId ?? null);
  if (shouldHostPreviewInGraph(preview, execution?.runs)) {
    return null;
  }
  if (preview.status === "resolved") {
    return <ResolvedTeamPreview preview={preview} />;
  }
  return (
    <PendingDecisionMarker
      label={teamPendingMarkerLabel(preview.primitive, summarySuffix(preview))}
    />
  );
}

function isDebate(preview: TeamPreviewDisplay): boolean {
  return preview.primitive === "debate";
}

function summarySuffix(preview: TeamPreviewDisplay): string {
  if (isDebate(preview)) {
    const n = preview.sides.length;
    return n > 0 ? `${n} 方` : "辩论";
  }
  return `${preview.workers.length} 名队员`;
}

export function WorkerRows({ preview }: { preview: TeamPreviewDisplay }) {
  return (
    <div className="mt-2 space-y-1.5">
      {preview.workers.map((w) => (
        <div
          key={w.run_id}
          className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="text-xs font-medium text-foreground">{w.role}</p>
            {w.write_capability_label && (
              <span
                className={
                  w.write_capability === "text_only"
                    ? "text-xs font-medium text-muted-foreground"
                    : "text-xs text-muted-foreground"
                }
              >
                {w.write_capability_label}
              </span>
            )}
            {w.debate && (
              <span className="text-xs text-muted-foreground">辩论</span>
            )}
            {w.depends_on.length > 0 && (
              <span className="text-xs text-muted-foreground">
                依赖 {w.depends_on.length} 步
              </span>
            )}
          </div>
          {w.task && (
            <p className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">
              {w.task}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/** Debate motion / round budget / sides — shared by standalone card and graph header. */
export function DebateBody({ preview }: { preview: TeamPreviewDisplay }) {
  const budget =
    preview.maxRounds > 0
      ? preview.thorough
        ? `认真辩透 · 上限 ${preview.maxRounds} 轮`
        : `快速对碰 · ${preview.maxRounds} 轮`
      : preview.thorough
        ? "认真辩透"
        : "快速对碰";

  const rosterLine = formatCrossModelRosterLine(preview.sides, {
    model: preview.moderatorModel,
    origin: preview.moderatorOrigin,
  });

  return (
    <div className="mt-2 space-y-1.5">
      {preview.motion && (
        <p className="whitespace-pre-wrap text-xs text-foreground">
          {preview.motion}
        </p>
      )}
      <p className="text-xs text-muted-foreground">{budget}</p>
      {rosterLine && (
        <p
          className="text-xs text-muted-foreground"
          data-testid="debate-roster-line"
        >
          {rosterLine}
        </p>
      )}
      {preview.sameModelDebate && (
        <p className="text-xs text-muted-foreground">同模型辩论</p>
      )}
      {preview.modelCandidates && preview.modelCandidates.length > 0 && (
        <div
          className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
          data-testid="debate-model-candidates"
        >
          <p className="text-xs font-medium text-foreground">
            模型消歧失败 · 请从目录候选重选（勿再问「是不是当前主模型」）
          </p>
          <ul className="mt-1 space-y-0.5">
            {preview.modelCandidates.map((c, i) => (
              <li
                key={`${c.origin}-${c.model}-${c.provider_id ?? ""}-${i}`}
                className="text-xs text-muted-foreground"
              >
                {c.label || c.model}
                {" · "}
                {c.origin}/{c.model}
                {c.provider_id ? `（provider=${c.provider_id}）` : ""}
                {c.side_key ? ` · ${c.side_key}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {preview.sides.map((s) => (
        <div
          key={s.key}
          className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="text-xs font-medium text-foreground">{s.name}</p>
            {s.is_subject && (
              <span className="text-xs text-muted-foreground">方案方</span>
            )}
          </div>
          {s.stance && (
            <p className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">
              {s.stance}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function graphPreviewSummary(preview: TeamPreviewDisplay): string {
  if (isDebate(preview)) {
    const n = preview.sides.length;
    return n > 0 ? `辩题 · ${n} 方` : "辩题";
  }
  const n = preview.workers.length;
  return n > 0 ? `分工 · ${n} 名队员` : "分工";
}

/**
 * Secondary ghost control for StatusStrip — Popover hosts 辩题 / 分工 details
 * (DebateBody / WorkerRows + optional note). No DecisionCard shell; does not
 * navigate to the debate room. Mounted only on the inline StatusStrip path.
 */
export function GraphTeamPreview({
  preview,
}: {
  preview: TeamPreviewDisplay;
}) {
  const summary = graphPreviewSummary(preview);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          className="ml-0.5 shrink-0 text-muted-foreground hover:text-foreground"
          data-testid="graph-team-preview"
        >
          {summary}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-3 [&>*:first-child]:mt-0">
        {isDebate(preview) ? (
          <DebateBody preview={preview} />
        ) : (
          <WorkerRows preview={preview} />
        )}
        {preview.note && (
          <p className="mt-1.5 whitespace-pre-wrap rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-foreground">
            {preview.note}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}

function ResolvedTeamPreview({ preview }: { preview: TeamPreviewDisplay }) {
  const decision = preview.decision ?? "timeout";
  const meta = teamResolvedOutcome(
    preview.primitive,
    decision,
    Boolean(preview.note?.trim()),
  );
  const summary = `${meta.label} · ${summarySuffix(preview)}`;

  return (
    <ResolvedDecisionRecord
      layout="neutralCollapsible"
      disclosureKey={`team-preview:${preview.id}`}
      icon={meta.icon}
      summary={summary}
    >
      {isDebate(preview) ? (
        <DebateBody preview={preview} />
      ) : (
        <WorkerRows preview={preview} />
      )}
      {preview.note && (
        <p className="mt-1.5 whitespace-pre-wrap rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-foreground">
          {preview.note}
        </p>
      )}
    </ResolvedDecisionRecord>
  );
}
