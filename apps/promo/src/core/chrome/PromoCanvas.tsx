import { agentColorVar, agentGlyph } from "@/lib/agentIdentity";
import type { Edge, Node } from "@xyflow/react";
import {
  AlertTriangle,
  ArrowUp,
  CheckCircle2,
  ClipboardCheck,
  Cloud,
  ListChecks,
  Loader2,
  Maximize,
  Maximize2,
  MessageSquare,
  Minus,
  PanelRight,
  Pause,
  Plus,
  X,
} from "lucide-react";
import type { DebateState } from "../graph/graphState";
import { GraphStage } from "../graph/GraphStage";

/*
 * 领衔 promo still — the product's 对话级画布 (Canvas view), re-stated the same way
 * PromoShell re-states the app shell: a pixel-faithful static copy of the real
 * ConversationCanvas markup (slim 画布 header + 视图切换/侧栏 floating chrome + a top→
 * bottom turn spine + the 常驻命令栏 + the right-docked 图上指挥 指挥台), with one TEAM
 * turn focused and expanded IN PLACE into its full worker DAG via the real GraphStage
 * (reused butterfly, running + glow). It answers "this is a real product", "a real
 * team is alive in it", AND "you command that team" — the三连 the chat-only crops miss.
 *
 * The spine cards mirror SimpleTurnNode / TurnSummaryNode; the focused card mirrors
 * FocusedTurnNode; the right rail mirrors CanvasDecisionPanel (指挥台, 计划复核 + 工作者
 * 上报); the bottom bar mirrors CanvasCommandBar. Bottom-anchored so the focused turn
 * sits low (above the bar, under a spotlight) with earlier turns climbing into the
 * header — the same latest-turn camera the real canvas parks on.
 *
 * Demo task title / graph snapshot / bbox come from the caller (video or still
 * package) — core does not import videos/.
 */

const FOCUS_W = 860;
const FOCUS_HEADER_H = 38;
const FOCUS_INFO_H = 30;
const FOCUS_BODY_H = 430;

// Faint dot grid matching the canvas surface (and the embedded graph's own backdrop),
// so the focused card body reads as part of the same surface. Token-only color.
const DOT_GRID: React.CSSProperties = {
  backgroundImage:
    "radial-gradient(color-mix(in oklab, var(--foreground) 8%, transparent) 1px, transparent 1px)",
  backgroundSize: "16px 16px",
};

type TurnStatus = "completed" | "running" | "paused";

interface SummaryCard {
  kind: "team";
  taskSummary: string;
  status: TurnStatus;
  roles: string[];
  agentCount: number;
  completed: number;
  total: number;
}
interface SimpleCard {
  kind: "simple";
  prompt: string;
  answer: string;
}
type SpineCard = SummaryCard | SimpleCard;

// A believable conversation history climbing into the focused 多方论证 turn (oldest →
// newest); the latest team turn (DEMO_TASK) is the focused one drawn below the spine.
// The 已暂停 budget turn ties to the 指挥台's 成本分析 上报 (waiting on a budget cap).
const SPINE: SpineCard[] = [
  {
    kind: "simple",
    prompt: "这个产品到底想解决什么核心问题？",
    answer: "聚焦多 Agent 团队真正协作，而非单 Agent 派发子任务……",
  },
  {
    kind: "team",
    taskSummary: "梳理技术可行性与选型空间",
    status: "completed",
    roles: ["技术预研", "风险评估"],
    agentCount: 2,
    completed: 2,
    total: 2,
  },
  {
    kind: "simple",
    prompt: "先看看这个方向有没有人认真做过",
    answer: "已扫描，主要有两类玩家，均未真正打通多 Agent 团队协作……",
  },
  {
    kind: "team",
    taskSummary: "调研用户痛点并排出优先级",
    status: "completed",
    roles: ["用户调研", "竞品分析", "技术趋势"],
    agentCount: 3,
    completed: 3,
    total: 3,
  },
  {
    kind: "simple",
    prompt: "把竞品那部分再展开讲讲",
    answer: "竞品 A 偏协作、B 偏自动化，定价与能力边界对比见下……",
  },
  {
    kind: "team",
    taskSummary: "按里程碑拆出第一版范围",
    status: "completed",
    roles: ["产品经理", "架构师", "交互设计"],
    agentCount: 3,
    completed: 3,
    total: 3,
  },
  {
    kind: "team",
    taskSummary: "试算三档预算与里程碑节奏",
    status: "paused",
    roles: ["成本分析", "产品经理"],
    agentCount: 2,
    completed: 1,
    total: 2,
  },
];

function Avatar({ role }: { role: string }) {
  return (
    <div
      className="flex size-6 items-center justify-center rounded-full text-xs font-semibold"
      style={{
        backgroundColor: `color-mix(in oklab, ${agentColorVar(role)} 18%, transparent)`,
        color: agentColorVar(role),
      }}
    >
      {agentGlyph(role)}
    </div>
  );
}

function Spine() {
  return <div className="h-6 w-px bg-border" />;
}

