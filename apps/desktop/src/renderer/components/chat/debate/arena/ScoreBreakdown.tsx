import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ChevronDown, TriangleAlert } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { DebateScoreView } from "../model";

/** 三维维度（中性量）：标签短、描述点明各维主看的环节。配色只用 muted/border/foreground，绝不用褒贬色。 */
export const SCORE_DIMENSIONS = [
  {
    key: "argument" as const,
    label: "论点",
    description: "论点强度（立论与续辩的论证质量）",
  },
  {
    key: "engagement" as const,
    label: "回应",
    description: "回应完整度（是否正面回应对方命门与质询）",
  },
  {
    key: "evidence" as const,
    label: "证据",
    description: "证据充分度（举证标记与来源等级）",
  },
] as const;

export type ScoreDimKey = (typeof SCORE_DIMENSIONS)[number]["key"];

/** 净分带符号（+9 / −2 / 0）。 */
export function formatNetTotal(total: number): string {
  if (total > 0) return `+${total}`;
  return String(total);
}

/**
 * 可复用三维拆分展示单元：论点 / 回应 / 证据 + 可选罚分详情。
 * 各记分面（战果对照 / 顶栏弹层 / JudgeNote / 动量 tooltip）复用，勿每处重写。
 */
export function ScoreBreakdown({
  score,
  density = "comfortable",
  penalties = "expandable",
  showTotal = false,
}: {
  score: DebateScoreView;
  density?: "comfortable" | "compact";
  /** expandable=可展开条目；always=常驻列；inline=一行摘要；hidden=不显示 */
  penalties?: "expandable" | "always" | "inline" | "hidden";
  showTotal?: boolean;
}) {
  const compact = density === "compact";
  return (
    <div className={compact ? "space-y-1.5" : "space-y-2"}>
      {showTotal && (
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs text-muted-foreground">净分</span>
          <span className="text-sm font-semibold tabular-nums text-foreground">
            {formatNetTotal(score.total)}
          </span>
        </div>
      )}
      <ul className={compact ? "space-y-1" : "space-y-1.5"}>
        {SCORE_DIMENSIONS.map((dim) => {
          const value = score[dim.key];
          return (
            <li
              key={dim.key}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <span className="text-muted-foreground" title={dim.description}>
                {dim.label}
              </span>
              <span className="shrink-0 font-medium tabular-nums text-foreground">
                {value}
              </span>
            </li>
          );
        })}
      </ul>
      {penalties !== "hidden" && score.penalties.length > 0 && (
        <PenaltyBlock
          penalties={score.penalties}
          mode={penalties === "inline" ? "inline" : penalties}
          compact={compact}
        />
      )}
    </div>
  );
}

function PenaltyBlock({
  penalties,
  mode,
  compact,
}: {
  penalties: string[];
  mode: "expandable" | "always" | "inline";
  compact: boolean;
}) {
  const [open, setOpen] = useState(mode === "always");

  if (mode === "inline") {
    return (
      <p className="text-xs text-muted-foreground">
        <TriangleAlert
          size={11}
          className="mr-0.5 inline -mt-0.5 text-muted-foreground"
        />
        罚分 {penalties.length}：{penalties.join("；")}
      </p>
    );
  }

  if (mode === "always") {
    return (
      <div className={compact ? "space-y-0.5" : "space-y-1"}>
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <TriangleAlert size={11} className="shrink-0" />
          罚分 · {penalties.length}
        </p>
        <ul className="space-y-0.5 pl-4">
          {penalties.map((p) => (
            <li key={p} className="list-disc text-xs text-foreground">
              {p}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <TriangleAlert size={11} className="shrink-0" />
        罚分 · {penalties.length}
        <ChevronDown
          size={12}
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 pl-4">
          {penalties.map((p) => (
            <li key={p} className="list-disc text-xs text-foreground">
              {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * 净分入口：保持一眼可读的数字，点击弹出三维拆分面板。
 * 用于顶栏 Scoreboard（1v1 比分与多方 chip）。
 */
export function ScoreTotalPortal({
  score,
  children,
  side = "bottom",
}: {
  score: DebateScoreView;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-56 p-3" side={side} align="center">
        <p className="mb-2 text-xs font-medium text-foreground">
          {score.name}
          <span className="ml-1.5 tabular-nums text-muted-foreground">
            净 {formatNetTotal(score.total)}
          </span>
        </p>
        <ScoreBreakdown score={score} density="compact" penalties="always" />
      </PopoverContent>
    </Popover>
  );
}

/**
 * 轻量 hover/focus 三维面板（无点击弹层）——用于 JudgeNote 等行内场景。
 */
export function ScoreBreakdownTip({
  score,
  children,
}: {
  score: DebateScoreView;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="max-w-xs p-2.5" side="top">
        <ScoreBreakdown
          score={score}
          density="compact"
          penalties="inline"
          showTotal
        />
      </TooltipContent>
    </Tooltip>
  );
}
