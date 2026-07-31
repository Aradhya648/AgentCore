/**
 * 用户交互 shell store —— 右坞「你的终端」单一数据源。
 *
 * 主进程持有权威 buffer；本 store 经 IPC list/read hydrate，订阅 pty:event 增量；
 * 选中会话时由 XtermView 挂载并回放 buffer / 接收 data。
 */
import { notifyActionError, notifyError } from "@/lib/toast";
import type {
  PtyEventPush,
  PtyReadValue,
  PtySessionItem,
  PtyStatus,
} from "@shared/pty-contract";
import { create } from "zustand";

export interface UserTerminalView {
  session_id: string;
  conversation_id: string;
  name: string;
  shell: string;
  index: number;
  status: PtyStatus;
  started_at: string;
  exit_code?: number | null;
  /** 原始 ANSI 输出（xterm 回放用；与 AI strip 路径分离）。 */
  output: string;
}

/** confirmOnKill busy：会话仍存活（无独立子进程字段，对齐 PtyStatus）。 */
export function isPtySessionBusy(session: {
  status: PtyStatus;
}): boolean {
  return session.status === "running";
}

export function countBusyPtySessions(
  sessions: ReadonlyArray<{ status: PtyStatus }>,
): number {
  return sessions.filter(isPtySessionBusy).length;
}

interface UserTerminalState {
  byConversation: Record<string, UserTerminalView[]>;
  selectedId: string | null;
  subscribed: boolean;

  ensureSubscribed: () => void;
  hydrateConversation: (conversationId: string) => Promise<void>;
  selectSession: (sessionId: string | null) => void;
  loadOutput: (sessionId: string) => Promise<void>;
  spawnSession: (args: {
    conversationId: string;
    rootId: string;
    subpath?: string;
  }) => Promise<
    { ok: true; session_id: string } | { ok: false; detail: string }
  >;
  /**
   * 关单会话。先等 IPC 成功再删 UI；失败保留会话并 toast。
   * @returns 是否已从 UI 移除
   */
  killSession: (sessionId: string) => Promise<boolean>;
  /**
   * 关对话下全部用户终端。先等 IPC 成功再清 UI；失败保留并 toast。
   * @returns 是否已清 UI
   */
  killConversation: (conversationId: string) => Promise<boolean>;
  writeInput: (sessionId: string, data: string) => void;
  resize: (sessionId: string, cols: number, rows: number) => void;
  /** 删对话等清理：异步杀干净（失败不乐观假清）。 */
  clearConversation: (conversationId: string) => void;
  applyEvent: (event: PtyEventPush) => void;
  sessionsFor: (conversationId: string | null) => UserTerminalView[];
}

/** 缺席会话的稳定空列表——Zustand getSnapshot 不可每次 `[]` 新引用。 */
const EMPTY_SESSIONS: UserTerminalView[] = [];

const UI_OUTPUT_CAP = 1024 * 1024;

function appendOutput(current: string, chunk: string): string {
  if (!chunk) return current;
  const next = current + chunk;
  if (next.length <= UI_OUTPUT_CAP) return next;
  return next.slice(next.length - UI_OUTPUT_CAP);
}

function fromItem(item: PtySessionItem, output = ""): UserTerminalView {
  return {
    session_id: item.session_id,
    conversation_id: item.conversation_id,
    name: item.name,
    shell: item.shell,
    index: item.index,
    status: item.status,
    started_at: item.started_at,
    exit_code: item.exit_code,
    output,
  };
}

function upsert(
  list: UserTerminalView[],
  next: UserTerminalView,
): UserTerminalView[] {
  const idx = list.findIndex((s) => s.session_id === next.session_id);
  if (idx < 0) return [...list, next];
  const copy = list.slice();
  copy[idx] = {
    ...copy[idx],
    ...next,
    output: next.output || copy[idx].output,
  };
  return copy;
}

