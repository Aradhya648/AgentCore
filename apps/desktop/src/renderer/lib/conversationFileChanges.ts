/**
 * 本对话 AI 文件改动是否存在 —— 与 {@link ConversationChangesPanel} /
 * 产物卡同源（process + execution → fileArtifacts）。
 * 供右坞「改动」tab 条件显隐（前端UX设计.md §十）。
 */

import {
  fileArtifactsFromExecution,
  fileArtifactsFromProcess,
  mergeArtifacts,
} from "@/lib/fileArtifacts";
import { assistantProjectionId } from "@/stores/conversation/runtime";
import type { Message } from "@/stores/conversation/types";
import { type ExecutionRuntime, projectRuntime } from "@/stores/execution";

/** 当前对话 messages 是否已有至少一条成功的 AI 文件改动。 */
export function conversationHasFileArtifacts(
  messages: Message[],
  byId: Record<string, ExecutionRuntime>,
): boolean {
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    const messageId = assistantProjectionId(msg);
    const rt = byId[messageId];
    const execution = rt ? projectRuntime(rt) : null;
    const artifacts = mergeArtifacts(
      fileArtifactsFromProcess(msg.process),
      fileArtifactsFromExecution(execution),
    );
    if (artifacts.length > 0) return true;
  }
  return false;
}
