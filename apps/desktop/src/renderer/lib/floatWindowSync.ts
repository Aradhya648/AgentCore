/**
 * 真 OS 浮窗跨窗投影同步（UX §十 · 方案 C）。
 *
 * 主窗仍是 SSE / sidecar 权威；真窗经 BroadcastChannel 收快照/增量，
 * 禁止各自再开对话流抢权威。
 */

import {
  CHANGES_TAB_ID,
  WORKSPACE_TAB_ID,
  type DetailTab,
  useSidePanelStore,
} from "@/stores/sidePanel";
import {
  assistantProjectionId,
  runtimeOf,
  useConversationStore,
  type Message,
} from "@/stores/conversation";
import { EMPTY_RUNTIME } from "@/stores/conversation/runtime";
import {
  type ExecutionRuntime,
  useExecutionStore,
} from "@/stores/execution";
import {
  type InteractionEntry,
  useInteractionStore,
} from "@/stores/interactions";

export const FLOAT_WINDOW_SYNC_CHANNEL = "agentcore:float-window-projection";

export type FloatProjectionSnapshot = {
  conversationId: string;
  tabId: string;
  tabs: DetailTab[];
  changesFocusMessageId: string | null;
  messages: Message[];
  executions: Record<string, ExecutionRuntime>;
  interactions: InteractionEntry[];
};

export type FloatSyncMessage =
  | {
      type: "snapshot";
      conversationId: string;
      tabId: string;
      snapshot: FloatProjectionSnapshot;
    }
  | {
      type: "request";
      conversationId: string;
      tabId: string;
    }
  | {
      type: "focus";
      tabId: string;
    };

function messageIdsForTab(
  tabId: string,
  tabs: readonly DetailTab[],
  messages: readonly Message[],
): Set<string> {
  const ids = new Set<string>();
  if (tabId === WORKSPACE_TAB_ID) return ids;
  if (tabId === CHANGES_TAB_ID) {
    for (const msg of messages) {
      if (msg.role === "assistant") ids.add(assistantProjectionId(msg));
    }
    return ids;
  }
  const tab = tabs.find((t) => t.id === tabId);
  if (!tab) return ids;
  if (tab.kind === "run") ids.add(tab.messageId);
  if (tab.kind === "content") ids.add(tab.contentMessageId);
  if (tab.kind === "simple-turn") {
    ids.add(tab.promptMessageId);
    if (tab.answerMessageId) ids.add(tab.answerMessageId);
  }
  return ids;
}

/** Build a projection snapshot from main-window stores for one float tab. */
export function buildFloatProjectionSnapshot(
  conversationId: string,
  tabId: string,
): FloatProjectionSnapshot {
  const side = useSidePanelStore.getState();
  const conv = useConversationStore.getState();
  const runtime = runtimeOf(conv, conversationId);
  const execById = useExecutionStore.getState().byId;
  const needed = messageIdsForTab(tabId, side.tabs, runtime.messages);
  const executions: Record<string, ExecutionRuntime> = {};
  for (const mid of needed) {
    const slot = execById[mid];
    if (slot) executions[mid] = slot;
  }
  return {
    conversationId,
    tabId,
    tabs: [...side.tabs],
    changesFocusMessageId: side.changesFocusMessageId,
    messages: runtime.messages,
    executions,
    interactions: useInteractionStore
      .getState()
      .listForConversation(conversationId),
  };
}

/** Hydrate float-window stores from a main-window snapshot (no SSE). */
export function applyFloatProjectionSnapshot(
  snapshot: FloatProjectionSnapshot,
): void {
  const { conversationId } = snapshot;

  useConversationStore.setState((s) => {
    const prev = s.byId[conversationId] ?? EMPTY_RUNTIME;
    return {
      currentConversationId: conversationId,
      byId: {
        ...s.byId,
        [conversationId]: {
          ...prev,
          messages: snapshot.messages,
          // Float window is not the stream owner.
          abort: null,
        },
      },
    };
  });

  useExecutionStore.setState((s) => ({
    byId: { ...s.byId, ...snapshot.executions },
  }));

  useSidePanelStore.setState((s) => {
    const byId = new Map(s.tabs.map((t) => [t.id, t] as const));
    for (const t of snapshot.tabs) byId.set(t.id, t);
    return {
      tabs: [...byId.values()],
      changesFocusMessageId: snapshot.changesFocusMessageId,
    };
  });

  useInteractionStore.setState((s) => {
    const next = new Map(s.byId);
    for (const [id, entry] of next) {
      if (entry.conversationId === conversationId) next.delete(id);
    }
    for (const entry of snapshot.interactions) {
      next.set(entry.id, entry);
    }
    return { byId: next };
  });
}

export function isFloatSyncMessage(raw: unknown): raw is FloatSyncMessage {
  if (!raw || typeof raw !== "object") return false;
  const msg = raw as { type?: unknown };
  if (msg.type === "snapshot") {
    const s = raw as FloatSyncMessage & { snapshot?: unknown };
    return (
      typeof (raw as { conversationId?: unknown }).conversationId ===
        "string" &&
      typeof (raw as { tabId?: unknown }).tabId === "string" &&
      !!s.snapshot &&
      typeof s.snapshot === "object"
    );
  }
  if (msg.type === "request" || msg.type === "focus") {
    return (
      typeof (raw as { tabId?: unknown }).tabId === "string" &&
      (msg.type === "focus" ||
        typeof (raw as { conversationId?: unknown }).conversationId ===
          "string")
    );
  }
  return false;
}

type ChannelLike = {
  postMessage: (data: FloatSyncMessage) => void;
  close: () => void;
  onmessage: ((ev: MessageEvent<unknown>) => void) | null;
};

/** Test seam / production BroadcastChannel. */
export function openFloatSyncChannel(
  factory?: () => ChannelLike,
): ChannelLike | null {
  if (factory) return factory();
  if (typeof BroadcastChannel === "undefined") return null;
  return new BroadcastChannel(
    FLOAT_WINDOW_SYNC_CHANNEL,
  ) as unknown as ChannelLike;
}

export function postFloatSync(
  channel: ChannelLike | null,
  message: FloatSyncMessage,
): void {
  channel?.postMessage(message);
}