function SimpleTurnCard({ card }: { card: SimpleCard }) {
  return (
    <div className="w-[320px] rounded-xl border border-border bg-muted/30 px-3.5 py-3 shadow-sm">
      <div className="flex items-center gap-2">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
          <MessageSquare size={14} className="text-muted-foreground" />
        </div>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {card.prompt}
        </p>
      </div>
      <p className="mt-2 line-clamp-2 text-xs leading-snug text-muted-foreground">
        {card.answer}
      </p>
    </div>
  );
}

const TEAM_STATUS: Record<
  TurnStatus,
  { ring: string; icon: React.ReactNode }
> = {
  completed: {
    ring: "ring-success",
    icon: <CheckCircle2 size={14} className="text-success" />,
  },
  running: {
    ring: "ring-primary",
    icon: <Loader2 size={14} className="text-primary" />,
  },
  paused: {
    ring: "ring-warning",
    icon: <Pause size={14} className="text-warning" />,
  },
};

function TeamTurnCard({ card }: { card: SummaryCard }) {
  const s = TEAM_STATUS[card.status];
  const showBar = card.status !== "completed";
  const pct = card.total > 0 ? (card.completed / card.total) * 100 : 0;
  return (
    <div
      className={`w-[320px] rounded-xl border bg-card px-3.5 py-3 shadow-sm ring-2 ${s.ring}`}
    >
      <div className="flex items-center gap-2">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
          {s.icon}
        </div>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {card.taskSummary}
        </p>
        {card.status === "paused" && (
          <span className="shrink-0 rounded-full bg-warning/10 px-1.5 py-0.5 text-xs font-medium text-warning">
            已暂停
          </span>
        )}
      </div>
      <div className="mt-2.5 flex items-center gap-1.5">
        {card.roles.slice(0, 5).map((role, i) => (
          <Avatar key={`${role}-${i}`} role={role} />
        ))}
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
          {card.agentCount} 个 Agent · {card.completed}/{card.total}
        </span>
      </div>
      {showBar && (
        <div className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full ${card.status === "paused" ? "bg-warning" : "bg-primary"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

function FocusedTurnCard({
  taskTitle,
  nodes,
  edges,
  debate,
  frame,
  graphW,
  graphH,
}: {
  taskTitle: string;
  nodes: Node[];
  edges: Edge[];
  debate: DebateState;
  frame: number;
  graphW: number;
  graphH: number;
}) {
  const settled: Node[] = nodes.map((n) => ({
    ...n,
    data: { ...n.data, _enterFrame: -100, _terminalFrame: null, _glow: true },
  }));
  return (
    <div
      className="overflow-hidden rounded-xl border-2 border-primary bg-card shadow-md"
      style={{ width: FOCUS_W }}
    >
      <div
        className="flex items-center gap-2 border-b border-border px-3"
        style={{ height: FOCUS_HEADER_H }}
      >
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {taskTitle}
        </span>
        <span className="flex shrink-0 items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
          <AlertTriangle size={12} />
          待你确认 1
        </span>
        <span className="flex size-7 items-center justify-center rounded-lg text-muted-foreground">
          <Maximize2 size={15} />
        </span>
      </div>
      <div
        className="flex items-center gap-2 border-b border-border px-3"
        style={{ height: FOCUS_INFO_H }}
      >
        <Loader2 size={13} className="shrink-0 text-primary" />
        <span className="text-xs text-muted-foreground">
          11 个 Agent · 3/11 完成 · 已运行 1m 20s
        </span>
        <div className="ml-auto h-1 w-28 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-[27%] rounded-full bg-primary" />
        </div>
      </div>
      <div style={{ position: "relative", height: FOCUS_BODY_H, ...DOT_GRID }}>
        <GraphStage
          nodes={settled}
          edges={edges}
          debate={{ ...debate, active: true }}
          frame={frame}
          cinematic
          boxWidth={FOCUS_W}
          boxHeight={FOCUS_BODY_H}
          graphW={graphW}
          graphH={graphH}
          padX={28}
          padY={28}
          showBackground={false}
        />
      </div>
    </div>
  );
}

function ZoomControls() {
  return (
    <div className="absolute bottom-3 left-3 flex flex-col gap-0.5 rounded-lg border border-border bg-card/80 p-0.5 shadow-sm">
      {[Plus, Minus, Maximize].map((Icon, i) => (
        <span
          key={i}
          className="flex size-7 items-center justify-center rounded-lg text-muted-foreground"
        >
          <Icon size={14} />
        </span>
      ))}
    </div>
  );
}

function CommandBar() {
  return (
    <div className="shrink-0 border-t border-border bg-card px-4 py-3">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl text-muted-foreground">
          <Cloud size={18} />
        </span>
        <div className="flex min-h-[2.5rem] flex-1 items-center rounded-xl border border-border bg-background px-3 py-2 text-sm text-muted-foreground">
          向 CEO 下达下一步指令…
        </div>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <ArrowUp size={18} />
        </span>
      </div>
    </div>
  );
}

/** 图上指挥 指挥台 (前端UX设计.md §6.2): the boss's pending decisions docked right.
 * Mirrors CanvasDecisionPanel — a 计划复核 checkpoint (plan_review) + a worker
 * 上报 (成本分析 waiting on the budget cap that paused the budget turn above). */
function CommandDeck() {
  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-l border-border bg-card">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border pl-3 pr-1">
        <ListChecks size={15} className="shrink-0 text-warning" />
        <span className="min-w-0 flex-1 text-sm font-medium text-foreground">
          指挥台
          <span className="ml-1.5 rounded-full bg-warning/15 px-1.5 py-0.5 text-xs font-medium text-warning">
            2
          </span>
        </span>
        <span className="flex size-7 items-center justify-center rounded-lg text-muted-foreground">
          <X size={15} />
        </span>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <div className="rounded-xl border border-warning/30 bg-warning/5 p-3">
          <div className="mb-1.5 flex items-center gap-1.5">
            <ClipboardCheck size={14} className="text-warning" />
            <span className="text-sm font-medium text-warning">计划复核</span>
          </div>
          <p className="text-sm font-medium text-foreground">
            CEO 已定稿产品策略，待你确认推进
          </p>
          <p className="mt-1 text-xs leading-snug text-muted-foreground">
            综合圆桌辩论的主持人裁决：先验证关键风险，再分阶段放大投入，锁定团队协作主线。确认后并行产出产品需求与技术方案。
          </p>
          <div className="mt-3 flex gap-2">
            <span className="flex-1 rounded-lg bg-primary px-3 py-1.5 text-center text-sm font-medium text-primary-foreground">
              继续
            </span>
            <span className="flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-center text-sm text-foreground">
              调整
            </span>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-background p-3">
          <div className="mb-1.5 flex items-center gap-2">
            <Avatar role="成本分析" />
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
              成本分析 · 上报
            </span>
          </div>
          <p className="text-xs leading-snug text-muted-foreground">
            需要你确认算力预算上限，我再据此压测两套方案的成本曲线。
          </p>
          <div className="mt-2.5 flex gap-2">
            <span className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">
              回复
            </span>
            <span className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground">
              忽略
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}

export interface PromoCanvasProps {
  taskTitle: string;
  graphW: number;
  graphH: number;
  nodes: Node[];
  edges: Edge[];
  debate: DebateState;
  frame: number;
}

export function PromoCanvas({
  taskTitle,
  graphW,
  graphH,
  nodes,
  edges,
  debate,
  frame,
}: PromoCanvasProps) {
  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <div className="relative flex min-w-0 flex-1 flex-col bg-background">
        {/* Slim header band — labels the view, reserving the left band for the floating
            视图切换 toggle (pl-40 clears it, mirroring the real ConversationCanvas). */}
        <div className="flex h-11 shrink-0 items-center border-b border-border pl-40 pr-12">
          <span className="text-sm font-medium text-foreground">画布</span>
          <span className="ml-2 text-xs text-muted-foreground">
            {SPINE.length + 1} 回合
          </span>
        </div>

        {/* Floating 聊天/画布 view toggle (top-left) + 侧栏 toggle (top-right). */}
        <div className="absolute left-3 top-2 z-10 flex items-center gap-0.5 rounded-lg border border-border bg-card/80 p-0.5 shadow-sm">
          <span className="rounded-md px-2.5 py-1 text-xs text-muted-foreground">
            聊天
          </span>
          <span className="rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-accent-foreground">
            画布
          </span>
        </div>
        <div className="absolute right-3 top-2 z-10 flex size-8 items-center justify-center rounded-lg border border-border bg-card/80 text-muted-foreground shadow-sm">
          <PanelRight size={16} />
        </div>

        {/* Canvas surface: the accumulation spine, bottom-anchored so the focused turn
            sits low and earlier turns climb into the header (the latest-turn camera). */}
        <div
          className="relative flex min-h-0 flex-1 flex-col items-center justify-end overflow-hidden"
          style={DOT_GRID}
        >
          {/* Spotlight: a soft halo behind the focused turn so the live team is the
              clear focal point (consistent with the other stills' premium depth). */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 56% 42% at 50% 80%, color-mix(in oklab, var(--primary) 12%, transparent), transparent 72%)",
            }}
          />
          <div className="flex flex-col items-center pb-8">
            {SPINE.map((card, i) => (
              <div key={i} className="flex flex-col items-center">
                {card.kind === "simple" ? (
                  <SimpleTurnCard card={card} />
                ) : (
                  <TeamTurnCard card={card} />
                )}
                <Spine />
              </div>
            ))}
            <FocusedTurnCard
              taskTitle={taskTitle}
              nodes={nodes}
              edges={edges}
              debate={debate}
              frame={frame}
              graphW={graphW}
              graphH={graphH}
            />
          </div>
          <ZoomControls />
        </div>

        <CommandBar />
      </div>

      <CommandDeck />
    </div>
  );
}
