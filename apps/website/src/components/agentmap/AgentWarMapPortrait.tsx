import {
  AGENTS,
  AgentChip,
  CommEdge,
  EscalationEdge,
  FlowEdge,
  HubNode,
  MapDefs,
  SharedWorkspace,
  TokenDot,
  WaveTag,
  YouNode,
} from "./shared";

/**
 * 方案B —— 完整竖向「多 Agent 协作作战地图」（Hero 右栏加宽版）。
 *
 * 与旧版差异（去蛛网手术）：
 * - 三列固定泳道（L/M/R），波次 2 的两张卡对齐左右列，不再偏置。
 * - 任务流向改「中心总线 + 正交折线」：CEO 扇出、波次间注入、CEO 综合扇入均走水平总线，列内竖直下行——零曲线交叉。
 * - 保留完整机制：8 队员、状态环、工具印记、跨会话记忆、阻塞升级、A2A 辩论/互审。
 */

/** 三列泳道中心 x（卡片宽 190，列间距对齐）。 */
const L = 135;
const M = 340;
const R = 545;

/** 波次行 y（卡片顶边）。 */
const Y1 = 238;
const Y2 = 336;
const Y3 = 434;
const CARD_H = 44;

/** 波次间水平总线 y。 */
const BUS_DELEGATE = 212;
const BUS_INJECT = 310;
const BUS_W2W3 = 408;
const BUS_MERGE = 518;

