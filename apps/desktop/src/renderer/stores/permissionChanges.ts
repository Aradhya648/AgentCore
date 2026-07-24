import { isWebPreview } from "@/lib/preview";
import { fetchConversationAudit } from "@/services/audit";
import { useEffect } from "react";
import { create } from "zustand";

/**
 * 会话级「权限模式切换」store —— 聊天主流里那条系统提示行（权限模式 A → B）的数据源。
 *
 * 数据面复用既有会话级审计 REST（`GET …/audit?category=permission`），不新增 SSE / 契约 /
 * 后端接口。切换经 `PUT …/permission-preset` 在返回前**同步**写下一条 `permission.preset_changed`
 * 审计行（`turn_id = conversationId`，只进会话审计、不污染回合审计），故切换成功后由
 * {@link PermissionChangeState.load} 重新拉取即可拿到新行——无须乐观 id 拼接，`load` 直接以
 * 服务端权威列表覆盖。沿 `browserTakeover` 先例独立 store，隔离本模块便于并行开发。
 */

export type PermissionChange = {
  /** 审计行 id（时间线 key）。 */
  id: string;
  /** 切换发生时刻（ISO，用于时间线锚定）。 */
  at: string;
  /** 切换前的原始档位字符串。 */
  previous: string;
  /** 切换后的原始档位字符串。 */
  next: string;
};

/** 会话审计响应 → 权限切换列表（只取 preset_changed，快照/其他 permission 行忽略）。 */
function toChanges(
  rows: Awaited<ReturnType<typeof fetchConversationAudit>>,
): PermissionChange[] {
  return (rows?.data ?? [])
    .filter((e) => e.action === "permission.preset_changed")
    .map((e) => ({
      id: e.id,
      at: e.created_at,
      previous: String(e.detail?.previous ?? ""),
      next: String(e.detail?.permission_preset ?? ""),
    }));
}

interface PermissionChangeState {
  /** conversationId → 该会话的权限切换记录。 */
  byConversation: Record<string, PermissionChange[]>;
  /** 拉取会话权限审计并以服务端权威列表覆盖（404 → 空，不当硬错误）。 */
  load: (conversationId: string) => Promise<void>;
}

export const usePermissionChangeStore = create<PermissionChangeState>(
  (set) => ({
    byConversation: {},
    load: async (conversationId) => {
      const rows = await fetchConversationAudit(conversationId, {
        category: "permission",
      });
      set((s) => ({
        byConversation: {
          ...s.byConversation,
          [conversationId]: toChanges(rows),
        },
      }));
    },
  }),
);

const EMPTY: PermissionChange[] = [];

/** 选择器：某会话的权限切换记录（无 / 未加载时返回稳定空数组，避免重渲染）。 */
export function usePermissionChanges(
  conversationId: string | null,
): PermissionChange[] {
  return usePermissionChangeStore((s) =>
    conversationId ? (s.byConversation[conversationId] ?? EMPTY) : EMPTY,
  );
}

/**
 * 同步某会话的权限切换记录：打开会话时拉一次（best-effort——端点 404 / 旧后端静默降级，无红错、
 * 无系统行）。会话内新切换由 `PermissionPresetBadge` 切换成功后命令式重拉，故此处不轮询。
 * `#/preview` 离线回放不发网络请求。
 */
export function usePermissionChangesSync(conversationId: string | null): void {
  const load = usePermissionChangeStore((s) => s.load);
  useEffect(() => {
    if (conversationId && !isWebPreview()) {
      void load(conversationId).catch(() => {});
    }
  }, [conversationId, load]);
}
