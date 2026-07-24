import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { DebateRoundModel } from "../model";
import { ScoreBreakdown, formatNetTotal } from "./ScoreBreakdown";

/** 逐轮各方得分小条（chess.com 评估条风格）。无记分轮隐藏。 */
export function MomentumChart({
  rounds,
  sideKeys,
  colorByKey,
  nameByKey,
}: {
  rounds: DebateRoundModel[];
  sideKeys: string[];
  colorByKey: Record<string, string>;
  nameByKey?: Record<string, string>;
}) {
  const scored = rounds.filter((r) => r.scores.length > 0);
  if (scored.length === 0 || sideKeys.length === 0) return null;

  const maxAbs = Math.max(
    1,
    ...scored.flatMap((r) => r.scores.map((s) => Math.abs(s.total))),
  );

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-end gap-0.5" aria-label="逐轮得分动量">
        {scored.map((r) => (
          <Tooltip key={r.roundNo}>
            <TooltipTrigger asChild>
              <div className="flex cursor-default flex-col items-center gap-0.5">
                <div className="flex h-6 items-end gap-px">
                  {sideKeys.map((key) => {
                    const score = r.scores.find((s) => s.sideKey === key);
                    const val = score?.total ?? 0;
                    const h =
                      val !== 0
                        ? Math.max(2, (Math.abs(val) / maxAbs) * 24)
                        : 2;
                    return (
                      <span
                        key={key}
                        className="w-1.5 rounded-lg"
                        style={{
                          height: h,
                          backgroundColor: colorByKey[key],
                          opacity: val === 0 ? 0.25 : 1,
                        }}
                      />
                    );
                  })}
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs p-2.5">
              <RoundMomentumTip roundNo={r.roundNo} scores={r.scores} />
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
      {nameByKey && (
        <MomentumLegend
          sideKeys={sideKeys}
          colorByKey={colorByKey}
          nameByKey={nameByKey}
        />
      )}
    </div>
  );
}

function RoundMomentumTip({
  roundNo,
  scores,
}: {
  roundNo: number;
  scores: DebateRoundModel["scores"];
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-foreground">第 {roundNo} 轮</p>
      {scores.map((s) => (
        <div
          key={s.sideKey}
          className="space-y-1 border-t border-border pt-1.5 first:border-0 first:pt-0"
        >
          <p className="flex items-center gap-1.5 text-xs">
            <span
              className="size-1.5 shrink-0 rounded-full"
              style={{ backgroundColor: s.colorVar }}
            />
            <span className="font-medium text-foreground">{s.name}</span>
            <span className="tabular-nums text-muted-foreground">
              净 {formatNetTotal(s.total)}
            </span>
          </p>
          <ScoreBreakdown
            score={s}
            density="compact"
            penalties={s.penalties.length > 0 ? "inline" : "hidden"}
          />
        </div>
      ))}
    </div>
  );
}

function MomentumLegend({
  sideKeys,
  colorByKey,
  nameByKey,
}: {
  sideKeys: string[];
  colorByKey: Record<string, string>;
  nameByKey: Record<string, string>;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-x-2 gap-y-0.5"
      aria-label="动量图例"
    >
      {sideKeys.map((key) => (
        <span
          key={key}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground"
        >
          <span
            className="size-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: colorByKey[key] }}
          />
          {nameByKey[key] ?? key}
        </span>
      ))}
    </div>
  );
}
