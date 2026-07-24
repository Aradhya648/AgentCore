import { HubNode, MapDefs, YouNode } from "./shared";

/**
 * 方案A —— 「简化竖图」：Hero 右栏用的极简协作概览。
 *
 * 设计取向：**2 秒看懂的主干叙事**，不是完整架构图。
 * 你 → CEO 组团 → 一支团队在共享工作区分 3 波协作（每波两路、列对齐、零交叉）→ CEO 综合 → 你。
 * 刻意省略：工具层 / 跨会话记忆 / 阻塞升级 / 状态环 —— 这些机制细节交给下方专区或完整版。
 * 保留：身份色队员卡、波次徽标、波内 A2A 协作虚线（产品差异化的「辩论 / 互审」）。
 *
 * 连线全部沿两条竖直泳道（左 128 / 右 332）平行下行，仅在 CEO 扇出、CEO 综合扇入处汇聚——
 * 同源扇出 / 同汇扇入不产生交叉，从根上避免「蛛网」。颜色只用语义 token / 身份色。
 */

const LEFT = 128;
const RIGHT = 332;

type Role = { title: string; color: string; wave: number };

const WAVE1: Role[] = [
  { title: "市场检索", color: "--agent-1", wave: 1 },
  { title: "竞品采集", color: "--agent-2", wave: 1 },
];
const WAVE2: Role[] = [
  { title: "数据分析", color: "--agent-4", wave: 2 },
  { title: "用户画像", color: "--agent-5", wave: 2 },
];
const WAVE3: Role[] = [
  { title: "方案 · 正", color: "--agent-7", wave: 3 },
  { title: "方案 · 反", color: "--agent-8", wave: 3 },
];

function RoleChip({
  x,
  y,
  w,
  h,
  role,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  role: Role;
}) {
  const c = `var(${role.color})`;
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
      <rect x={x} y={y + 6} width={4} height={h - 12} rx={2} fill={c} />
      <circle cx={x + 18} cy={y + h / 2} r={4.5} fill={c} fillOpacity={0.9} />
      <text
        x={x + 30}
        y={y + h / 2 + 4.5}
        fontSize={13}
        fontWeight={600}
        fill="var(--foreground)"
      >
        {role.title}
      </text>
      {/* 波次徽标（右上角，轻量） */}
      <g>
        <circle cx={x + w - 13} cy={y + 13} r={8.5} fill="var(--primary)" fillOpacity={0.16} />
        <text
          x={x + w - 13}
          y={y + 16.5}
          textAnchor="middle"
          fontSize={9.5}
          fontWeight={700}
          fill="var(--primary)"
        >
          {role.wave}
        </text>
      </g>
    </g>
  );
}

/** 任务流向：实线 + 箭头（平静，不做流动动画，凸显「简化」）。 */
function Flow({
  d,
  idPrefix,
}: {
  d: string;
  idPrefix: string;
}) {
  return (
    <path
      d={d}
      fill="none"
      stroke="var(--primary)"
      strokeOpacity={0.55}
      strokeWidth={1.6}
      markerEnd={`url(#${idPrefix}-arrow)`}
    />
  );
}

/** 波内 A2A 协作通信：双向虚线 + 端点。 */
function Comm({ d, idPrefix }: { d: string; idPrefix: string }) {
  return (
    <path
      d={d}
      fill="none"
      stroke="var(--brand-2)"
      strokeOpacity={0.6}
      strokeWidth={1.5}
      strokeDasharray="5 5"
      markerStart={`url(#${idPrefix}-dot)`}
      markerEnd={`url(#${idPrefix}-dot)`}
    />
  );
}

function Label({ x, y, text }: { x: number; y: number; text: string }) {
  const w = text.length * 13 + 12;
  return (
    <g>
      <rect
        x={x - w / 2}
        y={y - 10}
        width={w}
        height={20}
        rx={6}
        fill="var(--background)"
        fillOpacity={0.92}
      />
      <text
        x={x}
        y={y + 4}
        textAnchor="middle"
        fontSize={12}
        fill="var(--muted-foreground)"
      >
        {text}
      </text>
    </g>
  );
}

