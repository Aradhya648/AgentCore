import { loadLatestWindow } from "@/services/messages";

/**
 * 后台执行终态后的最小刷新：reload 最新消息窗以拉入 harvest 合成用户消息 + CEO 终稿。
 *
 * `execution_completed` 早于 harvest 落库；同连接内 terminal phase 会挡住 attach，
 * 故用短延迟重试覆盖收口回合写完窗口（离开再回来仍走 ConversationPage 正常加载）。
 */
export function refreshAfterExecutionCompleted(conversationId: string): void {
  const reload = (): void => {
    void loadLatestWindow(conversationId).catch(() => {
      /* best-effort */
    });
  };
  reload();
  window.setTimeout(reload, 1500);
  window.setTimeout(reload, 6000);
}
