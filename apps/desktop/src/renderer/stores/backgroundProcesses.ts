/**
 * 后台进程 store —— 终端 tab 的单一数据源（列表 + 选中输出）。
 *
 * 主进程持有权威 buffer；本 store 经 IPC list/read hydrate，并订阅 process:event 增量。
 */
import {
  appendUiOutput,
  shouldShowTerminalTab,
  stripAnsi,
} from "@/lib/processOutput";
import type {
  ProcessEventPush,
  ProcessListItem,
  ProcessOpValue,
  ProcessStatus,
} from "@shared/process-contract";
import { create } from "zustand";

export interface BackgroundProcessView {
  process_id: string;
  conversation_id: string;
  name?: string;
  command: string;
  status: ProcessStatus;
  started_at: string;
  exit_code?: number | null;
  /** 已 strip ANSI 的滚屏文本。 */
  output: string;
}

interface BackgroundProcessState {
  /** conversationId → 进程列表（含已退出）。 */
  byConversation: Record<string, BackgroundProcessView[]>;
  /** 当前选中的 process_id（跨对话切换时保留，无效则回落）。 */
  selectedId: string | null;
  /** 是否已挂上主进程 event 订阅。 */
  subscribed: boolean;

  ensureSubscribed: () => void;
  hydrateConversation: (conversationId: string) => Promise<void>;
  selectProcess: (processId: string | null) => void;
  loadOutput: (processId: string) => Promise<void>;
  stopProcess: (processId: string) => Promise<void>;
  clearConversation: (conversationId: string) => void;
  applyEvent: (event: ProcessEventPush) => void;
  processesFor: (conversationId: string | null) => BackgroundProcessView[];
  showTabFor: (conversationId: string | null) => boolean;
}

/** 缺席会话的稳定空列表——Zustand getSnapshot 不可每次 `[]` 新引用。 */
const EMPTY_PROCESSES: BackgroundProcessView[] = [];

function upsert(
  list: BackgroundProcessView[],
  next: BackgroundProcessView,
): BackgroundProcessView[] {
  const idx = list.findIndex((p) => p.process_id === next.process_id);
  if (idx < 0) return [...list, next];
  const copy = list.slice();
  copy[idx] = {
    ...copy[idx],
    ...next,
    output: next.output || copy[idx].output,
  };
  return copy;
}

function fromListItem(
  item: ProcessListItem,
  conversationId: string,
  output = "",
): BackgroundProcessView {
  return {
    process_id: item.process_id,
    conversation_id: conversationId,
    name: item.name,
    command: item.command,
    status: item.status,
    started_at: item.started_at,
    exit_code: item.exit_code,
    output,
  };
}

