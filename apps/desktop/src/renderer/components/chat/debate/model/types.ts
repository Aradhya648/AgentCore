import type { Stance } from "@/stores/execution";
import type { RunNode } from "@/stores/execution";
import type {
  DebateBriefInfo,
  DebateFindingInfo,
  DebateResultPayload,
  DebateSideInfo,
  DebateUserInterjection,
  DebateVerdict,
  EvidenceLedgerEntry,
} from "@/types/events";

export type DebateForm = DebateResultPayload["form"];

/**
 * 一轮里的一方：身份 (名 + 稳定身份色) + 其辩手 run。`run` 收场/已裁判轮由 `run_id`
 * 直取，进行中当前轮由 run 树标签匹配；都解析到同一辩手节点 (发言全文在其
 * `agent.outputChunks`)。`stance` 仅 2 方对称攻防有值 (驱动左右对开)，多方为 null。
 */
/** 结构化论点大纲（契约 ``DebateSpeechArgument``；缺省时 SpeakerBlock 启发式回退）。 */
export interface DebateSpeechArgumentView {
  id: string;
  title: string;
  body: string;
}

export interface DebateSideModel {
  key: string;
  /** 语义 side key (`pro`/`con`/`a`…，= 契约 `DebateRoundSide.key`)，区别于 `key` (run_id，
   *  React key 用)。供 L3 交锋边「谁驳谁」按它精确高亮对应的发言格 (名字可能撞 / 不稳定)。 */
  sideKey: string;
  name: string;
  stance: Stance | null;
  /** 身份色 `var(--agent-N)` (按 name hash，live↔收场恒定)；内联使用，遵 color-tokens。 */
  colorVar: string;
  /** 该方辩手 run 的【实际执行 model】（`run.model`）；MVP 各方同 turn model。{@link modelVendorLabel}
   *  映射成友好厂商名供发言格标；空则不显徽章。 */
  model: string;
  run: RunNode | null;
  /** 后端解析的论点大纲；空 / 缺省 → SpeakerBlock 回退 parseSpeechArguments。 */
  arguments?: DebateSpeechArgumentView[];
}

/**
 * 一条论点级交锋边 (L3 谁驳谁)，已解析成可直接渲染的展示态：`from`/`to` 双方的显示名 + 稳定
 * 身份色 + 反驳要点。由 {@link resolveClashes} 把契约的 `DebateClash` (语义 key 引用) 据本轮
 * `sides` 映射成名字/色，让叙事线把「平铺发言」升级为可读的交锋关系，而非靠用户脑补谁驳了谁。
 */
export interface DebateClashView {
  /** 语义 side key (匹配 {@link DebateSideModel.sideKey})，供点击交锋边时高亮对应发言格。 */
  fromKey: string;
  fromName: string;
  fromColorVar: string;
  toKey: string;
  toName: string;
  toColorVar: string;
  point: string;
}

/**
 * 质询环节的一条 Q↔A 展示态（质询回合 P1）。
 * 只承载问↔答原文；是否正面回应由裁判 engagement / decisive 裁定，不设二元褒贬字段。
 */
export interface DebateCrossExamExchangeView {
  question: string;
  answer: string;
}

/**
 * 质询环节对某一方的一组逐条交换（质询回合 P1）已解析成可渲染的展示态：被质询方 `target` 的显示名 +
 * 身份色 + 逐条 Q↔A + 该方作答的辩手 run（{@link DebateSideModel.run} 同源，完整产出钻取用）。
 * 由 {@link resolveCrossExam} 把契约的 {@link DebateCrossExam}（语义 key + answer_run_id 引用）据
 * 本轮 `sides` 与执行图 runs 映射而成——让「主持人当面质询、某方接招」在群聊里可见。
 */
export interface DebateCrossExamView {
  /** 被质询方语义 key（匹配 {@link DebateSideModel.sideKey}）。 */
  targetKey: string;
  /** 被质询方阵营（取自作答 run 的 `stance`）——split 按阵营分列时的权威判据（后端 key 是主持人
   *  自定、未必 `pro`/`con`，唯 `stance` 恒 `pro`/`con`）；多方 / 无作答 run ⇒ null。 */
  stance: Stance | null;
  targetName: string;
  targetColorVar: string;
  exchanges: DebateCrossExamExchangeView[];
  /** 该方作答的辩手 run（`answer_run_id` 解析）——完整作答在其 `agent.outputChunks`；未解析到（旧
   *  产物 / 作答失败无 run）为 null。侧面板「查看完整产出」钻取用。 */
  answerRun: RunNode | null;
}

