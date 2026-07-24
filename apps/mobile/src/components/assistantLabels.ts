// Shared chrome labels for assistant rendering (English tool names / 上下文通道名 + the arg-detail
// picker). Extracted so BOTH the inline timeline ({@link AssistantView}) and the per-worker
// run-detail panel ({@link TeamView} · RunDetail) read ONE source — the maps are the kind of
// chrome that silently drifts if copied. Pure data + string helpers, no JSX, so it stays a
// leaf both can import without an import cycle (AssistantView → TeamView → RunDetail → here).
//
// These mirror the desktop `TOOL_META` / `CONTEXT_CHANNEL_META` labels so the two ends read the
// same (各端全新建 per cross-platform-frontend; labels are chrome, NOT shared business logic).

import type { ToolPhase } from "@agentcore/contract-types";

/** Context channel → 中文 label (上下文传递可视化). Covers the CEO-side opening channels
 *  (系统提示 / 对话历史 / 原始请求 / 队员回传) and the worker-side / 续写 channels (任务 / 交付物 /
 *  前置结果 / 本轮焦点 …). An unknown channel falls back to its raw name. */
export const CONTEXT_CHANNEL_LABEL: Record<string, string> = {
  system: "系统提示",
  history: "对话历史",
  request: "原始请求",
  team_position: "团队位置",
  dependency: "前置结果",
  workspace: "工作区",
  task: "你的任务",
  deliverable: "交付物规格",
  team_brief: "团队共识",
  gate_notes: "把关要点",
  steer: "中途指示",
  team_result: "队员回传",
  round_focus: "本轮焦点",
  opponent: "对方论点",
  challenge: "被驳命门",
  interjection: "你的追问",
  continuation: "接续指令",
  cross_exam: "质询",
  witness_exam: "证人",
  closing: "结辩",
};

/** English tool labels — mirror desktop `TOOL_META` so both ends read the same
 *  (各端全新建 per cross-platform-frontend; labels are chrome, NOT shared business logic).
 *  An unknown tool falls back to its raw backend name. */
const TOOL_LABEL: Record<string, string> = {
  web_search: "Search web",
  read_url: "Read page",
  grep: "Grep code",
  code_execute: "Run code",
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
  ask_user: "Ask you",
  consult_skill: "Consult skill",
  consult_memory: "Consult memory",
  revise: "Revise",
  escalate: "Escalate",
};

export const toolLabel = (name: string): string => TOOL_LABEL[name] ?? name;

/** Tool execution phase → waiting-state chrome (network UX). Mirrors desktop `toolPhaseText`. */
const TOOL_PHASE_TEXT: Record<ToolPhase, string> = {
  queued: "Queued",
  querying: "Searching",
  fallback: "Trying fallback",
  fetching: "Fetching page",
  reading: "Extracting",
  executing: "Running",
  blocked: "Network blocked",
};

export function toolPhaseText(phase: string | undefined): string | null {
  if (!phase) return null;
  return TOOL_PHASE_TEXT[phase as ToolPhase] ?? "Working";
}

/** The most descriptive string arg to show beside a tool (its query / url / path / …);
 *  empty when the call carries no representative string arg. */
const TOOL_DETAIL_KEYS = [
  "query",
  "url",
  "pattern",
  "path",
  "command",
  "code",
  "q",
  "text",
];

export function toolDetail(args: Record<string, unknown>): string {
  for (const k of TOOL_DETAIL_KEYS) {
    const v = args[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  for (const v of Object.values(args)) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}
