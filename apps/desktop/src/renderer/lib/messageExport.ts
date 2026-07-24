/**
 * 消息出口文案（仅交付 / 含过程）。
 *
 * `messages.content` 只留最终交付（deliverable_only）；气泡过程时间线另有旁白与工具。
 * 复制/分享提供两档：默认仅交付；「含过程」按 process 时序拼可读文本。
 * 搜索与下轮 history 仍只用交付正文——本模块只服务出口，不改持久化契约。
 */

import type { ProcessStep } from "@/types/events";

export type MessageCopyMode = "deliverable" | "with_process";

/** Chrome labels for copy text — keep in sync with message-bubble/constants TOOL_META. */
const TOOL_LABEL: Record<string, string> = {
  web_search: "Search web",
  read_url: "Read page",
  grep: "Grep code",
  code_search: "Search code",
  code_execute: "Run code",
  terminal: "Run terminal",
  test_run: "Run tests",
  git: "Git",
  file_read: "Read file",
  file_write: "Write file",
  file_append: "Append file",
  file_list: "List dir",
  str_replace: "Edit file",
  file_delete: "Delete file",
  file_move: "Move file",
  file_copy: "Copy file",
  mkdir: "Make dir",
  file_batch: "Batch files",
  delegate: "Delegate",
  replan: "Replan",
  debate: "Debate",
  ask_user: "Ask you",
  consult_skill: "Consult skill",
  consult_memory: "Consult memory",
  revise: "Revise",
  escalate: "Escalate",
  update_synthesis: "Update synthesis",
  cancel_worker: "Cancel worker",
  resolve_escalation: "Resolve escalate",
  queue_user_message: "Queue message",
  post_note: "Post note",
  read_notes: "Read notes",
  amend_note: "Amend note",
  handoff: "Handoff",
  board_ops: "Edit board",
  board_read: "Read board",
  desktop_notify: "Notify",
};

const TOOL_DETAIL_KEYS = [
  "query",
  "url",
  "pattern",
  "path",
  "command",
  "code",
  "q",
  "text",
] as const;

function toolDetail(args: Record<string, unknown>): string {
  for (const k of TOOL_DETAIL_KEYS) {
    const v = args[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  for (const v of Object.values(args)) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

function formatToolLine(step: Extract<ProcessStep, { kind: "tool" }>): string {
  const label = TOOL_LABEL[step.tool_name] ?? step.tool_name;
  const detail = toolDetail(step.arguments ?? {});
  const status =
    step.status === "error"
      ? "（失败）"
      : step.status === "running"
        ? "（进行中）"
        : "";
  return detail ? `· ${label}${status}：${detail}` : `· ${label}${status}`;
}

/** Format the turn's process timeline into plain readable text (旁白 + 关键工具). */
export function formatProcessExport(
  process: ProcessStep[] | undefined,
): string {
  if (!process?.length) return "";
  const lines: string[] = [];
  for (const step of process) {
    switch (step.kind) {
      case "reasoning": {
        const t = step.text.trim();
        if (t) lines.push(`【思考】\n${t}`);
        break;
      }
      case "content": {
        const t = step.text.trim();
        if (t) lines.push(t);
        break;
      }
      case "tool":
        lines.push(formatToolLine(step));
        break;
      case "rework":
        lines.push("· （引用/格式核验后已重写）");
        break;
      case "team":
        lines.push("· （团队协作）");
        break;
      case "checkpoint":
        lines.push("· （向你确认）");
        break;
      case "ask":
        lines.push("· （提问）");
        break;
      case "plan_review":
        lines.push("· （计划复核）");
        break;
      case "team_preview":
        lines.push("· （团队预览）");
        break;
      default:
        break;
    }
  }
  return lines.join("\n\n").trim();
}

/**
 * Build clipboard / share text for an assistant message.
 * - deliverable: `messages.content` only（默认）
 * - with_process: 过程时间线 + 交付正文（无 process 时退化为仅交付）
 */
export function formatMessageExport(
  content: string,
  process: ProcessStep[] | undefined,
  mode: MessageCopyMode,
): string {
  const deliverable = content.trim();
  if (mode === "deliverable") return deliverable;

  const processText = formatProcessExport(process);
  if (!processText) return deliverable;
  if (!deliverable) return `【过程】\n\n${processText}`;

  // Trailing content steps often already equal the deliverable; avoid duplicating
  // the final answer when the timeline already ends on it.
  const endsWithDeliverable =
    processText === deliverable || processText.endsWith(deliverable);
  if (endsWithDeliverable) {
    return `【过程】\n\n${processText}`;
  }
  return `【过程】\n\n${processText}\n\n【交付】\n\n${deliverable}`;
}
