/**
 * 一次性执行记录的 live-only 输出 buffer（仿 backgroundProcesses 姿态）。
 *
 * 消费 `tool_use_progress` phase="output" + {stream, chunk}；不进 journal。
 * 重载后清空，UI 回落 `tool_use_end.display` 的权威 stdout/stderr。
 */
import { appendUiOutput, stripAnsi } from "@/lib/processOutput";
import type { ToolUseProgressPayload } from "@/types/events";
import { create } from "zustand";

export interface ToolOutputLiveEntry {
  toolCallId: string;
  toolName: string;
  conversationId: string;
  startedAt: string;
  /** 工具结束时写入，供时长冻结；live-only。 */
  endedAt?: string;
  stdout: string;
  stderr: string;
}

interface ToolOutputLiveState {
  /** tool_call_id → live buffer。 */
  byId: Record<string, ToolOutputLiveEntry>;
  /** 当前选中的执行记录 id（与后台进程选中互斥，由 TerminalPanel 协调）。 */
  selectedId: string | null;

  seed: (opts: {
    toolCallId: string;
    toolName: string;
    conversationId: string;
  }) => void;
  appendProgress: (
    payload: ToolUseProgressPayload,
    conversationId: string,
  ) => void;
  /** 标记结束（冻结时长）；不删 buffer，供竞态帧回落。 */
  markEnded: (toolCallId: string) => void;
  clear: (toolCallId: string) => void;
  clearConversation: (conversationId: string) => void;
  select: (toolCallId: string | null) => void;
  entry: (toolCallId: string | null | undefined) => ToolOutputLiveEntry | null;
}

/** 从 progress payload 抽 output chunk（extra 键未进 generated 类型）。 */
export function progressOutputChunk(payload: ToolUseProgressPayload): {
  stream: "stdout" | "stderr" | string;
  chunk: string;
} | null {
  if (payload.phase !== "output") return null;
  const extra = payload as ToolUseProgressPayload & {
    stream?: unknown;
    chunk?: unknown;
  };
  const chunk = typeof extra.chunk === "string" ? extra.chunk : "";
  if (!chunk) return null;
  const stream = typeof extra.stream === "string" ? extra.stream : "stdout";
  return { stream, chunk };
}

export const useToolOutputLiveStore = create<ToolOutputLiveState>(
  (set, get) => ({
    byId: {},
    selectedId: null,

    seed: ({ toolCallId, toolName, conversationId }) => {
      set((s) => {
        const prev = s.byId[toolCallId];
        if (prev) return s;
        return {
          byId: {
            ...s.byId,
            [toolCallId]: {
              toolCallId,
              toolName,
              conversationId,
              startedAt: new Date().toISOString(),
              stdout: "",
              stderr: "",
            },
          },
        };
      });
    },

    appendProgress: (payload, conversationId) => {
      const out = progressOutputChunk(payload);
      if (!out) return;
      const cleaned = stripAnsi(out.chunk);
      set((s) => {
        const prev = s.byId[payload.tool_call_id];
        const base: ToolOutputLiveEntry = prev ?? {
          toolCallId: payload.tool_call_id,
          toolName: payload.tool_name,
          conversationId,
          startedAt: new Date().toISOString(),
          stdout: "",
          stderr: "",
        };
        const next: ToolOutputLiveEntry = {
          ...base,
          conversationId,
          toolName: payload.tool_name || base.toolName,
          stdout:
            out.stream === "stderr"
              ? base.stdout
              : appendUiOutput(base.stdout, cleaned),
          stderr:
            out.stream === "stderr"
              ? appendUiOutput(base.stderr, cleaned)
              : base.stderr,
        };
        return { byId: { ...s.byId, [payload.tool_call_id]: next } };
      });
    },

    markEnded: (toolCallId) => {
      set((s) => {
        const prev = s.byId[toolCallId];
        if (!prev || prev.endedAt) return s;
        return {
          byId: {
            ...s.byId,
            [toolCallId]: { ...prev, endedAt: new Date().toISOString() },
          },
        };
      });
    },

    clear: (toolCallId) => {
      set((s) => {
        if (!s.byId[toolCallId]) return s;
        const { [toolCallId]: _, ...rest } = s.byId;
        return {
          byId: rest,
          selectedId: s.selectedId === toolCallId ? null : s.selectedId,
        };
      });
    },

    clearConversation: (conversationId) => {
      set((s) => {
        const next: Record<string, ToolOutputLiveEntry> = {};
        for (const [id, e] of Object.entries(s.byId)) {
          if (e.conversationId !== conversationId) next[id] = e;
        }
        const selectedStill =
          s.selectedId && next[s.selectedId] ? s.selectedId : null;
        return { byId: next, selectedId: selectedStill };
      });
    },

    select: (toolCallId) => set({ selectedId: toolCallId }),

    entry: (toolCallId) => {
      if (!toolCallId) return null;
      return get().byId[toolCallId] ?? null;
    },
  }),
);