/** 批 D1 · 证人答问展示态：幕1 透镜证人被主持人点名的事实性问答。 */
export interface DebateWitnessExamView {
  witnessKey: string;
  name: string;
  originCaption: string;
  colorVar: string;
  exchanges: DebateCrossExamExchangeView[];
  answerRun: RunNode | null;
  seatRunId: string;
  lensRunId: string;
}

/**
 * 一方某轮/累计的记分（记分裁判 P2）已解析成展示态：身份（名 + 稳定身份色）+ 三维分 + 罚分清单 +
 * 净分。由 {@link resolveScores}（逐轮）/ {@link tallyScores}（累计）把契约的 {@link DebateRoundScore}
 * （语义 key 引用）据本轮 `sides` 映射成名字/色——让「回避与被戳穿被记分、倾向由记分驱动」可见。
 */
export interface DebateScoreView {
  sideKey: string;
  name: string;
  colorVar: string;
  argument: number;
  engagement: number;
  evidence: number;
  penalties: string[];
  note: string;
  /** 净得分（三维和减罚分，后端算好、前端直用不重算，可为负）。 */
  total: number;
}

/**
 * 一方的【结辩陈词】（阶段化发言角色 P4 · 结辩收束）已解析成可渲染的展示态：身份（名 + 稳定身份色）+
 * 结辩辩手 run（陈词全文在其 `agent.outputChunks`，与发言格同源）+ 是否成功产出。由 {@link resolveClosings}
 * 把契约的 {@link DebateClosing}（语义 key + run_id 引用）据执行图 runs 映射而成——让「辩已辩尽、各方最后
 * 亮胜负手」在收场处可见（辩手自己的 advocacy 收束，与裁判中立的 `brief.decisive` 正交并存）。
 */
export interface DebateClosingView {
  sideKey: string;
  /** 结辩方阵营（取自结辩 run 的 `stance`）——split 按阵营分列时的权威判据（后端 key 是主持人
   *  自定、未必 `pro`/`con`，唯 `stance` 恒 `pro`/`con`）；多方 / 无结辩 run ⇒ null。 */
  stance: Stance | null;
  name: string;
  colorVar: string;
  /** 结辩辩手 run（`run_id` 解析）——陈词全文在其 `agent.outputChunks`；未解析到（失败无 run）为 null。 */
  run: RunNode | null;
  /** 是否成功产出结辩（失败 / 无 session → false，前端标「未产出结辩」）。 */
  ok: boolean;
}

/** 红队 finding 线程展示态：结构来自载荷，全文靠 run_id 关联。 */
export interface DebateFindingView {
  id: string;
  severity: DebateFindingInfo["severity"];
  target: string;
  attackerKey: string;
  attackerName: string;
  attackerColorVar: string;
  status: DebateFindingInfo["status"];
  disposition: string;
  attackRun: RunNode | null;
  responseRun: RunNode | null;
  rebuttalRun: RunNode | null;
  mergedFrom: string[];
}

/** 圆桌线程 turn 展示态。 */
export interface DebateThreadTurnView {
  speakerKey: string;
  speakerName: string;
  speakerColorVar: string;
  replyToKey: string;
  replyToName: string;
  run: RunNode | null;
  ok: boolean;
  beat: "thread" | "crux";
}

/**
 * 一轮的规范化单元——无论 live (verdict 可空、发言流式) 还是收场 (verdict 必有、全文已定)
 * 都是这一个形状。`inFlight` = 该轮尚未裁判 (live 的当前轮)。`clashes` = 本轮 L3 交锋边
 * (已解析名字/色)，进行中当前轮恒空 (尚未裁判)。
 */
