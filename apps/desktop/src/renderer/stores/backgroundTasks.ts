import { type HandoffJob, listHandoffJobs } from "@/services/handoff";
import {
  type WorkspaceMode,
  getWorkspaceBinding,
} from "@/services/workspaceBinding";
import { useEffect } from "react";
import { create } from "zustand";

/**
 * 后台云端任务 store（双模式工作区 P2e —— 交接的「方案 B」前端态）。
 *
 * 把本地→云交接从工作区侧栏的孤岛搬进对话：一条本地模式对话「在云端后台跑」的任务
 * 就是这里的一项。数据沿用 `services/handoff` 的 `HandoffJob`（后端 `/handoff/jobs`
 * 持久化），故卡片随对话重开自然重放——无需在消息表另落占位行（方案 i 的「原位重放」
 * 目标用「按时间戳并入时间线」达成，零 schema 改动）。
 *
 * `modeByConversation` 缓存每个对话的云/本地判定（`getWorkspaceBinding`），供输入框的
 * 「后台」开关与本 feed 共用一次请求（`ensureMode` 去重并发拉取）——交接只在本地模式
 * 存在，故云端对话零额外拉取。
 */
interface BackgroundTasksState {
  /** conversationId → 其后台云端任务（后端按创建倒序返回）。 */
  byConversation: Record<string, HandoffJob[]>;
  /** conversationId → 工作区模式（cloud / local），解析后缓存。 */
  modeByConversation: Record<string, WorkspaceMode>;
  /** conversationId → 绑定的本地根 id（本地模式才有；云端 / 未解析为 null）。 */
  rootIdByConversation: Record<string, string | null>;
  /** 用服务端权威列表覆盖某对话的任务（`listHandoffJobs`）。 */
  load: (conversationId: string) => Promise<void>;
  /** 插入 / 替换单项（乐观派发的临时项，或轮询刷新）。 */
  upsert: (conversationId: string, job: HandoffJob) => void;
  /**
   * 解析并缓存某对话的工作区模式 + 绑定根 id；与输入框共用，去重并发请求。失败回落
   * cloud / null。返回 mode（rootId 经 `useWorkspaceRootId` 读取，供成功任务的内联评审
   * 写回本地用）。
   */
  ensureMode: (conversationId: string) => Promise<WorkspaceMode>;
  /** 删除对话时丢掉该会话的任务列表 / 模式缓存，避免分桶泄漏。 */
  clearConversation: (conversationId: string) => void;
}

/** ensureMode 的并发去重：同一对话多处同时问模式，只打一次 binding 请求。 */
const modeInFlight = new Map<string, Promise<WorkspaceMode>>();

export const useBackgroundTasksStore = create<BackgroundTasksState>(
  (set, get) => ({
    byConversation: {},
    modeByConversation: {},
    rootIdByConversation: {},
    load: async (conversationId) => {
      const jobs = await listHandoffJobs(conversationId);
      set((s) => ({
        byConversation: { ...s.byConversation, [conversationId]: jobs },
      }));
    },
    upsert: (conversationId, job) =>
      set((s) => {
        const prev = s.byConversation[conversationId] ?? [];
        const next = prev.some((j) => j.id === job.id)
          ? prev.map((j) => (j.id === job.id ? job : j))
          : [job, ...prev];
        return {
          byConversation: { ...s.byConversation, [conversationId]: next },
        };
      }),
    ensureMode: async (conversationId) => {
      const cached = get().modeByConversation[conversationId];
      if (cached) return cached;
      const pending = modeInFlight.get(conversationId);
      if (pending) return pending;
      const p = (async () => {
        let mode: WorkspaceMode = "cloud";
        let rootId: string | null = null;
        try {
          const binding = await getWorkspaceBinding(conversationId);
          mode = binding.mode;
          rootId = binding.rootId;
        } catch {
          // Binding unknown (e.g. a never-sent draft) — treat as cloud so the
          // background entry stays hidden and the feed never lists.
        }
        set((s) => ({
          modeByConversation: {
            ...s.modeByConversation,
            [conversationId]: mode,
          },
          rootIdByConversation: {
            ...s.rootIdByConversation,
            [conversationId]: rootId,
          },
        }));
        modeInFlight.delete(conversationId);
        return mode;
      })();
      modeInFlight.set(conversationId, p);
      return p;
    },
    clearConversation: (conversationId) => {
      modeInFlight.delete(conversationId);
      set((s) => {
        const { [conversationId]: _jobs, ...byConversation } = s.byConversation;
        const { [conversationId]: _mode, ...modeByConversation } =
          s.modeByConversation;
        const { [conversationId]: _root, ...rootIdByConversation } =
          s.rootIdByConversation;
        return { byConversation, modeByConversation, rootIdByConversation };
      });
    },
  }),
);

const EMPTY: HandoffJob[] = [];

/** 选择器：某对话的后台云端任务（无 / 未加载时返回稳定空数组，避免重渲染）。 */
export function useBackgroundTasks(
  conversationId: string | null,
): HandoffJob[] {
  return useBackgroundTasksStore((s) =>
    conversationId ? (s.byConversation[conversationId] ?? EMPTY) : EMPTY,
  );
}

/**
 * 选择器：某对话绑定的本地根 id（`ensureMode` 解析后才有）。供成功任务的内联评审把
 * 云端结果写回本地（`readLocalShas` / `applyHandoffJob` 都按根 id 在绑定根上履行 op）。
 * 云端 / 未解析 / 解析失败为 null —— 此时卡片不提供评审入口。
 */
export function useWorkspaceRootId(
  conversationId: string | null,
): string | null {
  return useBackgroundTasksStore((s) =>
    conversationId ? (s.rootIdByConversation[conversationId] ?? null) : null,
  );
}

/**
 * 同步某对话的后台云端任务：模式解析为 local 时拉一次列表，并在有进行中任务时轮询
 * （MVP=轮询，4s，与原交接面板同节奏）。云端对话不拉取。
 */
export function useBackgroundTasksSync(conversationId: string | null): void {
  const ensureMode = useBackgroundTasksStore((s) => s.ensureMode);
  const load = useBackgroundTasksStore((s) => s.load);
  const mode = useBackgroundTasksStore((s) =>
    conversationId ? s.modeByConversation[conversationId] : undefined,
  );
  const tasks = useBackgroundTasks(conversationId);
  const inFlight = tasks.some(
    (t) => t.status === "pending" || t.status === "running",
  );

  useEffect(() => {
    if (conversationId) void ensureMode(conversationId);
  }, [conversationId, ensureMode]);

  useEffect(() => {
    if (!conversationId || mode !== "local") return;
    void load(conversationId).catch(() => {});
  }, [conversationId, mode, load]);

  useEffect(() => {
    if (!conversationId || mode !== "local" || !inFlight) return;
    const id = setInterval(
      () => void load(conversationId).catch(() => {}),
      4000,
    );
    return () => clearInterval(id);
  }, [conversationId, mode, inFlight, load]);
}
