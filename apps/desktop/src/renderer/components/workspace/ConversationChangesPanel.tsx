import { TurnFileChangesReview } from "@/components/chat/TurnFileChangesReview";
import { EmptyHint } from "@/components/files/parts";
import {
  type FileArtifact,
  fileArtifactsFromExecution,
  fileArtifactsFromProcess,
  mergeArtifacts,
} from "@/lib/fileArtifacts";
import { useConversationStore } from "@/stores/conversation";
import {
  assistantProjectionId,
  runtimeOf,
} from "@/stores/conversation/runtime";
import { projectRuntime, useExecutionStore } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { Diff } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

/**
 * 右坞固定「改动」tab —— 本对话 AI 文件改动聚合（前端UX设计.md §十）。
 * 按回合列出，复用 {@link TurnFileChangesReview}（只读真 diff + 回滚）。
 * 产物卡「查看改动」经 {@link useSidePanelStore.showChanges} 聚焦同源入口。
 */

interface TurnChanges {
  messageId: string;
  label: string;
  artifacts: FileArtifact[];
}

export function ConversationChangesPanel() {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const messages = useConversationStore(
    (s) => runtimeOf(s, conversationId).messages,
  );
  const byId = useExecutionStore((s) => s.byId);
  const focusMessageId = useSidePanelStore((s) => s.changesFocusMessageId);

  const turns = useMemo((): TurnChanges[] => {
    const out: TurnChanges[] = [];
    let turnIndex = 0;
    for (const msg of messages) {
      if (msg.role !== "assistant") continue;
      turnIndex += 1;
      const messageId = assistantProjectionId(msg);
      const rt = byId[messageId];
      const execution = rt ? projectRuntime(rt) : null;
      const artifacts = mergeArtifacts(
        fileArtifactsFromProcess(msg.process),
        fileArtifactsFromExecution(execution),
      );
      const focused = focusMessageId != null && messageId === focusMessageId;
      if (artifacts.length === 0 && !focused) continue;
      out.push({
        messageId,
        label: `回合 ${turnIndex}`,
        artifacts,
      });
    }
    // 聚焦回合尚未出现在 messages（极端时序）时仍给一个入口。
    if (
      focusMessageId &&
      !out.some((t) => t.messageId === focusMessageId)
    ) {
      out.push({
        messageId: focusMessageId,
        label: "本回合",
        artifacts: [],
      });
    }
    return out;
  }, [messages, byId, focusMessageId]);

  const focusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!focusMessageId) return;
    focusRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusMessageId, turns]);

  if (!conversationId) {
    return (
      <EmptyHint
        inline
        icon={<Diff size={26} className="text-muted-foreground/40" />}
        title="暂无改动"
        hint="发送消息后，本对话 AI 写入工作区的文件改动会出现在这里。"
      />
    );
  }

  if (turns.length === 0) {
    return (
      <EmptyHint
        inline
        icon={<Diff size={26} className="text-muted-foreground/40" />}
        title="暂无改动"
        hint="本对话尚无 AI 文件改动。产物卡「查看改动」与此处同源。"
      />
    );
  }

  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="space-y-4">
        {turns.map((t) => {
          const focused = t.messageId === focusMessageId;
          return (
            <section
              key={t.messageId}
              ref={focused ? focusRef : undefined}
              className={`rounded-xl border border-border bg-card ${
                focused ? "ring-1 ring-primary/40" : ""
              }`}
            >
              <header className="border-b border-border px-3 py-2">
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t.label}
                  {t.artifacts.length > 0 && (
                    <span className="ml-2 tabular-nums text-muted-foreground/80">
                      {t.artifacts.length} 个文件
                    </span>
                  )}
                </h3>
              </header>
              <TurnFileChangesReview
                artifacts={t.artifacts}
                conversationId={conversationId}
                messageId={t.messageId}
                variant="panel"
              />
            </section>
          );
        })}
      </div>
    </div>
  );
}
