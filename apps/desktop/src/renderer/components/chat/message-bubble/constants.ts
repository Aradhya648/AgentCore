import type { ProcessStep, ToolPhase } from "@/types/events";
import {
  ArrowUp,
  Bell,
  BookOpen,
  Brain,
  Camera,
  Code2,
  Compass,
  FileText,
  Folder,
  Forward,
  Gavel,
  GitBranch,
  Globe,
  HelpCircle,
  Inbox,
  Keyboard,
  ListRestart,
  type LucideIcon,
  MessagesSquare,
  MousePointerClick,
  MoveVertical,
  NotebookPen,
  PenLine,
  Pencil,
  Presentation,
  Scale,
  ScanText,
  Search,
  StickyNote,
  Terminal,
  TestTube2,
  Trash2,
  UserX,
  Users,
  Wrench,
} from "lucide-react";

/** Icon + English action label for a builtin tool, by its backend name. */
export const TOOL_META: Record<string, { Icon: LucideIcon; label: string }> = {
  web_search: { Icon: Search, label: "Search web" },
  read_url: { Icon: Globe, label: "Read page" },
  grep: { Icon: Code2, label: "Grep code" },
  code_search: { Icon: Code2, label: "Search code" },
  code_execute: { Icon: Terminal, label: "Run code" },
  terminal: { Icon: Terminal, label: "Run terminal" },
  test_run: { Icon: TestTube2, label: "Run tests" },
  git: { Icon: GitBranch, label: "Git" },
  file_read: { Icon: FileText, label: "Read file" },
  file_write: { Icon: FileText, label: "Write file" },
  file_append: { Icon: FileText, label: "Append file" },
  file_list: { Icon: Folder, label: "List dir" },
  str_replace: { Icon: Pencil, label: "Edit file" },
  file_delete: { Icon: Trash2, label: "Delete file" },
  file_move: { Icon: FileText, label: "Move file" },
  file_copy: { Icon: FileText, label: "Copy file" },
  mkdir: { Icon: FileText, label: "Make dir" },
  file_batch: { Icon: FileText, label: "Batch files" },
  delegate: { Icon: Users, label: "Delegate" },
  replan: { Icon: ListRestart, label: "Replan" },
  // CEO 编排原语（组队辩论）：气泡侧只在「Composing …」参数组装心跳时露出，
  // 图标与开工卡的 debate 形态一致（Scale）。
  debate: { Icon: Scale, label: "Debate" },
  ask_user: { Icon: HelpCircle, label: "Ask you" },
  consult_skill: { Icon: BookOpen, label: "Consult skill" },
  consult_memory: { Icon: Brain, label: "Consult memory" },
  // Worker-only 跨会话对话日志（CEO 经 delegate 派查阅员）。
  search_conversations: { Icon: MessagesSquare, label: "Search conversations" },
  read_conversation: { Icon: MessagesSquare, label: "Read conversation" },
  revise: { Icon: PenLine, label: "Revise" },
  escalate: { Icon: ArrowUp, label: "Escalate" },
  // CEO 协调模式原语（波内边跑边调）：与 file/web 工具同走 ToolLine。
  update_synthesis: { Icon: NotebookPen, label: "Update synthesis" },
  cancel_worker: { Icon: UserX, label: "Cancel worker" },
  resolve_escalation: { Icon: Gavel, label: "Resolve escalate" },
  queue_user_message: { Icon: Inbox, label: "Queue message" },
  // L3 团队浏览器（worker-only）：连续步聚合成「浏览器活动卡」（BrowserActivityCard），
  // 单步走通用 ToolLine + ToolResultView 的 browser 分支。
  browser_navigate: { Icon: Compass, label: "Navigate" },
  browser_click: { Icon: MousePointerClick, label: "Click" },
  browser_type: { Icon: Keyboard, label: "Type" },
  browser_scroll: { Icon: MoveVertical, label: "Scroll" },
  browser_snapshot: { Icon: ScanText, label: "Snapshot" },
  browser_screenshot: { Icon: Camera, label: "Screenshot" },
  // Worker / board channels that also render on the process timeline.
  post_note: { Icon: StickyNote, label: "Post note" },
  read_notes: { Icon: StickyNote, label: "Read notes" },
  amend_note: { Icon: StickyNote, label: "Amend note" },
  handoff: { Icon: Forward, label: "Handoff" },
  board_ops: { Icon: Presentation, label: "Edit board" },
  board_read: { Icon: Presentation, label: "Read board" },
  desktop_notify: { Icon: Bell, label: "Notify" },
};

