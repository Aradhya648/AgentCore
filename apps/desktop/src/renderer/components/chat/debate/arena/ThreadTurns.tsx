import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui";
import {
  statusAccentText,
  statusPillInline,
} from "@/components/ui/tone-presets";
import type { Execution } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { CornerDownRight, MessagesSquare } from "lucide-react";
import { SideIdentity } from "../SideChip";
import type { DebateThreadTurnView } from "../model";

/**
 * 圆桌英雄区：按点名串行线程渲染（先回应已说的，再补自己的）。
 * crux 追问 turn 挂「crux」徽章。
 */
export function ThreadTurns({
  turns,
  execution,
  messageId,
  subtopic,
}: {
  turns: DebateThreadTurnView[];
  execution: Execution;
  messageId: string;
  /** 本轮子题（来自 focus 或场级 subtopics）。 */
  subtopic?: string;
}) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  if (turns.length === 0) return null;

  return (
    <div className="space-y-2 py-2">
      <h3 className="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-foreground">
        <MessagesSquare size={15} className="text-muted-foreground" />
        圆桌线程
        {subtopic && (
          <span className="text-xs font-normal text-muted-foreground">
            · {subtopic}
          </span>
        )}
      </h3>
      <ol className="space-y-3">
        {turns.map((t, i) => {
          const agent = t.run
            ? execution.agents.find((a) => a.id === t.run?.agentId)
            : undefined;
          const text = agent ? agent.outputChunks.join("") : "";
          const streaming = t.run?.status === "running";
          return (
            <li
              key={`${t.run?.id ?? t.speakerKey}-${i}`}
              className="border-l-[3px] pl-3"
              style={{ borderLeftColor: t.speakerColorVar }}
            >
              {t.replyToName && (
                <p className="mb-1 flex items-start gap-1 text-xs text-muted-foreground">
                  <CornerDownRight size={12} className="mt-0.5 shrink-0" />
                  <span>
                    回{" "}
                    <span className="font-medium text-foreground">
                      {t.replyToName}
                    </span>
                  </span>
                </p>
              )}
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                {t.run ? (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      const runId = t.run?.id;
                      if (!runId) return;
                      showRunDetail(messageId, runId, t.speakerName);
                    }}
                    className="h-auto justify-start gap-2 rounded-none px-0 py-0 hover:bg-transparent"
                  >
                    <SideIdentity
                      name={t.speakerName}
                      colorVar={t.speakerColorVar}
                    />
                  </Button>
                ) : (
                  <SideIdentity
                    name={t.speakerName}
                    colorVar={t.speakerColorVar}
                  />
                )}
                {t.beat === "crux" && (
                  <span className={statusPillInline.primary}>crux</span>
                )}
                {streaming && (
                  <span className={statusAccentText.primary}>正在输入…</span>
                )}
                {!t.ok && !streaming && (
                  <span className="text-destructive">发言失败</span>
                )}
              </div>
              <div className="mt-1 pb-2 text-sm text-foreground">
                {text ? (
                  streaming ? (
                    <p className="whitespace-pre-wrap break-words">
                      {text}
                      <span
                        className="ml-0.5 inline-block h-[1em] w-px animate-pulse bg-primary align-text-bottom"
                        aria-hidden
                      />
                    </p>
                  ) : (
                    <Markdown content={text} />
                  )
                ) : (
                  <p className="text-xs text-muted-foreground">等待发言…</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
