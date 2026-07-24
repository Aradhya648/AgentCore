/**
 * Worker 节点「收到的上下文」——普通模式 = 结构化分段；诊断模式 = 同一区块原位展开为
 * LLM 消息骨架（系统提示 + 开场用分段替代 + 后续轮次）。双数据管线保留：
 * SSE ``run_context`` → blocks；REST llm-window → messages。
 */
import {
  ContextBlockCard,
  ReceivedContextSection,
} from "@/components/chat/ReceivedContext";
import { Button } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatCompact } from "@/lib/format";
import { usePersistentDisclosure } from "@/stores/disclosure";
import type { ContextBlockWire } from "@/types/events";
import type { LlmWindowMessage } from "@agentcore/contract-rest-types/llm-window";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

const ROLE_LABELS: Record<LlmWindowMessage["role"], string> = {
  system: "系统",
  user: "用户",
  assistant: "助手",
  tool: "工具",
};

export type WorkerContextDiagnostic = {
  messages: LlmWindowMessage[];
  available: boolean;
  loading: boolean;
  error: string | null;
};

export function WorkerContextSection({
  blocks,
  diagnosticMode,
  diagnostic,
  onNavigate,
  keyBase,
}: {
  blocks: ContextBlockWire[];
  diagnosticMode: boolean;
  diagnostic: WorkerContextDiagnostic;
  onNavigate?: (runId: string) => void;
  keyBase: string;
}) {
  // 普通模式：零回归，复用原 ReceivedContextSection。
  if (!diagnosticMode) {
    if (blocks.length === 0) return null;
    return (
      <ReceivedContextSection
        blocks={blocks}
        defaultExpanded={false}
        keyBase={keyBase}
        onNavigate={onNavigate}
      />
    );
  }

  const hasSkeleton = diagnostic.available && diagnostic.messages.length > 0;
  if (
    blocks.length === 0 &&
    !hasSkeleton &&
    !diagnostic.loading &&
    !diagnostic.error
  ) {
    return null;
  }

  return (
    <DiagnosticContextSkeleton
      blocks={blocks}
      diagnostic={diagnostic}
      onNavigate={onNavigate}
      keyBase={keyBase}
    />
  );
}

function DiagnosticContextSkeleton({
  blocks,
  diagnostic,
  onNavigate,
  keyBase,
}: {
  blocks: ContextBlockWire[];
  diagnostic: WorkerContextDiagnostic;
  onNavigate?: (runId: string) => void;
  keyBase: string;
}) {
  const [expanded, setExpanded] = usePersistentDisclosure(
    `${keyBase}:ctx`,
    false,
  );
  const [rawOpen, setRawOpen] = useState(false);

  const messages = diagnostic.messages;
  const systemMsg = messages.find((m) => m.role === "system");
  const openingIdx = messages.findIndex(
    (m) => m.role === "user" && m.origin === "context_blocks",
  );
  const openingMsg = openingIdx >= 0 ? messages[openingIdx] : null;
  // Drop system (shown above) and the origin-tagged opening user (replaced by blocks).
  const rest = messages.filter((m, i) => {
    if (m.role === "system") return false;
    if (openingIdx >= 0 && i === openingIdx) return false;
    return true;
  });

  const segmentCount = blocks.length;
  const roundCount = rest.length;
  const summaryBits: string[] = [];
  if (segmentCount > 0) summaryBits.push(`${segmentCount} 段`);
  if (systemMsg) summaryBits.push("含系统提示");
  if (roundCount > 0) summaryBits.push(`${roundCount} 轮`);

  return (
    <section className="mb-4 last:mb-0">
      <Button
        variant="ghost"
        onClick={() => setExpanded((v) => !v)}
        className="h-auto w-full justify-start gap-1.5 px-0 py-0 hover:bg-transparent"
      >
        <span className="flex w-full items-center gap-1.5">
          {expanded ? (
            <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={14}
              className="shrink-0 text-muted-foreground"
            />
          )}
          <span className="flex-1 text-left text-xs font-medium text-muted-foreground">
            收到的上下文
          </span>
          {diagnostic.loading ? (
            <span className="shrink-0 text-xs text-muted-foreground">
              加载中…
            </span>
          ) : (
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {summaryBits.join(" · ") || "诊断"}
            </span>
          )}
        </span>
      </Button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {diagnostic.error ? (
            <p className="text-xs text-destructive">{diagnostic.error}</p>
          ) : null}

          {systemMsg ? (
            <SystemPromptRow
              content={systemMsg.content ?? ""}
              keyBase={keyBase}
            />
          ) : null}

          {blocks.length > 0 ? (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  开场上下文（结构化分段）
                </span>
                {openingMsg?.content ? (
                  <Button
                    variant="ghost"
                    className="h-auto px-1.5 py-0.5 text-xs text-primary hover:bg-primary/10"
                    onClick={() => setRawOpen(true)}
                  >
                    查看原始拼接
                  </Button>
                ) : null}
              </div>
              {blocks.map((b, i) => (
                <ContextBlockCard
                  key={`${b.channel}-${i}`}
                  block={b}
                  defaultOpen={false}
                  onNavigate={onNavigate}
                  sceneKey={`${keyBase}:ctxblk:${b.channel}-${i}`}
                  presentation="incremental"
                />
              ))}
            </div>
          ) : openingMsg ? (
            <WindowMessageRow
              message={openingMsg}
              index={openingIdx}
              keyBase={keyBase}
              defaultExpanded={false}
            />
          ) : null}

          {diagnostic.loading && messages.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              正在从 journal 折叠 LLM 窗口…
            </p>
          ) : null}

          {!diagnostic.loading && !diagnostic.available && blocks.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              无法从 journal 重建后续轮次（可能缺少 execution facts）。
            </p>
          ) : null}

          {rest.map((message, i) => (
            <WindowMessageRow
              key={`${message.role}-${i}`}
              message={message}
              index={i + 10}
              keyBase={keyBase}
              defaultExpanded={false}
            />
          ))}
        </div>
      )}

      {openingMsg?.content ? (
        <Dialog open={rawOpen} onOpenChange={setRawOpen}>
          <DialogContent className="flex max-h-[80vh] max-w-2xl flex-col">
            <DialogHeader>
              <DialogTitle>原始拼接</DialogTitle>
              <DialogDescription>
                开场 user
                消息的全文（喂给模型的逐字拼接；结构化分段在事件侧可能截断）。
              </DialogDescription>
            </DialogHeader>
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3 text-xs leading-relaxed text-foreground">
              {openingMsg.content}
            </pre>
          </DialogContent>
        </Dialog>
      ) : null}
    </section>
  );
}

