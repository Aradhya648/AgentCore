import {
  type BrowserTakeoverRecord,
  listBrowserTakeovers,
} from "@/services/browserTakeover";
import { useEffect } from "react";
import { create } from "zustand";

/**
 * L3「团队浏览器」M2 接管留档 store（提案 D17）。
 *
 * 时间线的「用户接管了浏览器」标记卡的数据源。仿「记忆更新卡」先例双源合并：
 *  - **GET takeovers**（{@link listBrowserTakeovers}）= 服务端权威列表，会话打开时拉一次 →
 *    刷新/回放可重建（数据在表里）；
 *  - **store 合并**（{@link BrowserTakeoverState.addLocal}）= BrowserLivePanel 归还控制时把本场
 *    接管乐观并入，卡片即时可见，无需等重新拉取。
 *
 * 用独立 store（非塞进庞大的 conversation store）隔离本模块，便于并行开发——沿
 * `backgroundTasks` 先例。本地乐观项用 `local:` 前缀 id，与服务端 id 天然不撞；`load` 合并时
 * 保留尚未被服务端收录的本地项，避免慢速 GET 在竞态里抹掉刚记的接管。
 */

export type BrowserTakeover = BrowserTakeoverRecord;

interface BrowserTakeoverState {
  /** conversationId → 该会话的接管留档（起止 + 时长）。 */
  byConversation: Record<string, BrowserTakeover[]>;
  /** 用服务端权威列表覆盖某会话，保留尚未被收录的本地乐观项（去重按 id）。 */
  load: (conversationId: string) => Promise<void>;
  /** 归还控制时乐观并入本场接管（自铸 `local:` id）；卡片即时可见。 */
  addLocal: (
    conversationId: string,
    startedAt: string,
    endedAt: string,
  ) => void;
  /** 删除对话时丢掉该会话的留档，避免分桶泄漏。 */
  clearConversation: (conversationId: string) => void;
}

export const useBrowserTakeoverStore = create<BrowserTakeoverState>((set) => ({
  byConversation: {},
  load: async (conversationId) => {
    const server = await listBrowserTakeovers(conversationId);
    set((s) => {
      const existing = s.byConversation[conversationId] ?? [];
      const serverIds = new Set(server.map((t) => t.id));
      const localOnly = existing.filter((t) => !serverIds.has(t.id));
      return {
        byConversation: {
          ...s.byConversation,
          [conversationId]: [...server, ...localOnly],
        },
      };
    });
  },
  addLocal: (conversationId, startedAt, endedAt) =>
    set((s) => {
      const existing = s.byConversation[conversationId] ?? [];
      const record: BrowserTakeover = {
        id: `local:${crypto.randomUUID()}`,
        startedAt,
        endedAt,
      };
      return {
        byConversation: {
          ...s.byConversation,
          [conversationId]: [...existing, record],
        },
      };
    }),
  clearConversation: (conversationId) =>
    set((s) => {
      if (!(conversationId in s.byConversation)) return s;
      const { [conversationId]: _drop, ...byConversation } = s.byConversation;
      return { byConversation };
    }),
}));

const EMPTY: BrowserTakeover[] = [];

/** 选择器：某会话的接管留档（无 / 未加载时返回稳定空数组，避免重渲染）。 */
export function useBrowserTakeovers(
  conversationId: string | null,
): BrowserTakeover[] {
  return useBrowserTakeoverStore((s) =>
    conversationId ? (s.byConversation[conversationId] ?? EMPTY) : EMPTY,
  );
}

/**
 * 同步某会话的接管留档：打开会话时拉一次 GET takeovers（best-effort——端点缺失/旧后端 404
 * 静默降级，无红错、无标记卡）。会话内新接管由 BrowserLivePanel 经 `addLocal` 乐观并入，故此处
 * 不轮询。
 */
export function useBrowserTakeoversSync(conversationId: string | null): void {
  const load = useBrowserTakeoverStore((s) => s.load);
  useEffect(() => {
    if (conversationId) void load(conversationId).catch(() => {});
  }, [conversationId, load]);
}