export const useUserTerminalStore = create<UserTerminalState>((set, get) => ({
  byConversation: {},
  selectedId: null,
  subscribed: false,

  ensureSubscribed: () => {
    if (get().subscribed) return;
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    if (!api?.onEvent) return;
    set({ subscribed: true });
    api.onEvent((e) => get().applyEvent(e));
  },

  hydrateConversation: async (conversationId) => {
    get().ensureSubscribed();
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    if (!api?.list) {
      set((s) => ({
        byConversation: { ...s.byConversation, [conversationId]: [] },
      }));
      return;
    }
    try {
      const { sessions } = await api.list({ conversation_id: conversationId });
      set((s) => {
        const prev = s.byConversation[conversationId] ?? [];
        const prevOut = new Map(prev.map((p) => [p.session_id, p.output]));
        const next = sessions.map((item) =>
          fromItem(item, prevOut.get(item.session_id) ?? ""),
        );
        let selectedId = s.selectedId;
        if (selectedId && !next.some((p) => p.session_id === selectedId)) {
          selectedId = next[next.length - 1]?.session_id ?? null;
        }
        return {
          byConversation: { ...s.byConversation, [conversationId]: next },
          selectedId,
        };
      });
      const selected = get().selectedId;
      if (selected) void get().loadOutput(selected);
    } catch (e) {
      console.error("[userTerminals] list 失败", e);
    }
  },

  selectSession: (sessionId) => {
    set({ selectedId: sessionId });
    if (sessionId) void get().loadOutput(sessionId);
  },

  loadOutput: async (sessionId) => {
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    if (!api?.read) return;
    try {
      const result = await api.read({ session_id: sessionId });
      if (!result.ok) return;
      const value: PtyReadValue = result.value;
      set((s) => {
        const updated: Record<string, UserTerminalView[]> = {
          ...s.byConversation,
        };
        for (const [cid, list] of Object.entries(updated)) {
          const idx = list.findIndex((p) => p.session_id === sessionId);
          if (idx < 0) continue;
          const copy = list.slice();
          copy[idx] = {
            ...copy[idx],
            status: value.status,
            exit_code: value.exit_code ?? copy[idx].exit_code,
            output: value.output ?? "",
          };
          updated[cid] = copy;
        }
        return { byConversation: updated };
      });
    } catch (e) {
      console.error("[userTerminals] read 失败", e);
    }
  },

  spawnSession: async ({ conversationId, rootId, subpath }) => {
    get().ensureSubscribed();
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    if (!api?.spawn) {
      return { ok: false, detail: "终端能力不可用" };
    }
    const result = await api.spawn({
      conversation_id: conversationId,
      root_id: rootId,
      subpath: subpath || "",
    });
    if (!result.ok) {
      return { ok: false, detail: result.error.detail };
    }
    const view = fromItem(result.value.item);
    set((s) => {
      const list = s.byConversation[conversationId] ?? [];
      return {
        byConversation: {
          ...s.byConversation,
          [conversationId]: upsert(list, view),
        },
        selectedId: result.value.session_id,
      };
    });
    return { ok: true, session_id: result.value.session_id };
  },

  killSession: async (sessionId) => {
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    if (api?.kill) {
      try {
        const result = await api.kill({ session_id: sessionId });
        if (!result.ok) {
          notifyError(result.error.detail || "关闭终端失败");
          return false;
        }
      } catch (e) {
        notifyActionError("关闭终端失败", e);
        return false;
      }
    }

    set((s) => {
      const updated: Record<string, UserTerminalView[]> = {
        ...s.byConversation,
      };
      for (const [cid, list] of Object.entries(updated)) {
        const next = list.filter((p) => p.session_id !== sessionId);
        if (next.length !== list.length) updated[cid] = next;
      }
      return {
        byConversation: updated,
        selectedId: s.selectedId === sessionId ? null : s.selectedId,
      };
    });
    return true;
  },

  writeInput: (sessionId, data) => {
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    void api?.input?.({ session_id: sessionId, data });
  },

  resize: (sessionId, cols, rows) => {
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    void api?.resize?.({ session_id: sessionId, cols, rows });
  },

  killConversation: async (conversationId) => {
    const api = typeof window !== "undefined" ? window.ptyApi : undefined;
    if (api?.killConversation) {
      try {
        await api.killConversation({ conversation_id: conversationId });
      } catch (e) {
        notifyActionError("关闭终端失败", e);
        return false;
      }
    }

    set((s) => {
      const { [conversationId]: _, ...rest } = s.byConversation;
      const selectedStill =
        s.selectedId &&
        Object.values(rest).some((list) =>
          list.some((p) => p.session_id === s.selectedId),
        );
      return {
        byConversation: rest,
        selectedId: selectedStill ? s.selectedId : null,
      };
    });
    return true;
  },

  clearConversation: (conversationId) => {
    void get().killConversation(conversationId);
  },

  applyEvent: (event) => {
    if (event.type === "started") {
      const view = fromItem(event.item);
      set((s) => {
        const list = s.byConversation[event.conversation_id] ?? [];
        return {
          byConversation: {
            ...s.byConversation,
            [event.conversation_id]: upsert(list, view),
          },
          selectedId: s.selectedId ?? event.session_id,
        };
      });
      return;
    }
    if (event.type === "data") {
      set((s) => {
        const list = s.byConversation[event.conversation_id] ?? [];
        const idx = list.findIndex((p) => p.session_id === event.session_id);
        if (idx < 0) return s;
        const copy = list.slice();
        copy[idx] = {
          ...copy[idx],
          output: appendOutput(copy[idx].output, event.chunk),
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
        const idx = list.findIndex((p) => p.session_id === event.session_id);
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

  sessionsFor: (conversationId) => {
    if (!conversationId) return EMPTY_SESSIONS;
    return get().byConversation[conversationId] ?? EMPTY_SESSIONS;
  },
}));