function SystemPromptRow({
  content,
  keyBase,
}: {
  content: string;
  keyBase: string;
}) {
  const [open, setOpen] = usePersistentDisclosure(`${keyBase}:sys`, false);
  const chars = content.length;
  return (
    <div className="rounded-lg border border-border/60 bg-background">
      <Button
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        className="h-auto w-full justify-start gap-1.5 rounded-lg px-2.5 py-2 hover:bg-muted/50"
      >
        <span className="flex w-full items-center gap-1.5">
          {open ? (
            <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={14}
              className="shrink-0 text-muted-foreground"
            />
          )}
          <span className="flex-1 text-left text-xs font-medium text-muted-foreground">
            系统提示词 · {formatCompact(chars)} 字
          </span>
        </span>
      </Button>
      {open ? (
        <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words border-t border-border/40 px-2.5 py-2 text-xs leading-relaxed text-foreground">
          {content || "（空）"}
        </pre>
      ) : null}
    </div>
  );
}

function WindowMessageRow({
  message,
  index,
  keyBase,
  defaultExpanded,
}: {
  message: LlmWindowMessage;
  index: number;
  keyBase: string;
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = usePersistentDisclosure(
    `${keyBase}:wmsg:${index}`,
    defaultExpanded,
  );
  const [argsOpen, setArgsOpen] = usePersistentDisclosure(
    `${keyBase}:wmsg:${index}:args`,
    false,
  );
  const [reasoningOpen, setReasoningOpen] = usePersistentDisclosure(
    `${keyBase}:wmsg:${index}:reason`,
    false,
  );

  const preview =
    message.content?.trim() ||
    message.reasoning_content?.trim() ||
    (message.tool_calls?.length
      ? `tool_calls × ${message.tool_calls.length}`
      : message.tool_call_id
        ? `tool:${message.tool_call_id}`
        : "（空）");
  const long = (preview?.length ?? 0) > 160;
  const hasToolCalls = (message.tool_calls?.length ?? 0) > 0;
  const hasReasoning = Boolean(message.reasoning_content?.trim());

  return (
    <div className="rounded-lg border border-border/60 bg-background">
      <Button
        variant="ghost"
        onClick={() => setExpanded((v) => !v)}
        className="h-auto w-full justify-start gap-1.5 rounded-lg px-2.5 py-2 hover:bg-muted/50"
      >
        <span className="flex w-full items-center gap-1.5">
          {long || hasToolCalls || hasReasoning ? (
            expanded ? (
              <ChevronDown
                size={14}
                className="shrink-0 text-muted-foreground"
              />
            ) : (
              <ChevronRight
                size={14}
                className="shrink-0 text-muted-foreground"
              />
            )
          ) : (
            <span className="w-3.5 shrink-0" />
          )}
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
            {ROLE_LABELS[message.role]}
          </span>
          {!expanded && long && (
            <span className="min-w-0 flex-1 truncate text-left text-xs text-muted-foreground">
              {preview}
            </span>
          )}
        </span>
      </Button>

      {(expanded || !long) && (
        <div className="space-y-2 border-t border-border/40 px-2.5 py-2 text-xs">
          {hasReasoning ? (
            <div>
              <Button
                variant="ghost"
                onClick={() => setReasoningOpen((v) => !v)}
                className="mb-1 h-auto px-0 py-0 text-xs text-muted-foreground hover:bg-transparent"
              >
                {reasoningOpen ? "收起 reasoning" : "展开 reasoning"}
              </Button>
              {reasoningOpen ? (
                <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded bg-muted p-2 leading-relaxed text-muted-foreground">
                  {message.reasoning_content}
                </pre>
              ) : null}
            </div>
          ) : null}
          {message.content ? (
            <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded bg-muted p-2 leading-relaxed text-foreground">
              {message.content}
            </pre>
          ) : null}
          {message.tool_calls?.map((tc) => (
            <div
              key={tc.id}
              className="rounded bg-muted p-2 font-mono text-xs text-muted-foreground"
            >
              <div>{tc.function.name}</div>
              <Button
                variant="ghost"
                onClick={() => setArgsOpen((v) => !v)}
                className="mt-1 h-auto px-0 py-0 text-xs text-muted-foreground hover:bg-transparent"
              >
                {argsOpen ? "收起参数" : "展开参数"}
              </Button>
              {argsOpen ? (
                <pre className="mt-1 whitespace-pre-wrap break-words">
                  {tc.function.arguments}
                </pre>
              ) : null}
            </div>
          ))}
          {message.tool_call_id && message.role === "tool" ? (
            <p className="font-mono text-muted-foreground">
              id: {message.tool_call_id}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
