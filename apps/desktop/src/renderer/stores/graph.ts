import {
  createZustandUiStorage,
  registerConversationUiClearer,
} from "@/lib/uiStorage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** Structural edge. Visual state (animated) is derived live.
 *
 * `dep` (default) is a DAG dependency / input·captain bookend flow; `delegate`
 * is a captain worker → its nested sub-worker (阶段2 父子分组), drawn distinctly
 * (dashed) so a sub-team reads as grouped under the parent rather than as another
 * top-level branch; `revision` is an original worker → its「修订 vN」续写 child
 * (乙 热修 P4), drawn distinctly (dotted) so a re-do reads as a version of the same
 * node, not a new branch; `handoff` is 回落换人「接替」(replaces_run_id → new worker). */
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind?: "dep" | "delegate" | "continuation" | "inject" | "handoff";
}

/**
 * Collaboration-graph layout algorithm (user-switchable from the canvas
 * toolbar). `leftright` is the default left-to-right layered flow — it suits the
 * widescreen displays the desktop targets and keeps the inline↔full-screen
 * direction consistent (no 90° flip on maximize); `tree` is the same layered
 * algorithm rotated top-down.
 */
export type GraphLayout = "tree" | "leftright";

/** Max team turns expanded as TurnGroupNode compounds on the conversation spine. */
export const MAX_EXPANDED_TURNS = 3;

const LAYOUTS: GraphLayout[] = ["tree", "leftright"];

export interface ConversationFoldState {
  /** Parent run ids whose subtrees are folded away (+N badge). */
  collapsedSubtrees: string[];
  /** Parents already seeded into collapsedSubtrees (so expand sticks). */
  seenSubtreeParents: string[];
  /** Expanded team-turn ids on the spine, oldest→newest (LRU eviction). */
  expandedTurns: string[];
  /** Whether default expandedTurns have been seeded for this conversation. */
  turnsSeeded: boolean;
}

const EMPTY_FOLD: ConversationFoldState = {
  collapsedSubtrees: [],
  seenSubtreeParents: [],
  expandedTurns: [],
  turnsSeeded: false,
};

const uiPersistStorage = createJSONStorage(() => createZustandUiStorage());

function foldOf(
  byConversation: Record<string, ConversationFoldState>,
  conversationId: string | null | undefined,
): ConversationFoldState {
  if (!conversationId) return EMPTY_FOLD;
  return byConversation[conversationId] ?? EMPTY_FOLD;
}

function patchFold(
  byConversation: Record<string, ConversationFoldState>,
  conversationId: string,
  patch: Partial<ConversationFoldState>,
): Record<string, ConversationFoldState> {
  const prev = byConversation[conversationId] ?? EMPTY_FOLD;
  return {
    ...byConversation,
    [conversationId]: { ...prev, ...patch },
  };
}

// Per-graph layout (ELK positions + structural edges) is NOT global state: with
// §9.3 every multi-agent message renders its own inline graph, so the layout is
// view state owned locally by each {@link GraphView}. Only the *choice* of layout
// algorithm is global — it is a user preference that applies to every graph and
// persists across sessions. Fold / expand prefs are per-conversation.
interface GraphState {
  /** Active layout algorithm — a shared, persisted user preference. */
  layoutKind: GraphLayout;
  setLayoutKind: (kind: GraphLayout) => void;
  /** Phase 2: always show audit-confirmed inject edges on the collaboration graph. */
  showAuditInjectFlow: boolean;
  setShowAuditInjectFlow: (on: boolean) => void;

  /** Per-conversation fold / expand prefs (persisted). */
  foldByConversation: Record<string, ConversationFoldState>;

  toggleSubtreeCollapsed: (conversationId: string, parentId: string) => void;
  setSubtreeCollapsed: (
    conversationId: string,
    parentId: string,
    collapsed: boolean,
  ) => void;
  /** Seed newly discovered foldable parents as collapsed (default). */
  ensureSubtreeDefaults: (conversationId: string, parentIds: string[]) => void;

  expandTurn: (conversationId: string, turnId: string) => void;
  collapseTurn: (conversationId: string, turnId: string) => void;
  /** First-open: expand completed team turns (cap MAX_EXPANDED_TURNS, newest first). */
  ensureDefaultExpandedTurns: (
    conversationId: string,
    teamTurnIdsNewestFirst: string[],
  ) => void;
}

