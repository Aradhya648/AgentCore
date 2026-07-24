/**
 * 「多 Agent 协作作战地图」共享积木：角色数据 + 纯展示 SVG 基元。
 *
 * 两种舞台共用这套基元：
 * - `AgentWarMapWide`（整宽横向系统地图，方案②）
 * - `AgentWarMapPortrait`（加宽右栏的竖向地图，方案①）
 *
 * 体现产品真实机制：CEO + delegate 定 DAG、WaveScheduler 波次调度、共享工作区中转产物、
 * A2A 辩论/互审、worker 阻塞 escalate 升级给你、CEO 波边界 replan、MCP 工具调用、跨会话记忆。
 * 颜色只用语义 token / Agent 身份色（globals.css 单一来源），不硬编码 hex。
 */

export type AgentStatus = "running" | "done" | "pending" | "blocked";
export type ToolKind = "web" | "db" | "files" | "code";

export type AgentSpec = {
  title: string;
  /** 身份色 token 名，如 "--agent-1" */
  color: string;
  status: AgentStatus;
  tool?: ToolKind;
};

/** 一次「新产品上市调研与方案」协作的真实团队（8 名队员，跨 3 波）。 */
export const AGENTS = {
  market: { title: "市场检索", color: "--agent-1", status: "done", tool: "web" },
  comp: { title: "竞品采集", color: "--agent-2", status: "done", tool: "web" },
  interview: {
    title: "用户访谈",
    color: "--agent-3",
    status: "blocked",
    tool: "files",
  },
  data: { title: "数据分析", color: "--agent-4", status: "running", tool: "code" },
  persona: { title: "用户画像", color: "--agent-5", status: "running", tool: "db" },
  pro: { title: "方案 · 正", color: "--agent-7", status: "pending" },
  con: { title: "方案 · 反", color: "--agent-8", status: "pending" },
  review: { title: "评审", color: "--agent-6", status: "pending", tool: "files" },
} satisfies Record<string, AgentSpec>;

export function statusColor(s: AgentStatus): string {
  if (s === "done") return "var(--success)";
  if (s === "running") return "var(--primary)";
  if (s === "blocked") return "var(--warning)";
  return "var(--muted-foreground)";
}

const TOOL_LABEL: Record<ToolKind, string> = {
  web: "Web",
  db: "DB",
  files: "Files",
  code: "Code",
};

/** SVG marker / 渐变定义。idPrefix 保证两张图同页时不冲突。 */
export function MapDefs({ idPrefix }: { idPrefix: string }) {
  return (
    <defs>
      <marker
        id={`${idPrefix}-arrow`}
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M0,0 L10,5 L0,10 z" fill="var(--primary)" fillOpacity="0.85" />
      </marker>
      <marker
        id={`${idPrefix}-arrow-amber`}
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M0,0 L10,5 L0,10 z" fill="var(--warning)" fillOpacity="0.9" />
      </marker>
      <marker
        id={`${idPrefix}-dot`}
        viewBox="0 0 6 6"
        refX="3"
        refY="3"
        markerWidth="6"
        markerHeight="6"
      >
        <circle cx="3" cy="3" r="2.2" fill="var(--brand-2)" fillOpacity="0.8" />
      </marker>
    </defs>
  );
}

/** 任务流向：实线底 + 上叠流动短划（reduced-motion 下仅余实线）。 */
export function FlowEdge({
  d,
  idPrefix,
  label,
}: {
  d: string;
  idPrefix: string;
  label?: string;
}) {
  return (
    <g>
      <path
        d={d}
        fill="none"
        stroke="var(--primary)"
        strokeOpacity={0.32}
        strokeWidth={1.6}
        markerEnd={`url(#${idPrefix}-arrow)`}
      />
      <path
        className="am-flow"
        d={d}
        fill="none"
        stroke="var(--primary)"
        strokeOpacity={0.9}
        strokeWidth={1.8}
      />
      {label ? <EdgeLabel d={d} text={label} /> : null}
    </g>
  );
}