export default function AgentMapVerticalSimple() {
  const P = "vs";
  return (
    <svg
      viewBox="0 0 460 612"
      className="h-auto w-full"
      role="img"
      aria-label="一次协作的简化概览：你下达目标，CEO 主 Agent 组建团队并委派；团队在共享工作区分三波协作——波次1 市场检索与竞品采集并行，波次2 数据分析与用户画像依赖前一波，波次3 方案正反辩论互审；最终 CEO 综合裁决回到你审阅"
      style={{ fontFamily: "inherit" }}
    >
      <MapDefs idPrefix={P} />

      {/* 共享工作区容器 */}
      <rect
        x={24}
        y={196}
        width={412}
        height={258}
        rx={16}
        fill="var(--primary)"
        fillOpacity={0.04}
        stroke="var(--primary)"
        strokeOpacity={0.45}
        strokeWidth={1.3}
        strokeDasharray="7 5"
      />
      <rect
        x={24}
        y={185}
        width={108}
        height={22}
        rx={8}
        fill="var(--card)"
        stroke="var(--border)"
        strokeWidth={1}
      />
      <text
        x={78}
        y={200}
        textAnchor="middle"
        fontSize={11.5}
        fontWeight={600}
        fill="var(--foreground)"
      >
        共享工作区
      </text>

      {/* ── 任务流向 ── */}
      <Flow d="M230 66 L230 90" idPrefix={P} />
      <Flow d={`M230 160 C 195 178 ${LEFT + 8} 196 ${LEFT} 245`} idPrefix={P} />
      <Flow d={`M230 160 C 265 178 ${RIGHT - 8} 196 ${RIGHT} 245`} idPrefix={P} />
      <Flow d={`M${LEFT} 289 L${LEFT} 305`} idPrefix={P} />
      <Flow d={`M${RIGHT} 289 L${RIGHT} 305`} idPrefix={P} />
      <Flow d={`M${LEFT} 347 L${LEFT} 363`} idPrefix={P} />
      <Flow d={`M${RIGHT} 347 L${RIGHT} 363`} idPrefix={P} />
      <Flow d={`M${LEFT} 405 C 165 430 208 442 228 450`} idPrefix={P} />
      <Flow d={`M${RIGHT} 405 C 295 430 252 442 232 450`} idPrefix={P} />
      <Flow d="M230 458 L230 478" idPrefix={P} />
      <Flow d="M230 540 L230 560" idPrefix={P} />

      {/* ── 波内 A2A 协作通信 ── */}
      <Comm d={`M${LEFT + 88} 268 L${RIGHT - 88} 268`} idPrefix={P} />
      <Comm d={`M${LEFT + 88} 326 L${RIGHT - 88} 326`} idPrefix={P} />
      <Comm d={`M${LEFT + 88} 384 L${RIGHT - 88} 384`} idPrefix={P} />

      {/* ── 标签 ── */}
      <Label x={230} y={178} text="委派" />
      <Label x={230} y={384} text="辩论 · 互审" />

      {/* ── 节点 ── */}
      <YouNode x={170} y={20} w={120} h={46} sub="下达目标" />
      <HubNode
        x={150}
        y={94}
        w={160}
        h={62}
        title="CEO 主 Agent"
        sub="组团 · 委派 · 编排"
      />

      <RoleChip x={40} y={247} w={176} h={42} role={WAVE1[0]} />
      <RoleChip x={244} y={247} w={176} h={42} role={WAVE1[1]} />
      <RoleChip x={40} y={305} w={176} h={42} role={WAVE2[0]} />
      <RoleChip x={244} y={305} w={176} h={42} role={WAVE2[1]} />
      <RoleChip x={40} y={363} w={176} h={42} role={WAVE3[0]} />
      <RoleChip x={244} y={363} w={176} h={42} role={WAVE3[1]} />

      <HubNode x={150} y={478} w={160} h={60} title="CEO 综合" sub="裁决 · 汇报" />
      <YouNode x={170} y={560} w={120} h={44} sub="审阅 · 决策" />
    </svg>
  );
}
