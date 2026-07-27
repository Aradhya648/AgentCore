import {
  type ToolResultData,
  ToolResultView,
  hasToolResultBody,
  toolResultPeek,
} from "@/components/chat/toolResult/ToolResultView";
import { Badge, Button } from "@/components/ui";
import { isBrowserTool } from "@/lib/browserActivity";
import { formatCompact } from "@/lib/format";
import { runtimeOf, useConversationStore } from "@/stores/conversation";
import {
  usePersistentDisclosure,
  useStreamAwareDisclosure,
} from "@/stores/disclosure";
import { useSidePanelStore } from "@/stores/sidePanel";
import type { ProcessStep } from "@/types/events";
import { Check, ChevronDown, ChevronRight, Radio, X } from "lucide-react";
import { useEffect, useState } from "react";
import {
  BrowserActivityCard,
  isBrowserActivityGroup,
} from "./BrowserActivityCard";
import {
  ReadUrlSourceCollection,
  isReadUrlSourceGroup,
} from "./ReadUrlSourceCollection";
import { ThinkingDots } from "./message-bubble/Thinking";
import {
  toolDetail,
  toolGroupSummary,
  toolMeta,
  toolPhaseText,
} from "./message-bubble/constants";

/** Tools whose collapsed title already names the target (path / topic / skill / action)
 * and whose peek would only repeat an ack line or leak result body. Skip the peek —
 * collapsed rows stay a clean single line (mirrors how web_search folds its count into
 * the title instead of a peek). */
const PEEK_SUPPRESSED = new Set([
  "consult_skill",
  "consult_memory",
  // 跨会话对话日志：标题已自解释（query / conversation_id），正文在展开卡。
  "search_conversations",
  "read_conversation",
  "file_read",
  "file_list",
  // CEO 协调原语：标题已自解释（+ run_id / interjection_id chip），peek 只是操作确认文案。
  "update_synthesis",
  "replan",
  "cancel_worker",
  "resolve_escalation",
  "queue_user_message",
]);

/** Live transport line while the model streams tool-call JSON (不持久化). */
export function ComposingToolLine({
  tool,
}: {
  tool: { toolName: string; chars: number };
}) {
  const { Icon, label } = toolMeta(tool.toolName);
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
      <Icon size={14} className="shrink-0 text-primary" />
      <span>
        Composing {label}
        {tool.chars > 0 && (
          <span className="text-muted-foreground/70">
            {" · "}
            {formatCompact(tool.chars)} chars
          </span>
        )}
      </span>
      <span className="inline-block animate-pulse text-primary">▋</span>
    </span>
  );
}

/** Live elapsed seconds since a tool's REAL start (`startedAt`, epoch ms stamped by
 * `addProcessTool` at `tool_use_start` — see {@link ConversationRuntime.toolStartedMs}),
 * NOT since component mount. A liveliness cue for a BLOCKING tool (web_search) whose
 * execution streams no incremental progress. Deriving from `startedAt` keeps the counter
 * stable across row remount (过程折叠/展开 · 聊天列表虚拟化), which the old mount-time anchor
 * reset to 0. The 1s ticker only forces a re-render; the value is recomputed from the wall
 * clock each render (clamped ≥0). Returns 0 when not running or the start is unknown (e.g. a
 * reloaded turn — where the tool is already done anyway, so no live timer is wanted). */
function useRunningElapsed(
  running: boolean,
  startedAt: number | null | undefined,
): number {
  const [, force] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  if (!running || startedAt == null) return 0;
  return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
}

/** Shimmer placeholder rows shown while web_search is running — turns the bare waiting
 * spinner into a「结果正在来」affordance. The search is atomic (nothing to stream), so
 * this only previews the result cards' shape until the real hits land. */
