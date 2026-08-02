import { Badge } from "@/components/ui";
import type { DebatePretrialView } from "../model";
import { ModeratorIdentity } from "./ModeratorIdentity";
import {
  DEBATE_SPLIT_GRID,
  type DebateArenaLayout,
  partitionSides,
} from "./debateLayoutPreference";

const SKIP_LABEL: Record<string, string> = {
  fast: "快速档 · 已跳过庭前准备",
  dossier_sufficient: "案卷已充分 · 庭前秒过",
  evidence_pack: "共享证据包已齐 · 跳过外证",
  no_pack: "无共享证据包 · 立论期检索补证",
};

const COMPLETENESS_LABEL: Record<string, string> = {
  full: "完整度 · 齐全",
  partial: "完整度 · 不完整",
  empty: "完整度 · 空",
};

const EXTERNAL_MODE_LABEL: Record<string, string> = {
  skip: "外证 · 已跳过",
};

const STATUS_BADGE: Record<
  string,
  { label: string; tone: "primary" | "success" | "muted" | "destructive" }
> = {
  running: { label: "准备中", tone: "primary" },
  done: { label: "已完成", tone: "success" },
  skipped: { label: "已跳过", tone: "muted" },
  degraded: { label: "已降级", tone: "destructive" },
};

/**
 * 庭前准备区块：组卷 / 证据包轻态 + 可选任务单摘要（无取证员舰队进度）。
 * 开赛后首轮立论前可见；靠 `debate_pretrial_started|completed` 撑住首屏，不依赖调查员事件。
 */
export function PretrialSection({
  pretrial,
  moderatorModel,
  layoutMode = "stack",
}: {
  pretrial: DebatePretrialView;
  moderatorModel?: string | null;
  /** 与立论/质询一致：并排偏好下宽主列左右对照，窄主列自动单栏。 */
  layoutMode?: DebateArenaLayout;
}) {
  const statusMeta = STATUS_BADGE[pretrial.status] ?? STATUS_BADGE.running;
  const skipLine =
    pretrial.status === "skipped" && pretrial.skipReason
      ? (SKIP_LABEL[pretrial.skipReason] ?? "已跳过庭前准备")
      : null;
  // 权威=completed：running 不渲染完整度；缺字段=未知不告警；intentional skip 非失败态。
  const completeness = pretrial.completeness;
  const showCompleteness =
    pretrial.status !== "running" && completeness != null;
  const completenessLine = showCompleteness
    ? (COMPLETENESS_LABEL[completeness] ?? `完整度 · ${completeness}`)
    : null;
  const completenessToneBad =
    pretrial.incomplete === true ||
    (pretrial.incomplete !== false &&
      pretrial.completeness != null &&
      pretrial.completeness !== "full");
  const showIncompleteAlarm =
    pretrial.incomplete === true &&
    pretrial.status !== "running" &&
    !pretrial.skipReason;
  const externalLine = pretrial.externalEvidenceMode
    ? (EXTERNAL_MODE_LABEL[pretrial.externalEvidenceMode] ??
      `外证 · ${pretrial.externalEvidenceMode}`)
    : null;
  const useSplit = layoutMode === "split" && pretrial.sides.length === 2;
  const subtitle =
    pretrial.status === "running"
      ? "组装共享证据包"
      : pretrial.evidenceReady
        ? "证据已就绪"
        : "庭前准备";

  return (
    <div className="space-y-3">
      <div className="mt-1 border-t border-border pt-3 text-center">
        <h4 className="text-base font-semibold text-foreground">庭前准备</h4>
        <p className="mt-1 flex flex-wrap items-center justify-center gap-1.5 text-xs text-muted-foreground">
          <ModeratorIdentity
            model={moderatorModel}
            gavelSize={13}
            className="text-xs"
          />
          <span>{subtitle}</span>
          <Badge tone={statusMeta.tone}>{statusMeta.label}</Badge>
          {pretrial.evidenceLedgerCount > 0 ? (
            <Badge tone="muted">台账 {pretrial.evidenceLedgerCount} 条</Badge>
          ) : null}
          {completenessLine ? (
            <Badge tone={completenessToneBad ? "destructive" : "success"}>
              {completenessLine}
            </Badge>
          ) : null}
          {externalLine ? <Badge tone="muted">{externalLine}</Badge> : null}
        </p>
        {skipLine ? (
          <p className="mt-1 text-xs text-muted-foreground">{skipLine}</p>
        ) : null}
        {showIncompleteAlarm ? (
          <p className="mt-1 text-xs text-muted-foreground">证据不完整</p>
        ) : null}
        {pretrial.status === "degraded" && pretrial.fallbackSelfSearch ? (
          <p className="mt-1 text-xs text-muted-foreground">
            庭前未齐 · 将回退辩手立论自检索
          </p>
        ) : null}
      </div>

      {pretrial.sides.length > 0 && pretrial.status !== "skipped" ? (
        useSplit ? (
          <SplitPretrialColumns sides={pretrial.sides} />
        ) : (
          <div className="space-y-2">
            {pretrial.sides.map((side) => (
              <SideBlock key={side.sideKey} side={side} />
            ))}
          </div>
        )
      ) : null}
    </div>
  );
}

function SplitPretrialColumns({
  sides,
}: {
  sides: DebatePretrialView["sides"];
}) {
  const { pro, con, others } = partitionSides(sides, (s) => s.sideKey);
  return (
    <div className="space-y-2">
      <div className={DEBATE_SPLIT_GRID}>
        <div className="min-w-0">{pro ? <SideBlock side={pro} /> : null}</div>
        <div className="min-w-0">{con ? <SideBlock side={con} /> : null}</div>
      </div>
      {others.map((side) => (
        <SideBlock key={side.sideKey} side={side} />
      ))}
    </div>
  );
}

function SideBlock({
  side,
}: {
  side: DebatePretrialView["sides"][number];
}) {
  const progressLabel =
    side.tasks.length > 0
      ? `${side.tasks.length} 项任务`
      : side.preparing
        ? "组卷中"
        : "已就绪";

  return (
    <div
      className="min-w-0 rounded-xl border border-border bg-muted/30 px-3 py-2"
      style={{ borderLeftColor: side.colorVar, borderLeftWidth: 3 }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-foreground">{side.name}</span>
        {side.preparing ? <Badge tone="primary">准备中</Badge> : null}
        {!side.preparing && side.tasks.length > 0 ? (
          <Badge tone="success">完成</Badge>
        ) : null}
        <span className="text-xs text-muted-foreground">{progressLabel}</span>
      </div>
      {side.tasks.length > 0 ? (
        <ul className="mt-1.5 space-y-1 text-xs leading-snug text-muted-foreground">
          {side.tasks.map((t) => (
            <li key={t.query} className="break-words">
              {t.purpose ? `${t.purpose} · ` : ""}
              {t.query}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