/** 协作通信（A2A / 共享工作区）：双向虚线 + 游走点。 */
export function CommEdge({ d, idPrefix }: { d: string; idPrefix: string }) {
  return (
    <path
      className="am-comm"
      d={d}
      fill="none"
      stroke="var(--brand-2)"
      strokeOpacity={0.7}
      strokeWidth={1.5}
      markerStart={`url(#${idPrefix}-dot)`}
      markerEnd={`url(#${idPrefix}-dot)`}
    />
  );
}

/** 阻塞升级：worker 被卡 → escalate 直达你。琥珀虚线 + 闪烁。 */
export function EscalationEdge({
  d,
  idPrefix,
}: {
  d: string;
  idPrefix: string;
}) {
  return (
    <path
      className="am-blink"
      d={d}
      fill="none"
      stroke="var(--warning)"
      strokeOpacity={0.9}
      strokeWidth={1.6}
      strokeDasharray="2 5"
      strokeLinecap="round"
      markerEnd={`url(#${idPrefix}-arrow-amber)`}
    />
  );
}

/** 沿路径游走的产物 token（reduced-motion 下隐藏）。 */
export function TokenDot({
  path,
  color = "var(--brand-2)",
  dur = 3.2,
  delay = 0,
  r = 3,
}: {
  path: string;
  color?: string;
  dur?: number;
  delay?: number;
  r?: number;
}) {
  return (
    <circle
      className="am-token"
      r={r}
      fill={color}
      style={{
        offsetPath: `path('${path}')`,
        animationDuration: `${dur}s`,
        animationDelay: `${delay}s`,
      }}
    />
  );
}

function EdgeLabel({ d, text }: { d: string; text: string }) {
  // 取路径中点的粗略估计：用首尾坐标平均（直线/浅弧足够）。
  const nums = d.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
  const x1 = nums[0] ?? 0;
  const y1 = nums[1] ?? 0;
  const x2 = nums[nums.length - 2] ?? x1;
  const y2 = nums[nums.length - 1] ?? y1;
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const w = text.length * 12 + 10;
  return (
    <g>
      <rect
        x={cx - w / 2}
        y={cy - 9}
        width={w}
        height={18}
        rx={5}
        fill="var(--background)"
        fillOpacity={0.9}
      />
      <text
        x={cx}
        y={cy + 4}
        textAnchor="middle"
        fontSize={11}
        fill="var(--muted-foreground)"
      >
        {text}
      </text>
    </g>
  );
}

export function StatusRing({
  cx,
  cy,
  status,
  r = 7,
}: {
  cx: number;
  cy: number;
  status: AgentStatus;
  r?: number;
}) {
  const color = statusColor(status);
  if (status === "running") {
    return (
      <circle
        className="am-spin"
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeDasharray="3 3.5"
      />
    );
  }
  if (status === "done") {
    return (
      <g>
        <circle cx={cx} cy={cy} r={r} fill={color} fillOpacity={0.18} />
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={1.6} />
        <path
          d={`M${cx - 3.2} ${cy} l2.2 2.3 l4.2 -4.6`}
          fill="none"
          stroke={color}
          strokeWidth={1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    );
  }
  if (status === "blocked") {
    return (
      <g className="am-blink">
        <circle cx={cx} cy={cy} r={r} fill={color} fillOpacity={0.2} />
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={1.6} />
        <line
          x1={cx}
          y1={cy - 3}
          x2={cx}
          y2={cy + 1}
          stroke={color}
          strokeWidth={1.7}
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy + 3.4} r={0.9} fill={color} />
      </g>
    );
  }
  return (
    <circle
      cx={cx}
      cy={cy}
      r={r}
      fill="none"
      stroke={color}
      strokeOpacity={0.55}
      strokeWidth={1.6}
      strokeDasharray="2 3"
    />
  );
}

