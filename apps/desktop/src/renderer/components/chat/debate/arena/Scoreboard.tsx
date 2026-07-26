import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { Button } from "@/components/ui";
import { useDebateTake, useDebateUserTake } from "@/stores/debateUserTake";
import { Hand } from "lucide-react";
import { ModelBadge } from "../ModelBadge";
import { FINDING_STATUS, findingStatusCounts, gateLabel } from "../findings";
import {
  type DebateModel,
  type DebateScoreView,
  debateRoster,
  debateSideColorVar,
  modelVendorLabel,
  stopLabel,
  tallyScores,
} from "../model";
import {
  RISK_LEVELS,
  RISK_SEVERITY,
  buildRiskItems,
  riskCounts,
} from "../severity";
import { HowToReadPopover } from "./HowToReadPopover";
import { MomentumChart } from "./MomentumChart";
import { ScoreTotalPortal, formatNetTotal } from "./ScoreBreakdown";
import {
  closingAnchorId,
  finaleAnchorId,
  roundAnchorId,
  steeringAnchorId,
} from "./anchors";
import {
  DEBATE_ARENA_PAGE_MAX,
  type DebateArenaLayout,
} from "./debateLayoutPreference";

export function Scoreboard({
  model,
  messageId,
  hasPendingSteering,
  onScrollTo,
  canSplit,
  layoutMode,
  onLayoutChange,
}: {
  model: DebateModel;
  messageId: string;
  hasPendingSteering: boolean;
  onScrollTo: (anchorId: string) => void;
  canSplit?: boolean;
  layoutMode?: DebateArenaLayout;
  onLayoutChange?: (mode: DebateArenaLayout) => void;
}) {
  const motion = model.motion ?? model.rounds[0]?.focus ?? "辩论";
  const tally = model.form === "roundtable" ? [] : tallyScores(model.rounds);
  const roster = debateRoster(model.rounds);
  const isVersus = model.form === "debate" && roster.length === 2;
  const liveRound = model.rounds.find((r) => r.inFlight);
  const currentRoundNo = liveRound?.roundNo ?? model.rounds.length;
  const totalRounds = model.rounds.length;

  const chapters: { id: string; label: string }[] = model.rounds.map((r) => ({
    id: roundAnchorId(r.roundNo),
    label: `第${r.roundNo}轮`,
  }));
  if (model.settled && model.closings.length > 0) {
    chapters.push({ id: closingAnchorId(), label: "结辩" });
  }
  if (model.settled) {
    chapters.push({ id: finaleAnchorId(), label: "终审" });
  }

  return (
    <div className="border-b border-border">
      <div className={`mx-auto ${DEBATE_ARENA_PAGE_MAX} px-1 py-3`}>
        <div className="flex flex-wrap items-start gap-2">
          <p
            className="min-w-0 flex-1 basis-48 truncate text-base font-medium text-foreground"
            title={motion}
          >
            {motion}
          </p>
          <div className="flex max-w-full shrink-0 flex-wrap items-center justify-end gap-2">
            {hasPendingSteering && (
              <Button
                variant="neutral"
                size="sm"
                onClick={() => onScrollTo(steeringAnchorId())}
                icon={<Hand size={13} />}
              >
                掌舵
              </Button>
            )}
            <StatusLine
              model={model}
              liveRound={liveRound}
              currentRoundNo={currentRoundNo}
              totalRounds={totalRounds}
            />
            <HowToReadPopover form={model.form} />
            <ManualHelpLink to={MANUAL_HELP.debate} />
          </div>
        </div>

        <div className="mt-2">
          <ScoreboardRow2
            model={model}
            tally={tally}
            roster={roster}
            isVersus={isVersus}
            messageId={messageId}
          />
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {canSplit && layoutMode && onLayoutChange && (
            <LayoutToggle mode={layoutMode} onChange={onLayoutChange} />
          )}
          <MomentumChart
            rounds={model.rounds}
            sideKeys={roster.map((r) => r.sideKey)}
            colorByKey={Object.fromEntries(
              roster.map((r) => [
                r.sideKey,
                debateSideColorVar(r.sideKey, r.name),
              ]),
            )}
            nameByKey={Object.fromEntries(
              roster.map((r) => [r.sideKey, r.name]),
            )}
          />
          <div className="flex flex-1 flex-wrap gap-1">
            {chapters.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onScrollTo(c.id)}
                className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground"
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusLine({
  model,
  liveRound,
  currentRoundNo,
  totalRounds,
}: {
  model: DebateModel;
  liveRound: DebateModel["rounds"][number] | undefined;
  currentRoundNo: number;
  totalRounds: number;
}) {
  if (model.settled) {
    return (
      <span className="shrink-0 text-xs text-muted-foreground">
        {stopLabel(model.stopReason)}
      </span>
    );
  }

  const speaking = liveRound?.sides.find((s) => s.run?.status === "running");
  const phase = speaking
    ? `${speaking.name}正在${currentRoundNo <= 1 ? "立论" : "续辩"}`
    : liveRound?.crossExam.length
      ? "质询进行中"
      : `第 ${currentRoundNo}/${totalRounds} 轮`;

  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
      <span className="size-1.5 animate-pulse rounded-full bg-primary" />
      {phase}
    </span>
  );
}

function ScoreboardRow2({
  model,
  tally,
  roster,
  isVersus,
  messageId,
}: {
  model: DebateModel;
  tally: DebateScoreView[];
  roster: ReturnType<typeof debateRoster>;
  isVersus: boolean;
  messageId: string;
}) {
  if (model.form === "roundtable" && model.sides) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        {model.sides.map((s) => (
          <span
            key={s.key}
            className="inline-flex items-center gap-1.5 text-sm text-foreground"
          >
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: debateSideColorVar(s.key, s.name) }}
            />
            {s.name}
          </span>
        ))}
      </div>
    );
  }

  if (model.form === "red_team" && model.sides) {
    const subject = model.sides.find((s) => s.is_subject);
    const briefFindings = model.brief?.findings ?? [];
    const liveFindings = model.rounds.flatMap((r) => r.findings);
    const findings = briefFindings.length > 0 ? briefFindings : liveFindings;
    const hasFindings = findings.length > 0;
    const risks =
      !hasFindings && model.brief
        ? buildRiskItems(model.sides, model.brief)
        : [];
    const riskTally = riskCounts(risks);
    const statusTally = findingStatusCounts(
      findings.map((f) => ({ status: f.status })),
    );
    const gate = gateLabel(model.brief?.gate);
    return (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {subject && (
            <span>
              <span className="text-muted-foreground">方案方 </span>
              <span className="font-medium">{subject.name}</span>
            </span>
          )}
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">
            红队 {roster.filter((r) => r.sideKey !== subject?.key).length} 人
          </span>
          {gate && (
            <>
              <span className="text-muted-foreground">·</span>
              <span className="font-medium text-foreground">{gate}</span>
            </>
          )}
        </div>
        {hasFindings ? (
          <div className="flex flex-wrap gap-1">
            {(
              [
                "escalated",
                "open",
                "unanswered",
                "answered",
                "deadlocked",
                "closed",
              ] as const
            )
              .filter((s) => (statusTally[s] ?? 0) > 0)
              .map((s) => (
                <span key={s} className={FINDING_STATUS[s].pill}>
                  {FINDING_STATUS[s].label} {statusTally[s]}
                </span>
              ))}
          </div>
        ) : (
          model.settled && (
            <div className="flex gap-1">
              {RISK_LEVELS.filter((l) => riskTally[l] > 0).map((l) => (
                <span key={l} className={RISK_SEVERITY[l].pill}>
                  {RISK_SEVERITY[l].label} {riskTally[l]}
                </span>
              ))}
            </div>
          )
        )}
      </div>
    );
  }

  if (isVersus && tally.length >= 2 && model.sides) {
    const proSide = model.sides.find((s) => s.stance === "pro");
    const conSide = model.sides.find((s) => s.stance === "con");
    const proRoster = proSide
      ? roster.find((r) => r.sideKey === proSide.key)
      : roster[0];
    const conRoster = conSide
      ? roster.find((r) => r.sideKey === conSide.key)
      : roster[1];
    const proKey = proSide?.key ?? proRoster?.sideKey ?? tally[0].sideKey;
    const conKey = conSide?.key ?? conRoster?.sideKey ?? tally[1].sideKey;
    const proScore = tally.find((s) => s.sideKey === proKey) ?? tally[0];
    const conScore = tally.find((s) => s.sideKey === conKey) ?? tally[1];
    const proModel = sideRunModel(model, proKey);
    const conModel = sideRunModel(model, conKey);
    return (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <VersusSide
          name={proRoster?.name ?? proScore.name}
          model={proModel}
          colorVar={debateSideColorVar(
            proRoster?.sideKey ?? proScore.sideKey,
            proRoster?.name ?? proScore.name,
          )}
          align="left"
        />
        <span className="inline-flex items-baseline gap-1 text-xl font-semibold tabular-nums text-foreground">
          <ScoreTotalPortal score={proScore}>
            <button
              type="button"
              className="rounded-lg px-1 hover:bg-muted/50"
              aria-label={`${proScore.name}净分构成`}
            >
              {proScore.total}
            </button>
          </ScoreTotalPortal>
          <span className="text-muted-foreground">：</span>
          <ScoreTotalPortal score={conScore}>
            <button
              type="button"
              className="rounded-lg px-1 hover:bg-muted/50"
              aria-label={`${conScore.name}净分构成`}
            >
              {conScore.total}
            </button>
          </ScoreTotalPortal>
        </span>
        <VersusSide
          name={conRoster?.name ?? conScore.name}
          model={conModel}
          colorVar={debateSideColorVar(
            conRoster?.sideKey ?? conScore.sideKey,
            conRoster?.name ?? conScore.name,
          )}
          align="right"
        />
        <StanceControl turnId={messageId} model={model} />
      </div>
    );
  }

  // 3+ 方 debate：紧凑 chip 累计分（唯一顶栏累计出口；1v1 走上方对阵式）
  if (model.form === "debate" && tally.length > 0) {
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {tally.map((s) => (
          <ScoreTotalPortal key={s.sideKey} score={s}>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs text-foreground hover:bg-muted/40"
              aria-label={`${s.name}净分构成`}
            >
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: s.colorVar }}
              />
              <span className="font-medium">{s.name}</span>
              <span className="font-semibold tabular-nums">
                {formatNetTotal(s.total)}
              </span>
              {s.penalties.length > 0 && (
                <span className="text-muted-foreground">·罚</span>
              )}
            </button>
          </ScoreTotalPortal>
        ))}
      </div>
    );
  }

  return null;
}