export default function AgentWarMapPortrait() {
  const P = "pm";
  const y1b = Y1 + CARD_H;
  const y2b = Y2 + CARD_H;
  const y3b = Y3 + CARD_H;

  return (
    <svg
      viewBox="0 0 680 736"
      className="h-auto w-full"
      role="img"
      aria-label="多 Agent 协作作战地图（竖向）：你下达目标，CEO 主 Agent 用 delegate 定义 DAG 组团；共享工作区内分三波协作——波次1 市场检索/竞品采集/用户访谈并行，波次2 数据分析/用户画像依赖，波次3 方案正反辩论并经评审互审；各 Agent 经 MCP 调用工具（卡片右下角印记），用户访谈遇阻 escalate 升级给你，最终 CEO 综合裁决回到你审阅"
      style={{ fontFamily: "inherit" }}
    >
      <MapDefs idPrefix={P} />

      {/* 共享工作区（包裹三波次） */}
      <SharedWorkspace x={24} y={200} w={632} h={320} />
      <WaveTag x={40} y={228} text="波次 1 · 并行" anchor="start" />
      <WaveTag x={40} y={326} text="波次 2 · 依赖" anchor="start" />
      <WaveTag x={40} y={424} text="波次 3 · 辩论 · 互审" anchor="start" />

      {/* ── 任务流向：正交总线（无交叉曲线） ── */}

      {/* 你 → CEO */}
      <FlowEdge idPrefix={P} d="M340 72 L340 96" />

      {/* 跨会话记忆 → CEO（水平汇入） */}
      <FlowEdge idPrefix={P} d="M190 128 L255 128" />

      {/* CEO → 委派总线 → 三列 */}
      <FlowEdge idPrefix={P} d={`M340 160 L340 ${BUS_DELEGATE}`} label="委派" />
      <FlowEdge idPrefix={P} d={`M340 ${BUS_DELEGATE} L${L} ${BUS_DELEGATE} L${L} ${Y1}`} />
      <FlowEdge idPrefix={P} d={`M340 ${BUS_DELEGATE} L${M} ${Y1}`} />
      <FlowEdge idPrefix={P} d={`M340 ${BUS_DELEGATE} L${R} ${BUS_DELEGATE} L${R} ${Y1}`} />

      {/* 波次1 → 注入总线 → 波次2（左右列；中列经总线分流） */}
      <FlowEdge idPrefix={P} d={`M${L} ${y1b} L${L} ${BUS_INJECT}`} />
      <FlowEdge idPrefix={P} d={`M${M} ${y1b} L${M} ${BUS_INJECT}`} />
      <FlowEdge idPrefix={P} d={`M${R} ${y1b} L${R} ${BUS_INJECT}`} />
      <FlowEdge
        idPrefix={P}
        d={`M${L} ${BUS_INJECT} L${R} ${BUS_INJECT}`}
        label="注入"
      />
      <FlowEdge idPrefix={P} d={`M${L} ${BUS_INJECT} L${L} ${Y2}`} />
      <FlowEdge idPrefix={P} d={`M${R} ${BUS_INJECT} L${R} ${Y2}`} />

      {/* 波次2 → 波次3（列内竖直 + 中列从总线汇入） */}
      <FlowEdge idPrefix={P} d={`M${L} ${y2b} L${L} ${BUS_W2W3} L${L} ${Y3}`} />
      <FlowEdge idPrefix={P} d={`M${R} ${y2b} L${R} ${BUS_W2W3} L${R} ${Y3}`} />
      <FlowEdge idPrefix={P} d={`M${M} ${BUS_W2W3} L${M} ${Y3}`} />
      <FlowEdge idPrefix={P} d={`M${L} ${BUS_W2W3} L${R} ${BUS_W2W3}`} />

      {/* 波次3 → 综合总线 → CEO 综合 */}
      <FlowEdge idPrefix={P} d={`M${L} ${y3b} L${L} ${BUS_MERGE}`} />
      <FlowEdge idPrefix={P} d={`M${M} ${y3b} L${M} ${BUS_MERGE}`} />
      <FlowEdge idPrefix={P} d={`M${R} ${y3b} L${R} ${BUS_MERGE}`} />
      <FlowEdge idPrefix={P} d={`M${L} ${BUS_MERGE} L${R} ${BUS_MERGE}`} />
      <FlowEdge idPrefix={P} d={`M340 ${BUS_MERGE} L340 556`} label="综合" />

      {/* CEO 综合 → 你 */}
      <FlowEdge idPrefix={P} d="M340 620 L340 660" />

      {/* ── A2A 协作通信（波次 3 内：辩论 / 互审） ── */}
      <CommEdge idPrefix={P} d={`M${L + 95} 456 L${M - 95} 456`} />
      <CommEdge idPrefix={P} d={`M${M + 95} 456 L${R - 95} 456`} />

      {/* ── 阻塞升级（用户访谈 → 你）：沿右缘正交上行，不横穿工作区 ── */}
      <EscalationEdge
        idPrefix={P}
        d={`M${R} ${Y1 + CARD_H / 2} L${R + 52} ${Y1 + CARD_H / 2} L${R + 52} 44 L392 44`}
      />
      <text
        x={R + 56}
        y={140}
        fontSize={10.5}
        fontWeight={600}
        fill="var(--warning)"
      >
        escalate 升级
      </text>

      {/* ── 游走产物 token ── */}
      <TokenDot path="M340 72 L340 96" dur={2.2} color="var(--primary)" />
      <TokenDot
        path={`M340 160 L340 ${BUS_DELEGATE} L${M} ${Y1}`}
        dur={2.8}
        delay={0.5}
        color="var(--primary)"
      />
      <TokenDot
        path={`M340 ${BUS_MERGE} L340 556`}
        dur={3}
        delay={1}
        color="var(--primary)"
      />
      <TokenDot path="M340 620 L340 660" dur={2.6} delay={1.4} color="var(--primary)" />

      {/* ── 节点 ── */}
      <YouNode x={290} y={16} w={100} h={56} sub="下达目标" />
      <HubNode x={40} y={110} w={150} h={36} title="跨会话记忆" />
      <HubNode
        x={255}
        y={96}
        w={170}
        h={64}
        title="CEO 主 Agent"
        sub="delegate · DAG · replan"
      />

      {/* 波次 1：三列并行 */}
      <AgentChip x={40} y={Y1} w={190} h={CARD_H} agent={AGENTS.market} wave={1} />
      <AgentChip x={245} y={Y1} w={190} h={CARD_H} agent={AGENTS.comp} wave={1} />
      <AgentChip x={450} y={Y1} w={190} h={CARD_H} agent={AGENTS.interview} wave={1} />

      {/* 波次 2：左右列对称（依赖前波注入） */}
      <AgentChip x={40} y={Y2} w={190} h={CARD_H} agent={AGENTS.data} wave={2} />
      <AgentChip x={450} y={Y2} w={190} h={CARD_H} agent={AGENTS.persona} wave={2} />

      {/* 波次 3：三列（辩论 / 互审） */}
      <AgentChip x={40} y={Y3} w={190} h={CARD_H} agent={AGENTS.pro} wave={3} />
      <AgentChip x={245} y={Y3} w={190} h={CARD_H} agent={AGENTS.con} wave={3} />
      <AgentChip x={450} y={Y3} w={190} h={CARD_H} agent={AGENTS.review} wave={3} />

      <HubNode
        x={255}
        y={556}
        w={170}
        h={64}
        title="CEO 综合"
        sub="裁决 · 汇报"
      />
      <YouNode x={290} y={660} w={100} h={56} sub="审阅 · 决策" />
    </svg>
  );
}