export const useBackgroundProcessStore = create<BackgroundProcessState>(
  (set, get) => ({
    byConversation: {},
    selectedId: null,
    subscribed: false,

    ensureSubscribed: () => {
      if (get().subscribed) return;
      const api = typeof window !== "undefined" ? window.processApi : undefined;
      if (!api?.onEvent) return;
      set({ subscribed: true });
      api.onEvent((e) => get().applyEvent(e));
    },

    hydrateConversation: async (conversationId) => {
      get().ensureSubscribed();
      const api = typeof window !== "undefined" ? window.processApi : undefined;
      if (!api?.list) {
        set((s) => ({
          byConversation: { ...s.byConversation, [conversationId]: [] },
        }));
        return;
      }
      try {
        const { processes } = await api.list({
          conversation_id: conversationId,
        });
        set((s) => {
          const prev = s.byConversation[conversationId] ?? [];
          const prevOut = new Map(prev.map((p) => [p.process_id, p.output]));
          const next = processes.map((item) =>
            fromListItem(
              item,
              conversationId,
              prevOut.get(item.process_id) ?? "",
            ),
          );
          let selectedId = s.selectedId;
          if (selectedId && !next.some((p) => p.process_id === selectedId)) {
            selectedId = next[next.length - 1]?.process_id ?? null;
          } else if (!selectedId && next.length > 0) {
            selectedId = next[next.length - 1]?.process_id ?? null;
          }
          return {
            byConversation: { ...s.byConversation, [conversationId]: next },
            selectedId,
          };
        });
        const selected = get().selectedId;
        if (selected) void get().loadOutput(selected);
      } catch (e) {
        console.error("[backgroundProcesses] list 失败", e);
      }
    },

    selectProcess: (processId) => {
      set({ selectedId: processId });
      if (processId) void get().loadOutput(processId);
    },

    loadOutput: async (processId) => {
      const api = typeof window !== "undefined" ? window.processApi : undefined;
      if (!api?.read) return;
      try {
        const value: ProcessOpValue = await api.read({ process_id: processId });
        const text = stripAnsi(value.output ?? "");
        set((s) => {
          const updated: Record<string, BackgroundProcessView[]> = {
            ...s.byConversation,
          };
          for (const [cid, list] of Object.entries(updated)) {
            const idx = list.findIndex((p) => p.process_id === processId);
            if (idx < 0) continue;
            const copy = list.slice();
            copy[idx] = {
              ...copy[idx],
              status: value.status,
              exit_code: value.exit_code ?? copy[idx].exit_code,
              output: text,
            };
            updated[cid] = copy;
          }
          return { byConversation: updated };
        });
      } catch (e) {
        console.error("[backgroundProcesses] read 失败", e);
      }
    },

    stopProcess: async (processId) => {
      const api = typeof window !== "undefined" ? window.processApi : undefined;
      if (!api?.stop) return;
      try {
        const value = await api.stop({ process_id: processId });
        set((s) => {
          const updated: Record<string, BackgroundProcessView[]> = {
            ...s.byConversation,
          };
          for (const [cid, list] of Object.entries(updated)) {
            const idx = list.findIndex((p) => p.process_id === processId);
            if (idx < 0) continue;
            const copy = list.slice();
            copy[idx] = {
              ...copy[idx],
              status: value.status,
              exit_code: value.exit_code ?? copy[idx].exit_code,
              output: value.output ? stripAnsi(value.output) : copy[idx].output,
            };
            updated[cid] = copy;
          }
          return { byConversation: updated };
        });
      } catch (e) {
        console.error("[backgroundProcesses] stop 失败", e);
      }
    },

    clearConversation: (conversationId) => {
      const api = typeof window !== "undefined" ? window.processApi : undefined;
      void api?.killConversation?.({ conversation_id: conversationId });
      set((s) => {
        const { [conversationId]: _, ...rest } = s.byConversation;
        const selectedStill =
          s.selectedId &&
          Object.values(rest).some((list) =>
            list.some((p) => p.process_id === s.selectedId),
          );
        return {
          byConversation: rest,
          selectedId: selectedStill ? s.selectedId : null,
        };
      });
    },

    applyEvent: (event) => {
      if (event.type === "started") {
        const view = fromListItem(event.item, event.conversation_id);
        set((s) => {
          const list = s.byConversation[event.conversation_id] ?? [];
          return {
            byConversation: {
              ...s.byConversation,
              [event.conversation_id]: upsert(list, view),
            },
            selectedId: s.selectedId ?? event.process_id,
          };
        });
        return;
      }
      if (event.type === "output") {
        const chunk = stripAnsi(event.chunk);
        set((s) => {
          const list = s.byConversation[event.conversation_id] ?? [];
          const idx = list.findIndex((p) => p.process_id === event.process_id);
          if (idx < 0) return s;
          const copy = list.slice();
          copy[idx] = {
            ...copy[idx],
            output: appendUiOutput(copy[idx].output, chunk),
          };
          return {
            byConversation: {
              ...s.byConversation,
              [event.conversation_id]: copy,
            },
          };
        });
        return;
      }
      if (event.type === "exited") {
        set((s) => {
          const list = s.byConversation[event.conversation_id] ?? [];
          const idx = list.findIndex((p) => p.process_id === event.process_id);
          if (idx < 0) return s;
          const copy = list.slice();
          copy[idx] = {
            ...copy[idx],
            status: "exited",
            exit_code: event.exit_code,
          };
          return {
            byConversation: {
              ...s.byConversation,
              [event.conversation_id]: copy,
            },
          };
        });
      }
    },

    processesFor: (conversationId) => {
      if (!conversationId) return EMPTY_PROCESSES;
      return get().byConversation[conversationId] ?? EMPTY_PROCESSES;
    },

    showTabFor: (conversationId) =>
      shouldShowTerminalTab(get().processesFor(conversationId).length),
  }),
);
