/** Turn spine: hydrate journal, fold messages → turns (LOD nodes built in useCanvasFlow). */

import {
  assistantProjectionId,
  useActiveMessages,
  useConversationStore,
} from "@/stores/conversation";
import {
  type Execution,
  projectRuntime,
  useExecutionStore,
} from "@/stores/execution";
import { useEffect, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  countPendingDecisions,
  isTurnRecoverable,
} from "./CanvasDecisionPanel";
import type { TurnRailItem } from "./CanvasTurnRail";

export const TURN_NODE_WIDTH = 320;
export const TEAM_NODE_HEIGHT = 132;
export const SIMPLE_NODE_HEIGHT = 96;
export const GAP_Y = 40;

export interface TurnItem {
  id: string;
  kind: "team" | "simple";
  exec: Execution | null;
  prompt: string;
  answer: string;
  /** User bubble id for this turn (empty when no preceding user message). */
  promptMessageId: string;
  /** Assistant bubble id (client id; may differ from projection `id`). */
  answerMessageId: string;
  running: boolean;
  pendingDecisions: number;
  recoverable: boolean;
}

/** Spine height for a turn — prefers rendered RF style/measured height. */
export function spineTurnHeight(
  turn: TurnItem,
  nodes: {
    id: string;
    style?: { height?: number | string };
    height?: number;
    measured?: { height?: number };
  }[],
): number {
  const n = nodes.find((x) => x.id === turn.id);
  const styleH = n?.style?.height;
  if (typeof styleH === "number" && Number.isFinite(styleH)) return styleH;
  if (typeof styleH === "string") {
    const parsed = Number.parseFloat(styleH);
    if (!Number.isNaN(parsed)) return parsed;
  }
  const measured = n?.measured?.height ?? n?.height;
  if (typeof measured === "number" && Number.isFinite(measured))
    return measured;
  return turn.kind === "team" ? TEAM_NODE_HEIGHT : SIMPLE_NODE_HEIGHT;
}

interface UseCanvasTurnsOptions {
  focusedTurn: string | null;
  setFocusedTurn: (id: string) => void;
}

export function useCanvasTurns({
  focusedTurn,
  setFocusedTurn,
}: UseCanvasTurnsOptions) {
  const messages = useActiveMessages();
  const conversationId = useConversationStore((s) => s.currentConversationId);

  const teamTurnIds = useMemo(() => {
    const ids: string[] = [];
    for (const m of messages) {
      if (m.role !== "assistant" || !m.executionId) continue;
      ids.push(assistantProjectionId(m));
    }
    return ids;
  }, [messages]);

  // Per-turn runtimes only (not the whole byId table).
  const teamRuntimes = useExecutionStore(
    useShallow((s) => teamTurnIds.map((id) => s.byId[id])),
  );

  useEffect(() => {
    const store = useExecutionStore.getState();
    for (const m of messages) {
      if (m.role !== "assistant" || !m.executionId || !m.runs) continue;
      const key = assistantProjectionId(m);
      if (!store.byId[key]?.plan) {
        store.hydrateFromJournal(key, m.runs);
      }
    }
  }, [messages]);

  const turns = useMemo<TurnItem[]>(() => {
    const out: TurnItem[] = [];
    let lastUser = "";
    let lastUserId = "";
    let teamIdx = 0;
    for (const m of messages) {
      if (m.role === "user") {
        lastUser = m.content;
        lastUserId = m.id;
        continue;
      }
      if (m.role !== "assistant") continue;
      const turnId = assistantProjectionId(m);
      if (m.executionId) {
        const rt = teamRuntimes[teamIdx++];
        const exec = rt ? projectRuntime(rt) : null;
        out.push({
          id: turnId,
          kind: "team",
          exec,
          prompt: lastUser,
          answer: m.content,
          promptMessageId: lastUserId,
          answerMessageId: m.id,
          running: exec?.status === "running" || m.isStreaming,
          pendingDecisions: countPendingDecisions(m, exec, {
            conversationId,
          }),
          recoverable: isTurnRecoverable(exec),
        });
      } else {
        out.push({
          id: turnId,
          kind: "simple",
          exec: null,
          prompt: lastUser,
          answer: m.content,
          promptMessageId: lastUserId,
          answerMessageId: m.id,
          running: m.isStreaming,
          pendingDecisions: 0,
          recoverable: false,
        });
      }
    }
    return out;
  }, [messages, teamRuntimes, conversationId]);

  const latestTeamId = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].kind === "team") return turns[i].id;
    }
    return null;
  }, [turns]);

  useEffect(() => {
    if (latestTeamId) setFocusedTurn(latestTeamId);
  }, [latestTeamId, setFocusedTurn]);

  const effectiveFocus = useMemo(() => {
    if (
      focusedTurn &&
      turns.some((t) => t.id === focusedTurn && t.kind === "team")
    ) {
      return focusedTurn;
    }
    return latestTeamId;
  }, [focusedTurn, turns, latestTeamId]);

  const railItems = useMemo<TurnRailItem[]>(
    () =>
      turns.map((t) => ({
        id: t.id,
        kind: t.kind,
        status: t.exec?.status ?? null,
        running: t.running,
        pendingDecisions: t.pendingDecisions,
        recoverable: t.recoverable,
        label:
          t.exec?.taskSummary ||
          t.prompt ||
          (t.kind === "team" ? "团队回合" : "直接回答"),
      })),
    [turns],
  );

  return {
    turns,
    latestTeamId,
    effectiveFocus,
    railItems,
  };
}