export function ToolGlyph({
  cx,
  cy,
  kind,
  size = 13,
  color = "var(--muted-foreground)",
}: {
  cx: number;
  cy: number;
  kind: ToolKind;
  size?: number;
  color?: string;
}) {
  const s = size / 2;
  const common = {
    fill: "none",
    stroke: color,
    strokeWidth: 1.4,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <g transform={`translate(${cx} ${cy})`}>
      {kind === "web" && (
        <g {...common}>
          <circle cx={0} cy={0} r={s} />
          <ellipse cx={0} cy={0} rx={s / 2.2} ry={s} />
          <line x1={-s} y1={0} x2={s} y2={0} />
        </g>
      )}
      {kind === "db" && (
        <g {...common}>
          <ellipse cx={0} cy={-s + 1.5} rx={s} ry={s / 2.4} />
          <path d={`M${-s} ${-s + 1.5} V${s - 1.5}`} />
          <path d={`M${s} ${-s + 1.5} V${s - 1.5}`} />
          <path d={`M${-s} ${s - 1.5} A${s} ${s / 2.4} 0 0 0 ${s} ${s - 1.5}`} />
          <path d={`M${-s} ${0} A${s} ${s / 2.4} 0 0 0 ${s} ${0}`} />
        </g>
      )}
      {kind === "files" && (
        <g {...common}>
          <path
            d={`M${-s + 1} ${-s} h${size - 4} l2 2 v${size - 2} h${-(size)} z`}
          />
          <line x1={-s + 3} y1={-1} x2={s - 3} y2={-1} />
          <line x1={-s + 3} y1={s - 3} x2={s - 3} y2={s - 3} />
        </g>
      )}
      {kind === "code" && (
        <g {...common}>
          <path d={`M${-s + 1} ${-s + 2} L${-s + 4} ${0} L${-s + 1} ${s - 2}`} />
          <path d={`M${s - 1} ${-s + 2} L${s - 4} ${0} L${s - 1} ${s - 2}`} />
        </g>
      )}
    </g>
  );
}

/** 你（领导者）：与队员明显区分——主色实心 + 指挥冠标。 */
export function YouNode({
  x,
  y,
  w,
  h,
  sub,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  sub?: string;
}) {
  return (
    <g>
      <rect
        x={x - 4}
        y={y - 4}
        width={w + 8}
        height={h + 8}
        rx={16}
        fill="none"
        stroke="var(--brand-2)"
        strokeOpacity={0.35}
        strokeWidth={2}
      />
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={12}
        fill="var(--primary)"
        fillOpacity={0.16}
        stroke="var(--primary)"
        strokeWidth={1.6}
      />
      {/* 指挥冠标 */}
      <path
        d={`M${x + w / 2 - 9} ${y + 13} l3 -7 l3 4 l3 -6 l3 6 l3 -4 l3 7 z`}
        fill="var(--brand-2)"
        fillOpacity={0.9}
      />
      <text
        x={x + w / 2}
        y={sub ? y + h / 2 + 6 : y + h / 2 + 5}
        textAnchor="middle"
        fontSize={15}
        fontWeight={700}
        fill="var(--foreground)"
      >
        你
      </text>
      {sub && (
        <text
          x={x + w / 2}
          y={y + h - 8}
          textAnchor="middle"
          fontSize={10.5}
          fill="var(--muted-foreground)"
        >
          {sub}
        </text>
      )}
    </g>
  );
}

/** CEO 主 Agent / CEO 综合：编排枢纽，主色环强调。 */
export function HubNode({
  x,
  y,
  w,
  h,
  title,
  sub,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  sub?: string;
}) {
  return (
    <g>
      <rect
        x={x - 4}
        y={y - 4}
        width={w + 8}
        height={h + 8}
        rx={16}
        fill="none"
        stroke="var(--primary)"
        strokeOpacity={0.25}
        strokeWidth={2}
      />
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={12}
        fill="var(--card)"
        stroke="var(--primary)"
        strokeWidth={1.6}
      />
      <text
        x={x + w / 2}
        y={sub ? y + h / 2 - 4 : y + h / 2 + 4}
        textAnchor="middle"
        fontSize={14}
        fontWeight={700}
        fill="var(--foreground)"
      >
        {title}
      </text>
      {sub && (
        <text
          x={x + w / 2}
          y={y + h / 2 + 13}
          textAnchor="middle"
          fontSize={10.5}
          fill="var(--muted-foreground)"
        >
          {sub}
        </text>
      )}
    </g>
  );
}

