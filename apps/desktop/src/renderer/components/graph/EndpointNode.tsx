import type { RunStatus } from "@/stores/execution";
import { Handle, type NodeProps, Position } from "@xyflow/react";
import {
  CheckCircle2,
  Loader2,
  Sparkles,
  UserRound,
  XCircle,
} from "lucide-react";
import { graphNodeDimClass, useGraphNodeDimmed } from "./graphHover";
import { useTerminalFlash } from "./useTerminalFlash";

/** Which bookend this node is: the synthetic user-input source, or the CEO
 * captain root 汇聚点 (the turn's reply engine, drawn as the team's climax). */
export type EndpointVariant = "input" | "captain";

interface EndpointNodeData {
  variant: EndpointVariant;
  /** Derived captain (汇聚点) status (ignored for the input node). */
  status: RunStatus;
  /** Task summary (input) — kept short, the node clamps to two lines. */
  label: string;
  /** Captain only: tail of the CEO's final answer, clamped to two lines, so
   * the climax node previews the team's deliverable like a worker previews its
   * output. Empty until the captain starts writing the answer. */
  preview?: string;
  /** Edge anchor orientation, driven by the active graph layout. */
  handleDirection?: "vertical" | "horizontal";
  /** Position in the plan, used to stagger the entrance animation. */
  enterIndex?: number;
  /** Lit (full-screen only) when the in-place panel surfaces this endpoint's
   * message — the user's prompt (input) / the CEO's final answer (captain) — so
   * the bookend glows like a drilled worker node. Mirrors AgentNode's `focused`;
   * its single source is the full-screen endpoint view (see GraphView). */
  focused?: boolean;
  /** Captain only: keyboard/mouse activation — jumps to the final answer.
   * Absent on the input node, which stays a passive label. */
  onActivate?: () => void;
  /** Captain only: a11y verb for the activation. Defaults to 查看最终回答. */
  actionLabel?: string;
  /** Captain only: overrides the derived status subtitle (e.g. coordination wait). */
  statusCaption?: string;
  [key: string]: unknown;
}

/** 汇聚点 ring + icon by derived status (mirrors AgentNode's mapping). */
const SINK_STYLES: Record<string, { ring: string; icon: React.ReactNode }> = {
  pending: {
    ring: "ring-muted-foreground/30",
    icon: <Sparkles size={15} className="text-muted-foreground" />,
  },
  running: {
    ring: "ring-primary",
    icon: <Loader2 size={15} className="animate-spin text-primary" />,
  },
  completed: {
    ring: "ring-success",
    icon: <CheckCircle2 size={15} className="text-success" />,
  },
  failed: {
    ring: "ring-destructive",
    icon: <XCircle size={15} className="text-destructive" />,
  },
  cancelled: {
    ring: "ring-muted-foreground/30",
    icon: <XCircle size={15} className="text-muted-foreground" />,
  },
  skipped: {
    ring: "ring-muted-foreground/30",
    icon: <Sparkles size={15} className="text-muted-foreground" />,
  },
};

