import type {
  InteractionResult,
  InteractionStateChange,
  InteractionTranscriptLine,
} from "@agentcore/contract-types";

export type InteractionKind = InteractionResult["kind"];

export type ActiveInteraction = {
  id: string;
  tick: number;
  kind: InteractionKind;
  status: InteractionResult["status"];
  initiatorId: string;
  targetId?: string | null;
  summary: string;
  transcript?: InteractionTranscriptLine[];
  stateChanges?: InteractionStateChange;
  detail?: string;
  expiresAt: number;
};

const INTERACTION_TTL_MS: Record<InteractionKind, number> = {
  conversation: 4000,
  trade: 3000,
  vote: 5000,
  // 心动选票密封/揭晓：与 vote 同量级，留足舞台读秒。
  heart_pick: 5000,
};

export function interactionExpiresAt(
  kind: InteractionKind,
  at = Date.now(),
): number {
  return at + INTERACTION_TTL_MS[kind];
}

export function activeInteractionFromResult(
  interaction: InteractionResult,
  tick: number,
  at = Date.now(),
): ActiveInteraction {
  return {
    id: interaction.request_id,
    tick,
    kind: interaction.kind,
    status: interaction.status,
    initiatorId: interaction.initiator_id,
    targetId: interaction.target_id,
    summary: interaction.summary,
    transcript: interaction.transcript,
    stateChanges: interaction.state_changes,
    detail: interaction.detail,
    expiresAt: interactionExpiresAt(interaction.kind, at),
  };
}

export function truncateInteractionText(text: string, maxLen = 48): string {
  const trimmed = text.trim();
  if (trimmed.length <= maxLen) return trimmed;
  return `${trimmed.slice(0, maxLen - 1)}…`;
}

export function lastLineForAgent(
  transcript: InteractionTranscriptLine[] | undefined,
  agentId: string,
): string | null {
  if (!transcript?.length) return null;
  for (let i = transcript.length - 1; i >= 0; i -= 1) {
    if (transcript[i].speaker_id === agentId) return transcript[i].text;
  }
  return null;
}

export function voteGovernanceDetails(stateChanges?: InteractionStateChange): {
  motion: string;
  outcome: string;
  yes: number;
  no: number;
  abstain: number;
} {
  const gov = stateChanges?.governance ?? {};
  return {
    motion: String(gov.motion ?? ""),
    outcome: String(gov.outcome ?? ""),
    yes: Number(gov.yes ?? 0),
    no: Number(gov.no ?? 0),
    abstain: Number(gov.abstain ?? 0),
  };
}

export function tradeBriefLabel(interaction: ActiveInteraction): string {
  const transfer = interaction.stateChanges?.inventory_transfers?.[0];
  if (transfer && typeof transfer === "object") {
    const item = String(transfer.item ?? "物品");
    const qty = Number(transfer.quantity ?? 1);
    const money = interaction.stateChanges?.money_transfers?.[0];
    const amount =
      money && typeof money === "object" ? Number(money.amount ?? 0) : null;
    if (amount != null && !Number.isNaN(amount)) {
      return `${item}×${qty} · ${amount.toFixed(0)} 币`;
    }
    return `${item}×${qty}`;
  }
  return truncateInteractionText(interaction.summary, 40);
}

export function interactionSucceeded(
  status: InteractionResult["status"],
): boolean {
  return status === "completed";
}
