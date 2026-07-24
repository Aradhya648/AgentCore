/**
 * 裸聊本地 scratch 子路径（跨端契约：与服务端 `resolve_local_binding` 同形）。
 *
 * 容器根（`~/Documents/AgentCore`）只做父目录；每条裸聊落在
 * `conversations/<conversation_id>/`（懒建——首次写/打开时才 mkdir）。
 * 项目对话不走此路径（继承 Folder 的 root + subpath）。
 */
export function bareConversationScratchSubpath(conversationId: string): string {
  return `conversations/${conversationId}`;
}