export function EndpointNode({ data }: NodeProps) {
  const d = data as EndpointNodeData;
  const isInput = d.variant === "input";
  const style = SINK_STYLES[d.status] ?? SINK_STYLES.pending;
  const running = !isInput && d.status === "running";
  const horizontal = d.handleDirection === "horizontal";
  // Both bookends are interactive when given an activation handler: clicking
  // jumps the conversation to the real message they stand in for (the user's
  // prompt / the CEO's answer).
  const interactive = !!d.onActivate;
  // Single highlight source: the full-screen endpoint view (projected into
  // `d.focused` by GraphView). Mirrors AgentNode — a solid primary outline when
  // its prompt / answer is the one showing in the in-place panel.
  const highlighted = d.focused;
  const preview = isInput ? d.label : d.preview;
  // Only the captain node owns a live status; the input node is static, so it
  // never flashes (the hook also self-guards its already-terminal first mount).
  const flashing = useTerminalFlash(d.status) && !isInput;
  const flashColor =
    d.status === "failed" ? "var(--destructive)" : "var(--success)";
  const enterDelay = Math.min((d.enterIndex ?? 0) * 35, 280);
  const dimmed = useGraphNodeDimmed();

  const interactiveProps: React.HTMLAttributes<HTMLDivElement> = interactive
    ? {
        role: "button",
        tabIndex: 0,
        "aria-label": isInput
          ? "你的任务，对话发起，查看完整提问"
          : `CEO 汇总，${d.statusCaption ?? sinkLabel(d.status)}，${d.actionLabel ?? "查看最终回答"}`,
        onKeyDown: (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            d.onActivate?.();
          }
        },
      }
    : {};

  return (
    <>
      <Handle
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        className="!bg-border"
      />
      {/* Entrance wrapper — see AgentNode: keeps the once-on-mount scale/fade off
          the card so it never collides with the card's `animate-pulse`.
          Dim sits outside the entrance wrapper so animation fill-mode cannot
          override hover opacity. */}
      <div className={graphNodeDimClass(dimmed)}>
        <div
          className="animate-graph-node-enter"
          style={{ animationDelay: `${enterDelay}ms` }}
        >
          <div
            {...interactiveProps}
            style={{ "--graph-flash-color": flashColor } as React.CSSProperties}
            className={`w-[210px] rounded-xl border px-3 py-2.5 shadow-sm outline-none ${
              isInput
                ? "border-border bg-muted/40"
                : `bg-card ring-2 ${style.ring}`
            } ${running ? "animate-pulse" : ""} ${flashing ? "animate-graph-node-flash" : ""} ${interactive ? "cursor-pointer" : ""} ${
              highlighted
                ? "outline outline-2 outline-offset-2 outline-primary"
                : interactive
                  ? "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary/60"
                  : ""
            }`}
          >
            <div className="flex items-center gap-2.5">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
                {isInput ? (
                  <UserRound size={16} className="text-muted-foreground" />
                ) : (
                  style.icon
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {isInput ? "你的任务" : "CEO 汇总"}
                </p>
                {/* 端点副标题是描述/汇聚状态（非冗余状态文字）：输入端「对话发起」恒显，
                  CEO 汇总端保留「正在生成汇总…/已汇总」叙事（前端UX设计 §五约定的例外）。
                  与 AgentNode 第二行同节奏（mt-0.5）。 */}
                <p
                  className={`mt-0.5 truncate text-xs ${
                    running ? "text-primary" : "text-muted-foreground"
                  }`}
                  data-testid={isInput ? undefined : "captain-sink-label"}
                >
                  {isInput
                    ? "对话发起"
                    : (d.statusCaption ?? sinkLabel(d.status))}
                </p>
              </div>
            </div>

            {/* 预览取向与 AgentNode 对齐：输入端=任务摘要（task 语义，/70）、CEO 汇总端=
              答案开头或合成预览（output 语义，/80；headText 取开头，见 GraphView）。
              汇总空窗无 content_delta 时挂 team_synthesis_preview 片段，保持节点活性。 */}
            {preview && (
              <p
                className={`mt-2 line-clamp-2 text-xs leading-snug ${
                  isInput
                    ? "text-muted-foreground/70"
                    : running
                      ? "text-foreground/80"
                      : "text-muted-foreground/80"
                }`}
                data-testid={isInput ? undefined : "captain-sink-preview"}
              >
                {preview}
              </p>
            )}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        className="!bg-border"
      />
    </>
  );
}

function sinkLabel(status: RunStatus): string {
  const labels: Record<RunStatus, string> = {
    pending: "待汇总",
    running: "正在生成汇总…",
    completed: "已汇总",
    failed: "失败",
    cancelled: "已停止",
    skipped: "未执行",
  };
  return labels[status] ?? status;
}