function WebSearchSkeleton() {
  return (
    <div className="mt-1 space-y-1.5" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-start gap-2 px-2 py-1">
          <div className="mt-0.5 size-4 shrink-0 animate-pulse rounded bg-muted" />
          <div className="min-w-0 flex-1 space-y-1">
            <div className="h-3 w-1/2 animate-pulse rounded bg-muted" />
            <div className="h-3 w-4/5 animate-pulse rounded bg-muted/70" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** 行尾指示（顶层工具行对齐「Read page · N sources」）：进行中脉冲点；否则失败打红✗，
 *  顶层可展开行补一个折叠 chevron（open→ChevronUp / 收起→ChevronDown）明确可开合；
 *  组内明细子行仍用成功绿✓。顶层成功即只留 chevron，成功由「无红✗」隐含（与 read_url 组一致）。 */
function ToolRowTail({
  status,
  nested,
  hasBody,
  open,
}: {
  status: "running" | "success" | "error";
  nested: boolean;
  hasBody: boolean;
  open: boolean;
}) {
  if (status === "running")
    return (
      <span className="ml-1.5 inline-block size-1.5 animate-pulse rounded-full bg-primary align-middle" />
    );
  // The verdict icon mounts fresh on the running→done edge, so a one-shot pop marks the
  // state change (设计 §3); reduced-motion skips it. 行尾指示紧跟标题文字（自适应内容右侧、
  // 不撑到行边缘）：失败红✗；顶层可展开补折叠 chevron；组内明细子行用成功绿✓。
  return (
    <span className="ml-1 inline-flex items-center gap-1 align-middle">
      {status === "error" && (
        <X
          size={14}
          className="animate-status-pop text-destructive motion-reduce:animate-none"
        />
      )}
      {nested && status === "success" && (
        <Check
          size={14}
          className="animate-status-pop text-success motion-reduce:animate-none"
        />
      )}
      {!nested &&
        hasBody &&
        (open ? (
          <ChevronDown size={14} className="text-muted-foreground" />
        ) : (
          <ChevronRight size={14} className="text-muted-foreground" />
        ))}
    </span>
  );
}

/** Single tool invocation row in the process timeline. */
export function ToolLine({
  step,
  turnKey,
  nested = false,
  conversationId = null,
}: {
  step: Extract<ProcessStep, { kind: "tool" }>;
  /** 回合作用域标识（= messageId）：给了才把「结果卡开合」持久化（切对话/刷新后仍在），
   *  按 `${turnKey}:tool:${step.id}` 落 localStorage；缺省（如渲染测试）退化为会话内存态。 */
  turnKey?: string;
  /** 是否为「工具组展开后的缩进明细子行」。顶层孤立工具行（默认 false）走 header 规格
   *  （text-sm·灰·不加粗·成功无✓），与思考过程/工具组/过程摘要同级；组内子行（true）保留
   *  明细规格（text-sm·深色·加粗·成功绿✓），靠 pl-3 缩进与父摘要行区分层级。 */
  nested?: boolean;
  /** 所属对话（= conversationId）：仅 browser 结果用它懒加载关键帧；其余工具忽略。 */
  conversationId?: string | null;
}) {
  const [open, setOpen] = usePersistentDisclosure(
    turnKey ? `${turnKey}:tool:${step.id}` : null,
    false,
  );
  const { Icon, label } = toolMeta(step.tool_name);
  const detail = toolDetail(step.arguments);
  const data: ToolResultData = {
    toolName: step.tool_name,
    args: step.arguments,
    result: step.result,
    display: step.display,
    status: step.status,
    conversationId,
  };
  const hasBody = hasToolResultBody(data);
  const running = step.status === "running";
  const isWebSearch = step.tool_name === "web_search";
  const suppressesPeek = PEEK_SUPPRESSED.has(step.tool_name);
  // Real backend-ish start anchor (stamped at tool_use_start) keyed by tool_call_id (= step.id),
  // so the running timer survives this row remounting. Undefined on a reloaded turn (tool done).
  const startedAt = useConversationStore(
    (s) => runtimeOf(s, conversationId).toolStartedMs[step.id],
  );
  const elapsed = useRunningElapsed(running, startedAt);

  // Waiting-state hint (network search UX): coarse phase (Searching / Queued / Trying fallback)
  // plus a live elapsed timer, replacing the dead spinner. Empty at the very first instant
  // (no phase yet, <1s) — the pulsing dot + skeleton still convey life.
  const runningHint = running
    ? [toolPhaseText(step.phase), elapsed >= 1 ? `${elapsed}s` : null]
        .filter(Boolean)
        .join(" · ")
    : "";
  // web_search 的「N results」是元计数（类比 read_url 组的「N sources」）：成功时并入标题行、
  // 不再另起一行 peek——顶层折叠态与「Read page · N sources」同构（单行 + 行尾 chevron）。
  const inlineCount =
    !nested &&
    step.tool_name === "web_search" &&
    step.status === "success" &&
    hasBody
      ? toolResultPeek(data)
      : null;
  return (
    <div className="min-w-0">
      <Button
        variant="ghost"
        onClick={() => hasBody && setOpen((v) => !v)}
        className={`h-auto w-full justify-start gap-2 px-0 py-0 hover:bg-transparent ${
          hasBody ? "cursor-pointer" : "cursor-default"
        }`}
      >
        <span className="flex w-full items-start gap-2 text-left">
          <Icon size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            <span
              className={`flex min-w-0 items-center ${
                nested
                  ? "text-sm text-foreground"
                  : "text-sm text-muted-foreground"
              }`}
            >
              <span className="min-w-0 truncate">
                <span className={nested ? "font-medium" : undefined}>
                  {label}
                </span>
                {detail && (
                  <span className="ml-1.5 text-muted-foreground">{detail}</span>
                )}
                {inlineCount && (
                  <span className="ml-1.5 text-muted-foreground/70">
                    · {inlineCount}
                  </span>
                )}
              </span>
              <ToolRowTail
                status={step.status}
                nested={nested}
                hasBody={hasBody}
                open={open}
              />
            </span>
            {runningHint && (
              <span className="block truncate text-xs text-muted-foreground/70">
                {runningHint}
              </span>
            )}
            {hasBody && !open && !inlineCount && !suppressesPeek && (
              <span
                className={`block truncate text-xs ${
                  step.status === "error"
                    ? "text-destructive/80"
                    : "text-muted-foreground/70"
                }`}
              >
                {toolResultPeek(data)}
              </span>
            )}
          </span>
        </span>
      </Button>
      {running && isWebSearch && <WebSearchSkeleton />}
      {open && hasBody && <ToolResultView data={data} />}
    </div>
  );
}

/** ≥2 consecutive `web_search` — flatten to top-level ToolLines (no outer group
 * shell). Each search already carries query + result count on its own row; wrapping
 * them in「Search web A · B」only adds a redundant disclosure layer (unlike
 * read_url, which merges into one source collection). */
function isWebSearchFlatGroup(
  tools: Extract<ProcessStep, { kind: "tool" }>[],
): boolean {
  return tools.length >= 2 && tools.every((t) => t.tool_name === "web_search");
}

/** Collapsible group of consecutive tool lines (ProcessToolGroup pattern). */
export function ToolLineGroup({
  tools,
  isStreaming,
  turnKey,
  groupKey,
  conversationId = null,
}: {
  tools: Extract<ProcessStep, { kind: "tool" }>[];
  isStreaming: boolean;
  /** 回合作用域标识（= messageId）：给了才把「工具组开合」持久化；缺省退化为会话内存态。 */
  turnKey?: string;
  /** 该工具组的稳定标识（timelineNodeKeys，首个 tool 的 id）——组成持久化键；
   *  标记中段插入（insertBeforeTeam）不再位移它。 */
  groupKey?: string;
  /** 所属对话（= conversationId）：透传给 browser 活动卡懒加载关键帧；其余分派忽略。 */
  conversationId?: string | null;
}) {
  // All-read_url groups (≥2) render as a self-folding source collection — no
  // ToolLineGroup chevron on top (would be double disclosure). Persistence key
  // stays `${turnKey}:tgrp:${groupKey}` inside ReadUrlSourceCollection.
  if (isReadUrlSourceGroup(tools)) {
    return (
      <ReadUrlSourceCollection
        tools={tools}
        isStreaming={isStreaming}
        turnKey={turnKey}
        groupKey={groupKey}
      />
    );
  }
  // All-browser_* runs (≥2) fold into one「团队浏览器」活动卡 (steps + key-frames),
  // same single-disclosure chrome as the read_url collection.
  if (isBrowserActivityGroup(tools)) {
    return (
      <BrowserActivityCard
        tools={tools}
        isStreaming={isStreaming}
        turnKey={turnKey}
        groupKey={groupKey}
        conversationId={conversationId}
      />
    );
  }
  // Pure web_search runs: skip the outer group shell — each call is already a
  // self-explanatory top-level row (query + inline result count).
  if (isWebSearchFlatGroup(tools)) {
    return (
      <div className="space-y-2">
        {tools.map((t) => (
          <ToolLine key={t.id} step={t} turnKey={turnKey} />
        ))}
      </div>
    );
  }
  return (
    <DefaultToolLineGroup
      tools={tools}
      isStreaming={isStreaming}
      turnKey={turnKey}
      groupKey={groupKey}
      conversationId={conversationId}
    />
  );
}

function DefaultToolLineGroup({
  tools,
  isStreaming,
  turnKey,
  groupKey,
  conversationId = null,
}: {
  tools: Extract<ProcessStep, { kind: "tool" }>[];
  isStreaming: boolean;
  turnKey?: string;
  groupKey?: string;
  conversationId?: string | null;
}) {
  // 「直播中自动展开盯着看、收场后按保存值」（Q3）：取代旧的「流式默认展开 + 收场强制收起」，
  // 收场后不再强收，而是回到用户持久化的选择。
  const [expanded, toggleExpanded] = useStreamAwareDisclosure(
    turnKey != null && groupKey != null ? `${turnKey}:tgrp:${groupKey}` : null,
    isStreaming,
  );
  const showBrowser = useSidePanelStore((s) => s.showBrowser);

  const summary = toolGroupSummary(tools);
  const errorCount = tools.reduce(
    (n, t) => n + (t.status === "error" ? 1 : 0),
    0,
  );
  const running = tools.some((t) => t.status === "running");
  // 混杂组（含 browser_* + 他工具）走默认壳，无活动卡 CTA——组头挂同款「打开浏览器」/
  // 「查看直播」，勿在子 ToolLine 再刷。纯 browser ≥2 已由 BrowserActivityCard 接管。
  const showBrowserCta =
    conversationId != null && tools.some((t) => isBrowserTool(t.tool_name));

  return (
    <div>
      <div className="flex items-center gap-1.5">
        <Button
          variant="ghost"
          onClick={toggleExpanded}
          className="h-auto min-w-0 flex-1 justify-start gap-2 px-0 py-0 text-sm text-muted-foreground hover:bg-transparent hover:text-foreground"
        >
          <span className="flex items-center gap-2">
            {running && <ThinkingDots />}
            <span className="min-w-0 truncate text-left">{summary}</span>
            {errorCount > 0 && (
              <Badge tone="destructive" className="shrink-0 font-normal">
                {errorCount} failed
              </Badge>
            )}
            {!running &&
              (expanded ? (
                <ChevronDown size={14} className="shrink-0" />
              ) : (
                <ChevronRight size={14} className="shrink-0" />
              ))}
          </span>
        </Button>
        {showBrowserCta && (
          <button
            type="button"
            onClick={showBrowser}
            className="flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/15"
          >
            <Radio size={12} className="shrink-0" />
            {running ? "查看直播" : "打开浏览器"}
          </button>
        )}
      </div>
      {expanded && (
        <div className="mt-1.5 space-y-2 pl-3">
          {tools.map((t) => (
            <ToolLine
              key={t.id}
              step={t}
              turnKey={turnKey}
              nested
              conversationId={conversationId}
            />
          ))}
        </div>
      )}
    </div>
  );
}
