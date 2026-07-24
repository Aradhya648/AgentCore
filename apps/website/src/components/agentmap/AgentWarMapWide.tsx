import {
  AGENTS,
  AgentChip,
  CommEdge,
  EscalationEdge,
  FlowEdge,
  HubNode,
  MapDefs,
  SharedWorkspace,
  ToolChip,
  TokenDot,
  WaveTag,
  YouNode,
} from "./shared";

/**
 * 方案② —— 整宽横向「多 Agent 协作作战地图」。
 * 你 →（左）CEO 编排 → 三波次团队在共享工作区并行协作（A2A 辩论/互审、阻塞升级、MCP 工具层）
 * →（右）CEO 综合 → 回到你审阅，全链路一图看尽。
 */
export default function AgentWarMapWide() {
  const P = "wm";
  return (
    <svg
      viewBox="0 0 1280 650"
      className="h-auto w-full"
      role="img"
      aria-label="多 Agent 协作作战地图：你下达目标，CEO 主 Agent 用 delegate 定义 DAG 并组建团队；团队在共享工作区分三波协作——波次1 市场检索/竞品采集/用户访谈并行，波次2 数据分析/用户画像依赖前一波，波次3 方案正反辩论并经评审互审；各 Agent 经 MCP 调用 Web/DB/文件/代码工具，产物经调度器中转；用户访谈遇阻经 escalate 升级给你，CEO 在波边界 replan，最终综合裁决回到你审阅"
      style={{ fontFamily: "inherit" }}
    >
      <MapDefs idPrefix={P} />

      {/* 你主导 · 闭环（顶部回环） */}
      <path
        d="M1179 262 C 1179 22, 70 22, 70 262"
        fill="none"
        stroke="var(--brand-2)"
        strokeOpacity={0.28}
        strokeWidth={1.3}
        strokeDasharray="2 7"
      />
      <text
        x={625}
        y={40}
        textAnchor="middle"
        fontSize={11.5}
        fontWeight={600}
        fill="var(--muted-foreground)"
      >
        你主导 · 全程可见 · 闭环裁决
      </text>

      {/* 共享工作区（包裹三波次） */}
      <SharedWorkspace x={320} y={70} w={620} h={470} />
      <WaveTag x={435} y={98} text="波次 1 · 并行" />
      <WaveTag x={635} y={98} text="波次 2 · 依赖" />
      <WaveTag x={835} y={98} text="波次 3 · 辩论 · 互审" />

      {/* ── 任务流向（DAG） ── */}
      {/* 你 → CEO */}
      <FlowEdge idPrefix={P} d="M116 301 L150 301" />
      {/* 记忆 → CEO */}
      <FlowEdge idPrefix={P} d="M216 230 L216 265" />
      {/* CEO → 波次1（委派） */}
      <FlowEdge idPrefix={P} d="M282 296 C 330 200, 345 140, 360 132" />
      <FlowEdge idPrefix={P} d="M282 301 L360 292" label="委派" />
      <FlowEdge idPrefix={P} d="M282 306 C 330 400, 345 452, 360 452" />
      {/* 波次1 → 波次2（注入） */}
      <FlowEdge idPrefix={P} d="M510 132 C 545 165, 550 195, 560 208" />
      <FlowEdge idPrefix={P} d="M510 292 C 545 255, 550 222, 560 216" label="注入" />
      <FlowEdge idPrefix={P} d="M510 452 C 545 415, 550 385, 560 372" />
      {/* 波次2 → 波次3 */}
      <FlowEdge idPrefix={P} d="M710 212 C 745 180, 750 155, 760 152" />
      <FlowEdge idPrefix={P} d="M710 212 C 745 255, 750 300, 760 306" />
      <FlowEdge idPrefix={P} d="M710 372 C 745 340, 750 318, 760 312" />
      <FlowEdge idPrefix={P} d="M710 372 C 745 415, 750 465, 760 466" />
      {/* 波次3 → CEO 综合 */}
      <FlowEdge idPrefix={P} d="M910 152 C 945 205, 958 272, 970 286" />
      <FlowEdge idPrefix={P} d="M910 312 L970 304" label="综合" />
      <FlowEdge idPrefix={P} d="M910 472 C 945 420, 958 332, 970 316" />
      {/* CEO 综合 → 你审阅 */}
      <FlowEdge idPrefix={P} d="M1098 301 L1130 301" />

      {/* ── A2A 协作通信 ── */}
      <CommEdge idPrefix={P} d="M835 174 L835 290" />
      <CommEdge idPrefix={P} d="M822 450 C 800 405, 802 362, 820 334" />
      <WaveTag x={862} y={236} text="辩论" anchor="start" />
      <WaveTag x={792} y={398} text="互审" anchor="end" />

      {/* ── 阻塞升级（worker → 你） ── */}
      <EscalationEdge idPrefix={P} d="M356 452 C 240 484, 120 474, 74 340" />
      <text
        x={206}
        y={500}
        textAnchor="middle"
        fontSize={11}
        fontWeight={600}
        fill="var(--warning)"
      >
        escalate · 阻塞升级给你
      </text>

      {/* ── MCP 工具层 ── */}
      <path
        d="M630 540 L630 576"
        fill="none"
        stroke="var(--muted-foreground)"
        strokeOpacity={0.4}
        strokeWidth={1.3}
        strokeDasharray="3 4"
      />
      <text
        x={360}
        y={566}
        fontSize={11}
        fontWeight={600}
        fill="var(--muted-foreground)"
      >
        MCP 工具层 · Agent 按需调用
      </text>
      <ToolChip x={360} y={584} w={118} h={36} kind="web" />
      <ToolChip x={520} y={584} w={118} h={36} kind="db" />
      <ToolChip x={680} y={584} w={118} h={36} kind="files" />
      <ToolChip x={840} y={584} w={118} h={36} kind="code" />

      {/* ── 游走产物 token（reduced-motion 下隐藏） ── */}
      <TokenDot path="M116 301 L150 301" dur={2.4} />
      <TokenDot
        path="M282 301 L360 292"
        dur={2.8}
        delay={0.4}
        color="var(--primary)"
      />
      <TokenDot
        path="M710 212 C 745 180, 750 155, 760 152"
        dur={3.2}
        delay={0.8}
        color="var(--primary)"
      />
      <TokenDot
        path="M910 152 C 945 205, 958 272, 970 286"
        dur={3.4}
        delay={1.2}
        color="var(--primary)"
      />

      {/* ── 节点 ── */}
      <YouNode x={24} y={266} w={92} h={70} sub="下达目标" />
      <HubNode
        x={150}
        y={196}
        w={132}
        h={34}
        title="跨会话记忆"
      />
      <HubNode
        x={150}
        y={265}
        w={132}
        h={72}
        title="CEO 主 Agent"
        sub="delegate · DAG · replan"
      />

      <AgentChip x={360} y={110} w={150} h={44} agent={AGENTS.market} wave={1} />
      <AgentChip x={360} y={270} w={150} h={44} agent={AGENTS.comp} wave={1} />
      <AgentChip
        x={360}
        y={430}
        w={150}
        h={44}
        agent={AGENTS.interview}
        wave={1}
      />
      <AgentChip x={560} y={190} w={150} h={44} agent={AGENTS.data} wave={2} />
      <AgentChip x={560} y={350} w={150} h={44} agent={AGENTS.persona} wave={2} />
      <AgentChip x={760} y={130} w={150} h={44} agent={AGENTS.pro} wave={3} />
      <AgentChip x={760} y={290} w={150} h={44} agent={AGENTS.con} wave={3} />
      <AgentChip x={760} y={450} w={150} h={44} agent={AGENTS.review} wave={3} />

      <HubNode
        x={970}
        y={265}
        w={128}
        h={72}
        title="CEO 综合"
        sub="裁决 · 汇报"
      />
      <YouNode x={1130} y={266} w={98} h={70} sub="审阅 · 决策" />
    </svg>
  );
}