/** Tool-group collapse summaries reuse {@link TOOL_META} English labels (same chrome as ToolLine). */
const toolSummaryLabel = (name: string): string =>
  TOOL_META[name]?.label ?? name;

export const toolMeta = (name: string): { Icon: LucideIcon; label: string } =>
  TOOL_META[name] ?? { Icon: Wrench, label: name };

/** Tool execution phase → waiting-state chrome (network UX): a running tool's coarse phase
 * (from a `tool_use_progress` event) as user-facing text — a slow builtin fires these while its
 * blocking leg is in flight so the waiting row is live instead of a dead spinner. web_search:
 * Searching / Queued / Trying fallback; read_url: Fetching page / Extracting; code_execute: Running. */
const TOOL_PHASE_TEXT: Record<ToolPhase, string> = {
  queued: "Queued",
  querying: "Searching",
  fallback: "Trying fallback",
  fetching: "Fetching page",
  reading: "Extracting",
  executing: "Running",
  blocked: "Network blocked",
};

/** Waiting-state text for a running tool step's `phase`, or null when it has none yet.
 * An unrecognized (newer-backend) phase degrades to a generic "Working" rather than vanishing. */
export function toolPhaseText(phase: string | undefined): string | null {
  if (!phase) return null;
  return TOOL_PHASE_TEXT[phase as ToolPhase] ?? "Working";
}

/** Locator / identity args — safe to chip into the collapsed ToolLine title. */
const TOOL_DETAIL_KEYS = [
  "query",
  "url",
  "pattern",
  "path",
  "command",
  "q",
  "name", // consult_skill / consult_memory
  "conversation_id", // read_conversation
  "run_id", // cancel_worker / resolve_escalation
  "interjection_id", // queue_user_message
];

/** Short one-liner body args (e.g. a tiny `code` snippet). Long / multiline prose
 * (`draft` / `answer` / `text` / …) stays out of the title — expand + peek cover it. */
const TOOL_DETAIL_SHORT_BODY_KEYS = ["code", "text"];

/** Collapsed title chip budget — keep the row one line (CSS truncate is the backstop). */
const TOOL_DETAIL_MAX_CHARS = 72;

function asTitleDetail(raw: string): string {
  const line = raw
    .split(/\r?\n/)
    .find((l) => l.trim())
    ?.trim();
  if (!line) return "";
  return line.length > TOOL_DETAIL_MAX_CHARS
    ? `${line.slice(0, TOOL_DETAIL_MAX_CHARS)}…`
    : line;
}

export function toolDetail(args: Record<string, unknown>): string {
  for (const k of TOOL_DETAIL_KEYS) {
    const v = args[k];
    if (typeof v === "string" && v.trim()) return asTitleDetail(v);
  }
  for (const k of TOOL_DETAIL_SHORT_BODY_KEYS) {
    const v = args[k];
    if (typeof v !== "string") continue;
    const trimmed = v.trim();
    if (
      !trimmed ||
      trimmed.includes("\n") ||
      trimmed.length > TOOL_DETAIL_MAX_CHARS
    ) {
      continue;
    }
    return trimmed;
  }
  // No Object.values fallback: that leaked update_synthesis `draft` (and would leak
  // other coordination prose bodies) into the title with break-all wrapping.
  return "";
}

export function baseName(detail: string): string {
  if (!detail) return "";
  const segs = detail.split(/[/\\]/);
  return segs[segs.length - 1] || detail;
}

export function toolGroupSummary(
  tools: Extract<ProcessStep, { kind: "tool" }>[],
): string {
  const sameKind = tools.every((t) => t.tool_name === tools[0].tool_name);
  // read_url args are bare URLs — baseName yields opaque article ids. Prefer a
  // count title (matches the merged source-collection header).
  if (sameKind && tools[0]?.tool_name === "read_url") {
    const n = tools.length;
    return `Read page · ${n} source${n === 1 ? "" : "s"}`;
  }
  if (sameKind && tools.length <= 3) {
    const label = toolSummaryLabel(tools[0].tool_name);
    const names = tools.map((t) => baseName(toolDetail(t.arguments)));
    if (names.every(Boolean)) return `${label} ${names.join(" · ")}`;
  }
  const order: string[] = [];
  const counts = new Map<string, number>();
  for (const t of tools) {
    const label = toolSummaryLabel(t.tool_name);
    if (!counts.has(label)) order.push(label);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return order.map((l) => `${l} ${counts.get(l)}`).join(" · ");
}