/** 队员卡：身份色侧条 + 角色名 + 波次徽标 + 状态环 + 工具印记。 */
export function AgentChip({
  x,
  y,
  w,
  h,
  agent,
  wave,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  agent: AgentSpec;
  wave?: number;
}) {
  const c = `var(${agent.color})`;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={11}
        fill="var(--card)"
        stroke="var(--border)"
        strokeWidth={1}
      />
      {/* 身份色侧条 */}
      <rect x={x} y={y + 6} width={4} height={h - 12} rx={2} fill={c} />
      <circle cx={x + 16} cy={y + h / 2} r={4.5} fill={c} fillOpacity={0.9} />
      <text
        x={x + 27}
        y={y + h / 2 + 4.5}
        fontSize={13}
        fontWeight={600}
        fill="var(--foreground)"
      >
        {agent.title}
      </text>
      {/* 波次徽标（左上角） */}
      {wave ? (
        <g>
          <circle cx={x} cy={y} r={9.5} fill="var(--primary)" />
          <text
            x={x}
            y={y + 3.5}
            textAnchor="middle"
            fontSize={10}
            fontWeight={700}
            fill="var(--primary-foreground)"
          >
            {wave}
          </text>
        </g>
      ) : null}
      {/* 状态环（右上角） */}
      <StatusRing cx={x + w} cy={y} status={agent.status} />
      {/* 工具印记（右下角） */}
      {agent.tool ? (
        <g>
          <ToolGlyph cx={x + w - 13} cy={y + h - 12} kind={agent.tool} />
        </g>
      ) : null}
    </g>
  );
}

/** MCP 工具节点（作战地图底部「工具层」）。 */
export function ToolChip({
  x,
  y,
  w,
  h,
  kind,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  kind: ToolKind;
}) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        fill="var(--card)"
        stroke="var(--border)"
        strokeWidth={1}
        strokeDasharray="4 3"
      />
      <ToolGlyph cx={x + 16} cy={y + h / 2} kind={kind} size={15} />
      <text
        x={x + 28}
        y={y + h / 2 + 4}
        fontSize={12}
        fill="var(--muted-foreground)"
      >
        {TOOL_LABEL[kind]}
      </text>
    </g>
  );
}

export function WaveTag({
  x,
  y,
  text,
  anchor = "middle",
}: {
  x: number;
  y: number;
  text: string;
  anchor?: "start" | "middle" | "end";
}) {
  return (
    <text
      x={x}
      y={y}
      textAnchor={anchor}
      fontSize={11.5}
      fontWeight={600}
      letterSpacing="0.04em"
      fill="var(--muted-foreground)"
    >
      {text}
    </text>
  );
}

export function SharedWorkspace({
  x,
  y,
  w,
  h,
  label = "共享工作区 · 产物经调度器中转",
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  label?: string;
}) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={16}
        fill="var(--primary)"
        fillOpacity={0.04}
        stroke="var(--primary)"
        strokeOpacity={0.45}
        strokeWidth={1.3}
        strokeDasharray="7 5"
      />
      <rect
        x={x + 14}
        y={y - 11}
        width={label.length * 11 + 22}
        height={22}
        rx={8}
        fill="var(--card)"
        stroke="var(--border)"
        strokeWidth={1}
      />
      <text
        x={x + 25}
        y={y + 4}
        fontSize={11.5}
        fontWeight={600}
        fill="var(--foreground)"
      >
        {label}
      </text>
    </g>
  );
}
