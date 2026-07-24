import { agentColorVar, agentGlyph } from "@/lib/agentIdentity";
import { formatDuration } from "@/lib/format";
import type {
  ActAuthorizedBy,
  ActKind,
  ExecutionStatus,
} from "@/stores/execution";
import { Handle, type NodeProps, Position } from "@xyflow/react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  Pause,
  Sparkles,
  XCircle,
} from "lucide-react";
import { actAuthorizedByLabel } from "./actAuthLabels";

/**
 * 幕摘要卡（批 R2 幕级 LOD）: one act of a multi-act turn folded into ONE node on the
 * collaboration graph's top-level chain. It is the「幕 = 一等视觉单元」rule — the graph
 * shows a chain of these cards and expands exactly one focused act into its full DAG
 * (自相似于画布「恰好一个聚焦回合」LOD). Non-focused acts stay a card; clicking one
 * focuses it.
 *
 * The face intentionally mirrors {@link import("./TurnSummaryNode").TurnSummaryNode}'s
 * stable color/shape convention (status ring + icon, 身份 avatars via
 * {@link agentColorVar}, a count + progress) so a folded act reads the same as a folded
 * turn. Every field is真实可得 run data (title/kind, aggregate status, participants,
 * duration, pending decisions) — never invented.
 */
export interface ActSummaryData {
  actId: string;
  kind: ActKind | null;
  title: string | null;
  authorizedBy: ActAuthorizedBy | null;
  status: ExecutionStatus;
  /** Distinct participant roles, first-seen order — drives the identity avatars. */
  roles: string[];
  agentCount: number;
  completed: number;
  total: number;
  durationMs: number | null;
  /** 图上指挥扫视: unanswered boss decisions folded on this act (待你拍板 chip). */
  pendingDecisions: number;
  /** Recoverable terminal trouble in this act (待救火 chip when no decision pends). */
  recoverable: boolean;
  /** Edge anchor orientation, driven by the active graph layout. */
  handleDirection: "vertical" | "horizontal";
  /** 1-based act number for the「幕 N」eyebrow. */
  index: number;
  /** Click / keyboard activation — focuses this act (expands its DAG). */
  onActivate?: () => void;
  [key: string]: unknown;
}

const STATUS_STYLES: Record<
  ExecutionStatus,
  { ring: string; icon: React.ReactNode }
> = {
  planning: {
    ring: "ring-muted-foreground/30",
    icon: <Sparkles size={14} className="text-muted-foreground" />,
  },
  running: {
    ring: "ring-primary",
    icon: <Loader2 size={14} className="animate-spin text-primary" />,
  },
  paused: {
    ring: "ring-primary",
    icon: <Pause size={14} className="text-primary" />,
  },
  completed: {
    ring: "ring-success",
    icon: <CheckCircle2 size={14} className="text-success" />,
  },
  failed: {
    ring: "ring-destructive",
    icon: <XCircle size={14} className="text-destructive" />,
  },
  cancelled: {
    ring: "ring-muted-foreground/30",
    icon: <XCircle size={14} className="text-muted-foreground" />,
  },
};

const KIND_LABEL: Record<ActKind, string> = {
  multi_agent: "多智能体",
  debate: "辩论",
};

const AVATAR_CAP = 5;

export function ActSummaryNode({ data }: NodeProps) {
  const d = data as ActSummaryData;
  const style = STATUS_STYLES[d.status] ?? STATUS_STYLES.planning;
  const horizontal = d.handleDirection === "horizontal";
  const running = d.status === "running";
  const kindLabel = d.kind ? KIND_LABEL[d.kind] : null;
  const title = d.title?.trim() || kindLabel || `幕 ${d.index}`;
  const eyebrowParts = [`幕 ${d.index}`];
  if (kindLabel) eyebrowParts.push(kindLabel);
  const auth = actAuthorizedByLabel(d.authorizedBy);
  if (auth) eyebrowParts.push(auth);
  const shown = d.roles.slice(0, AVATAR_CAP);
  const overflow = d.roles.length - shown.length;
  const pct = d.total > 0 ? (d.completed / d.total) * 100 : 0;
  const interactive = !!d.onActivate;

  return (
    <>
      <Handle
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        className="!bg-border"
      />
      <div
        {...(interactive
          ? {
              role: "button",
              tabIndex: 0,
              "aria-label": `${title}，${eyebrowParts.join("·")}，展开本幕`,
              onKeyDown: (e: React.KeyboardEvent) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  d.onActivate?.();
                }
              },
            }
          : {})}
        className={`w-[280px] rounded-xl border bg-card px-3.5 py-3 shadow-sm outline-none ring-2 ${style.ring} ${
          running ? "animate-pulse" : ""
        } ${
          interactive
            ? "cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary/60"
            : ""
        }`}
      >
        <div className="flex items-center gap-2">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
            {style.icon}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-muted-foreground">
              {eyebrowParts.join(" · ")}
            </p>
            <p className="min-w-0 truncate text-sm font-medium text-foreground">
              {title}
            </p>
          </div>
          {d.pendingDecisions > 0 ? (
            <span className="flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              <AlertTriangle size={11} />
              待你拍板{d.pendingDecisions > 1 ? ` ${d.pendingDecisions}` : ""}
            </span>
          ) : (
            d.recoverable && (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
                <AlertTriangle size={11} />
                待救火
              </span>
            )
          )}
        </div>

        <div className="mt-2.5 flex items-center gap-1.5">
          {(() => {
            const seen = new Map<string, number>();
            return shown.map((role) => {
              const n = seen.get(role) ?? 0;
              seen.set(role, n + 1);
              return (
                <div
                  key={`${role}:${n}`}
                  title={role}
                  className="flex size-6 items-center justify-center rounded-full text-xs font-semibold"
                  style={{
                    backgroundColor: `color-mix(in oklab, ${agentColorVar(role)} 18%, transparent)`,
                    color: agentColorVar(role),
                  }}
                >
                  {agentGlyph(role)}
                </div>
              );
            });
          })()}
          {overflow > 0 && (
            <div className="flex size-6 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
              +{overflow}
            </div>
          )}
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {d.agentCount} 个 Agent · {d.completed}/{d.total}
          </span>
        </div>

        {d.durationMs != null && d.durationMs > 0 && (
          <div className="mt-2 flex items-center">
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              <Clock size={11} className="shrink-0" />
              用时 {formatDuration(d.durationMs)}
            </span>
          </div>
        )}

        {running && (
          <div className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        className="!bg-border"
      />
    </>
  );
}
