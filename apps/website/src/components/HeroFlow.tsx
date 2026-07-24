/**
 * Hero 右侧的「一次协作」竖向概览图——官网唯一的协作流程图（用图展示）。
 *
 * 与之配套的文字版讲解是 Hero 末尾「一次协作的全过程」步骤区（`#how` 锚点，用文字讲解）：
 * 图负责一眼看懂结构，步骤卡负责把每一步说清楚，show-vs-tell 互补。
 *
 * 叙事：你下达目标 → CEO 组团委派 → 团队分 3 波在共享工作区并行协作 → CEO 综合裁决 → 你审阅。
 * 实线 = 任务流向（委派 / 注入 / 综合）；虚线 = 协作通信（共享工作区内协商互审）。纯展示 SVG。
 */
function Node({
  x,
  y,
  w,
  h,
  title,
  sub,
  variant = "default",
  badge,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  sub?: string;
  variant?: "default" | "hub";
  badge?: string;
}) {
  const isHub = variant === "hub";
  return (
    <g>
      {isHub && (
        <rect
          x={x - 4}
          y={y - 4}
          width={w + 8}
          height={h + 8}
          rx={16}
          fill="none"
          stroke="var(--primary)"
          strokeOpacity={0.22}
          strokeWidth={2}
        />
      )}
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={12}
        fill="var(--card)"
        stroke={isHub ? "var(--primary)" : "var(--border)"}
        strokeWidth={isHub ? 1.6 : 1}
      />
      <text
        x={x + w / 2}
        y={sub ? y + h / 2 - 5 : y + h / 2 + 4}
        textAnchor="middle"
        fontSize={14}
        fontWeight={600}
        fill="var(--foreground)"
      >
        {title}
      </text>
      {sub && (
        <text
          x={x + w / 2}
          y={y + h / 2 + 13}
          textAnchor="middle"
          fontSize={11}
          fill="var(--muted-foreground)"
        >
          {sub}
        </text>
      )}
      {badge && (
        <g>
          <circle cx={x} cy={y} r={11} fill="var(--primary)" />
          <text
            x={x}
            y={y + 4}
            textAnchor="middle"
            fontSize={11}
            fontWeight={700}
            fill="var(--primary-foreground)"
          >
            {badge}
          </text>
        </g>
      )}
    </g>
  );
}

function Edge({
  d,
  dashed = false,
  arrow = true,
}: {
  d: string;
  dashed?: boolean;
  arrow?: boolean;
}) {
  return (
    <path
      d={d}
      fill="none"
      stroke={dashed ? "var(--brand-2)" : "var(--primary)"}
      strokeOpacity={dashed ? 0.55 : 0.6}
      strokeWidth={1.6}
      strokeDasharray={dashed ? "5 5" : undefined}
      markerEnd={dashed ? "url(#hf-dot)" : arrow ? "url(#hf-arrow)" : undefined}
      markerStart={dashed ? "url(#hf-dot)" : undefined}
    />
  );
}

function EdgeLabel({ x, y, text }: { x: number; y: number; text: string }) {
  const w = text.length * 13 + 10;
  return (
    <g>
      <rect
        x={x - w / 2}
        y={y - 10}
        width={w}
        height={20}
        rx={6}
        fill="var(--card)"
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

export default function HeroFlow() {
  return (
    <svg
      viewBox="0 0 460 608"
      className="h-auto w-full"
      role="img"
      aria-label="一次协作的全过程：你下达目标，CEO 主 Agent 理解任务并委派组团；团队在共享工作区分 3 波协作——波次1 资料检索与数据采集并行，波次2 数据分析与趋势研判依赖前一波，波次3 正反方案辩论，各 Agent 读写共享上下文、协商互审，产物经调度器注入下游；最终由 CEO 综合裁决并汇报给你审阅"
      style={{ fontFamily: "inherit" }}
    >
      <defs>
        <marker
          id="hf-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" fill="var(--primary)" fillOpacity="0.7" />
        </marker>
        <marker
          id="hf-dot"
          viewBox="0 0 6 6"
          refX="3"
          refY="3"
          markerWidth="6"
          markerHeight="6"
        >
          <circle cx="3" cy="3" r="2.2" fill="var(--brand-2)" fillOpacity="0.75" />
        </marker>
      </defs>

      {/* 共享工作区容器（虚线 = 协作通信场域） */}
      <rect
        x={24}
        y={196}
        width={412}
        height={258}
        rx={16}
        fill="var(--primary)"
        fillOpacity={0.04}
        stroke="var(--primary)"
        strokeOpacity={0.5}
        strokeWidth={1.4}
        strokeDasharray="6 4"
      />
      {/* 容器标签（骑在上边框） */}
      <rect
        x={24}
        y={184}
        width={120}
        height={24}
        rx={8}
        fill="var(--card)"
        stroke="var(--border)"
        strokeWidth={1}
      />
      <text
        x={84}
        y={200}
        textAnchor="middle"
        fontSize={12}
        fontWeight={600}
        fill="var(--foreground)"
      >
        共享工作区
      </text>

      {/* 任务流向（实线 + 箭头） */}
      <Edge d="M230 64 L230 92" />
      <Edge d="M230 158 L230 198" />
      <Edge d="M230 206 C 185 222, 145 232, 128 245" />
      <Edge d="M230 206 C 275 222, 315 232, 332 245" />
      <Edge d="M128 289 L128 305" />
      <Edge d="M332 289 L332 305" />
      <Edge d="M128 347 L128 363" />
      <Edge d="M332 347 L332 363" />
      <Edge d="M128 405 C 165 428, 205 440, 228 450" arrow={false} />
      <Edge d="M332 405 C 295 428, 255 440, 232 450" arrow={false} />
      <Edge d="M230 450 L230 472" />
      <Edge d="M230 530 L230 552" />

      {/* 协作通信（虚线 + 双向点）：同波 Agent 经共享工作区协商互审 */}
      <Edge d="M216 268 L244 268" dashed />
      <Edge d="M216 326 L244 326" dashed />
      <Edge d="M216 384 L244 384" dashed />

      {/* 边标签 */}
      <EdgeLabel x={230} y={178} text="委派" />
      <EdgeLabel x={128} y={297} text="注入" />

      {/* 节点 */}
      <Node x={165} y={18} w={130} h={46} title="你" sub="下达目标" />
      <Node
        x={150}
        y={92}
        w={160}
        h={66}
        title="CEO 主 Agent"
        sub="理解 · 组团 · 编排"
        variant="hub"
      />
      <Node x={40} y={247} w={176} h={42} title="资料检索" badge="1" />
      <Node x={244} y={247} w={176} h={42} title="数据采集" badge="1" />
      <Node x={40} y={305} w={176} h={42} title="数据分析" badge="2" />
      <Node x={244} y={305} w={176} h={42} title="趋势研判" badge="2" />
      <Node x={40} y={363} w={176} h={42} title="方案 · 正" badge="3" />
      <Node x={244} y={363} w={176} h={42} title="方案 · 反" badge="3" />
      <Node
        x={150}
        y={472}
        w={160}
        h={58}
        title="CEO 综合"
        sub="裁决 · 汇报"
        variant="hub"
      />
      <Node x={165} y={552} w={130} h={44} title="你审阅" sub="决策" />
    </svg>
  );
}