export const useGraphStore = create<GraphState>()(
  persist(
    (set, get) => ({
      layoutKind: "leftright",
      showAuditInjectFlow: false,
      foldByConversation: {},

      setLayoutKind: (layoutKind) => {
        if (!(LAYOUTS as string[]).includes(layoutKind)) return;
        set({ layoutKind });
      },

      setShowAuditInjectFlow: (showAuditInjectFlow) => {
        set({ showAuditInjectFlow });
      },

      toggleSubtreeCollapsed: (conversationId, parentId) => {
        const prev = foldOf(get().foldByConversation, conversationId);
        const has = prev.collapsedSubtrees.includes(parentId);
        const collapsedSubtrees = has
          ? prev.collapsedSubtrees.filter((id) => id !== parentId)
          : [...prev.collapsedSubtrees, parentId];
        set({
          foldByConversation: patchFold(
            get().foldByConversation,
            conversationId,
            {
              collapsedSubtrees,
            },
          ),
        });
      },

      setSubtreeCollapsed: (conversationId, parentId, collapsed) => {
        const prev = foldOf(get().foldByConversation, conversationId);
        const has = prev.collapsedSubtrees.includes(parentId);
        if (collapsed === has) return;
        const collapsedSubtrees = collapsed
          ? [...prev.collapsedSubtrees, parentId]
          : prev.collapsedSubtrees.filter((id) => id !== parentId);
        set({
          foldByConversation: patchFold(
            get().foldByConversation,
            conversationId,
            {
              collapsedSubtrees,
            },
          ),
        });
      },

      ensureSubtreeDefaults: (conversationId, parentIds) => {
        if (parentIds.length === 0) return;
        const prev = foldOf(get().foldByConversation, conversationId);
        const seen = new Set(prev.seenSubtreeParents);
        const fresh = parentIds.filter((id) => !seen.has(id));
        if (fresh.length === 0) return;
        set({
          foldByConversation: patchFold(
            get().foldByConversation,
            conversationId,
            {
              collapsedSubtrees: [...prev.collapsedSubtrees, ...fresh],
              seenSubtreeParents: [...prev.seenSubtreeParents, ...fresh],
            },
          ),
        });
      },

      expandTurn: (conversationId, turnId) => {
        const prev = foldOf(get().foldByConversation, conversationId);
        const without = prev.expandedTurns.filter((id) => id !== turnId);
        const expandedTurns = [...without, turnId];
        while (expandedTurns.length > MAX_EXPANDED_TURNS) {
          expandedTurns.shift();
        }
        set({
          foldByConversation: patchFold(
            get().foldByConversation,
            conversationId,
            {
              expandedTurns,
            },
          ),
        });
      },

      collapseTurn: (conversationId, turnId) => {
        const prev = foldOf(get().foldByConversation, conversationId);
        if (!prev.expandedTurns.includes(turnId)) return;
        set({
          foldByConversation: patchFold(
            get().foldByConversation,
            conversationId,
            {
              expandedTurns: prev.expandedTurns.filter((id) => id !== turnId),
            },
          ),
        });
      },

      ensureDefaultExpandedTurns: (conversationId, teamTurnIdsNewestFirst) => {
        const prev = foldOf(get().foldByConversation, conversationId);
        if (prev.turnsSeeded) return;
        if (teamTurnIdsNewestFirst.length === 0) return;
        const expandedTurns = teamTurnIdsNewestFirst
          .slice(0, MAX_EXPANDED_TURNS)
          .reverse(); // oldest→newest among the kept window
        set({
          foldByConversation: patchFold(
            get().foldByConversation,
            conversationId,
            {
              expandedTurns,
              turnsSeeded: true,
            },
          ),
        });
      },
    }),
    {
      name: "graph",
      storage: uiPersistStorage,
      partialize: (s) => ({
        layoutKind: s.layoutKind,
        showAuditInjectFlow: s.showAuditInjectFlow,
        foldByConversation: s.foldByConversation,
      }),
    },
  ),
);

registerConversationUiClearer((conversationId) => {
  const { foldByConversation } = useGraphStore.getState();
  if (!(conversationId in foldByConversation)) return;
  const next = { ...foldByConversation };
  delete next[conversationId];
  useGraphStore.setState({ foldByConversation: next });
});

/** Read fold state for a conversation (stable empty when missing). */
export function selectConversationFold(
  conversationId: string | null | undefined,
): ConversationFoldState {
  return foldOf(useGraphStore.getState().foldByConversation, conversationId);
}

export function useConversationFold(
  conversationId: string | null | undefined,
): ConversationFoldState {
  return useGraphStore((s) => foldOf(s.foldByConversation, conversationId));
}
