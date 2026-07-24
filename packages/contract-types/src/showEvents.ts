/**
 * AI 恋综 / AgentTown 节目模式 — `sim.show.*` SSE 事件。
 *
 * 权威源：后端 EventType + pydantic wire payload → `pnpm gen:types` →
 * `events.generated.ts` / `eventTypes.generated.ts`。
 * 本文件只保留类型别名与 payload map，便于节目壳按事件名索引。
 */

import type {
  SimShowAffectionShiftPayload,
  SimShowDeparturePayload,
  SimShowEpisodeGatePayload,
  SimShowHeartPickPayload,
  SimShowPairFormedPayload,
  SimShowRevealPayload,
  SimShowZeroVoteAlertPayload,
} from "./events.generated";

/** Wire event names for show-mode simulation overlays. */
export type SimShowEventType =
  | "sim.show.heart_pick"
  | "sim.show.pair_formed"
  | "sim.show.affection_shift"
  | "sim.show.zero_vote_alert"
  | "sim.show.departure"
  | "sim.show.reveal"
  | "sim.show.episode_gate";

export type {
  SimShowAffectionShiftPayload,
  SimShowDeparturePayload,
  SimShowEpisodeGatePayload,
  SimShowHeartPickPayload,
  SimShowPairFormedPayload,
  SimShowRevealPayload,
  SimShowZeroVoteAlertPayload,
};

export type SimShowPayloadMap = {
  "sim.show.heart_pick": SimShowHeartPickPayload;
  "sim.show.pair_formed": SimShowPairFormedPayload;
  "sim.show.affection_shift": SimShowAffectionShiftPayload;
  "sim.show.zero_vote_alert": SimShowZeroVoteAlertPayload;
  "sim.show.departure": SimShowDeparturePayload;
  "sim.show.reveal": SimShowRevealPayload;
  "sim.show.episode_gate": SimShowEpisodeGatePayload;
};