export interface DebateRoundModel {
  roundNo: number;
  focus: string;
  summary: string;
  verdict: DebateVerdict | null;
  sides: DebateSideModel[];
  clashes: DebateClashView[];
  inFlight: boolean;
  /** 驱动本轮的用户【追问】(辩论编排设计.md §6.3)。收场以
   *  权威 `debate_result.rounds[*].user_interjections` 为准；进行中恒空——live 孪生
   *  {@link DebateNarrativeRound} 刻意不携带（守 conformance 不动），追问在收场复盘可见。 */
  userInterjections: DebateUserInterjection[];
  /** 本轮质询环节的问答（质询回合 P1）。进行中由 live 孪生 {@link DebateNarrativeRound}.cross_exam
   *  （或质询 beat 的 `_cx_` run 重建）填充；收场以权威 `debate_result.rounds[*].cross_exam` 为准。 */
  crossExam: DebateCrossExamView[];
  /** 本轮证人答问（批 D1）。缺字段 / 未点名 → []。 */
  witnessExam: DebateWitnessExamView[];
  /** 本轮记分裁判的各方得分（记分裁判 P2）。收场以权威 `debate_result.rounds[*].scores` 为准；
   *  进行中恒空（live 孪生不携带）。空=未开启记分（快速对碰），前端不渲染比分。 */
  scores: DebateScoreView[];
  /** 红队 finding 台账（本轮）；空 = 旧载荷 / 非红队 → 降级为按方发言格。 */
  findings: DebateFindingView[];
  /** 圆桌点名串行线程；空 = 旧载荷 / 非圆桌 → 降级为按方发言格。 */
  threadTurns: DebateThreadTurnView[];
}

/**
 * 规范化的辩论视图模型——常驻外壳据此渲染。`settled` (收场) 才有 `motion`/`brief`/`sides`
 * (roster)/`stopReason`，进行中为 null，让壳头/简报/辩题在收场处**淡入**而非整卡重挂。
 */
export interface DebateModel {
  form: DebateForm;
  motion: string | null;
  stopReason: string | null;
  moderatorRunId: string | null;
  /** Phase 3：裁判 wire model；缺省 null（同模型场 / 旧 journal）。 */
  moderatorModel: string | null;
  moderatorOrigin: "platform" | "byok" | null;
  /** Phase 3：同模型降级明示（开赛卡 / 简报可选提示）。 */
  sameModelDebate: boolean;
  narrativeFirst: boolean;
  rounds: DebateRoundModel[];
  brief: DebateBriefInfo | null;
  sides: DebateSideInfo[] | null;
  /** 各方结辩陈词（阶段化发言角色 P4 · 结辩收束）：收场以权威 `debate_result.closings` 为准、据 run_id
   *  解析陈词 run；进行中恒空（结辩是收场后一次性 beat，live 无孪生）。空=未开启结辩（快速对碰 / 圆桌），
   *  前端不渲染结辩区。 */
  closings: DebateClosingView[];
  /** 主持人开场白：顶部「会说话的主持人」入场气泡。live 自首轮 `debate_round_started.opening`
   * sticky 折入；收场以 `debate_result.opening` 为权威。空（未产出、旧数据）⇒ 不渲染入场，
   * 开场由第 1 轮焦点标题承担。 */
  opening: string | null;
  settled: boolean;
  /** 本场是否开启质询（`debate_round_started.cross_exam_enabled`）。缺字段 / 老会话 → false，
   *  pending 文案回退「正在小结…」。 */
  crossExamEnabled: boolean;
  /** 庭前取证（开赛后首轮前）；null = 无 / 老会话 / 秒过前未发事件。 */
  pretrial: DebatePretrialView | null;
  /** 场级证据台账（live delta 累积 / 收场权威）：徽章 `#eN` 溯源。 */
  evidenceLedger: EvidenceLedgerEntry[];
  /** 圆桌子题轴（收场权威）；进行中 / 非圆桌为 null。 */
  subtopics: string[] | null;
}

/** 庭前取证展示态：各队点单 / 取证员进度 + 台账计数。 */
export interface DebatePretrialView {
  status: "running" | "done" | "skipped" | "degraded" | string;
  thorough: boolean;
  skipReason: string | null;
  evidenceLedgerCount: number;
  fallbackSelfSearch: boolean;
  evidenceReady: boolean;
  sides: DebatePretrialSideView[];
}

export interface DebatePretrialSideView {
  sideKey: string;
  name: string;
  colorVar: string;
  /** 本方任务单（点单后可见）。 */
  tasks: Array<{ query: string; purpose?: string }>;
  /** 取证员进度：done/total；无取证员时 total=0。 */
  investigatorDone: number;
  investigatorTotal: number;
  /** 是否仍有取证员在跑（live）。 */
  running: boolean;
}

/** 参辩名册的一方：语义 `sideKey` + 展示名 + 身份色——站队 / 拍板按 `sideKey` 记录用户取舍。 */
export interface DebateRosterSide {
  sideKey: string;
  name: string;
  colorVar: string;
}

/** 一轮的「人话」状态展示态：`label` 是融合后的一句话、`hint` 是悬浮解释（它怎么判出来 / 怎么读）。 */
export interface RoundVerdictView {
  label: string;
  hint: string;
}
