/**
 * 删除裸聊时把其本地 scratch 子目录移入系统回收站（软删）。
 * 项目对话不碰共享工作区；空 subpath（整根）绝不清。失败只记日志，不阻断删对话。
 */

import { getConversations } from "@/hooks/useConversations";
import { resolveConversationLocalTarget } from "@/services/sidecarRouting";

export async function trashBareConversationScratch(
  conversationId: string,
): Promise<void> {
  if (!window.fsApi?.trashPath) return;
  const conv = getConversations().find((c) => c.id === conversationId);
  if (!conv || conv.folderId) return;

  try {
    const target = await resolveConversationLocalTarget(conversationId);
    if (!target?.subpath) return;
    const res = await window.fsApi.trashPath(target.rootId, target.subpath);
    if (!res.ok) {
      console.warn("[workspace] trash scratch failed", res.reason);
    }
  } catch (e) {
    console.warn("[workspace] trash scratch error", e);
  }
}