/** 从各轮发言格取某方的实际执行 model（run.model），忽略 roster 声称的 per-side model。 */
function sideRunModel(model: DebateModel, sideKey: string): string | undefined {
  for (const round of model.rounds) {
    const side = round.sides.find((s) => s.sideKey === sideKey);
    if (side?.model) return side.model;
  }
  return undefined;
}

function VersusSide({
  name,
  model,
  colorVar,
  align,
}: {
  name: string;
  model?: string;
  colorVar: string;
  align: "left" | "right";
}) {
  const vendor = modelVendorLabel(model);
  return (
    <div
      className={`flex min-w-0 items-center gap-2 text-sm ${align === "right" ? "flex-row-reverse text-right" : ""}`}
    >
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: colorVar }}
      />
      <span className="font-medium text-foreground">{name}</span>
      {vendor && <ModelBadge model={model ?? ""} />}
    </div>
  );
}

function LayoutToggle({
  mode,
  onChange,
}: {
  mode: DebateArenaLayout;
  onChange: (mode: DebateArenaLayout) => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      <span className="text-xs text-muted-foreground">布局</span>
      <div className="flex rounded-lg border border-border p-0.5">
        {(
          [
            { key: "split" as const, label: "并排" },
            { key: "stack" as const, label: "单栏" },
          ] as const
        ).map(({ key, label }) => {
          const active = mode === key;
          return (
            <button
              key={key}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(key)}
              className={`rounded-lg px-2 py-0.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StanceControl({
  turnId,
  model,
}: {
  turnId: string;
  model: DebateModel;
}) {
  const stance = useDebateTake(turnId).stance;
  const setStance = useDebateUserTake((s) => s.setStance);
  const proSideInfo = model.sides?.find((s) => s.stance === "pro");
  const conSideInfo = model.sides?.find((s) => s.stance === "con");
  if (!proSideInfo || !conSideInfo) return null;

  return (
    <div className="flex w-full items-center gap-1 sm:ml-auto sm:w-auto">
      <span className="text-xs text-muted-foreground">你站</span>
      <div className="flex rounded-lg border border-border p-0.5">
        {[
          { key: proSideInfo.key, label: "正方" },
          { key: conSideInfo.key, label: "反方" },
        ].map(({ key, label }) => {
          const active = stance === key;
          return (
            <button
              key={key}
              type="button"
              aria-pressed={active}
              onClick={() => setStance(turnId, active ? null : key)}
              className={`rounded-lg px-2 py-0.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
