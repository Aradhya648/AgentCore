import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui";
import { statusAccentText } from "@/components/ui/tone-presets";
import { usePersistentDisclosure } from "@/stores/disclosure";
import type { Execution } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { ChevronDown, ChevronRight, CornerDownRight } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { CollapsibleSpeech } from "../CollapsibleSpeech";
import type {
  DebateClashView,
  DebateRoundModel,
  DebateSideModel,
} from "../model";
import { speakerAnchorId } from "./anchors";
import {
  type SpeechArgument,
  parseSpeechArguments,
  rehydrateArgumentTitles,
} from "./parseSpeechArguments";
import { speechPlaceholder } from "./speechPlaceholder";
import { speechStageLabel } from "./stageLabel";

export function SpeakerBlock({
  side,
  round,
  execution,
  messageId,
  stage,
  highlight,
  onHighlightEnd,
  clashes,
  onClashClick,
}: {
  side: DebateSideModel;
  round: DebateRoundModel;
  execution: Execution;
  messageId: string;
  stage: string;
  highlight?: boolean;
  onHighlightEnd?: () => void;
  clashes?: DebateClashView[];
  onClashClick?: (clash: DebateClashView) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  const run = side.run;
  const agent = run
    ? execution.agents.find((a) => a.id === run.agentId)
    : undefined;
  const output = agent ? agent.outputChunks.join("") : "";
  const streaming = run?.status === "running";

  useEffect(() => {
    if (!highlight || !ref.current) return;
    ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = window.setTimeout(() => onHighlightEnd?.(), 2000);
    return () => window.clearTimeout(t);
  }, [highlight, onHighlightEnd]);

  const status = streaming ? (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium ${statusAccentText.primary}`}
    >
      <span className="size-1.5 animate-pulse rounded-full bg-current" />
      正在输入…
    </span>
  ) : run?.status === "failed" ? (
    <span className="text-xs text-destructive">发言失败</span>
  ) : null;

  const sceneKey = `${messageId}:arena:r${round.roundNo}:${side.sideKey || side.key}`;
  // 头行 toggle 与展开态底部「收起全文」共享同一实例——无对话 id 时 usePersistentDisclosure
  // 退化为组件本地 useState，若父子各自调同键会脱同步（测试环境即此形态）。
  const [showAll, setShowAll] = usePersistentDisclosure(
    `${sceneKey}:all`,
    false,
  );
  // 新契约：后端 ``sides[].arguments`` 权威；缺省 / 空 → 旧 journal 启发式回退。
  // 有成稿 output 时按解析结果重水合 title（修复旧截断磁带），id/body 仍用结构化载荷。
  const structured = side.arguments;
  const arguments_: SpeechArgument[] =
    !streaming && structured && structured.length > 0
      ? rehydrateArgumentTitles(
          structured.map((a) => ({ id: a.id, title: a.title, body: a.body })),
          output,
        )
      : !streaming && output
        ? parseSpeechArguments(output)
        : [];
  const showFullTextToggle = !streaming && !!output && arguments_.length > 0;

  const meta = (
    <SpeakerMeta
      name={side.name}
      colorVar={side.colorVar}
      stage={stage}
      status={status}
    />
  );

  return (
    <div
      ref={ref}
      id={speakerAnchorId(round.roundNo, side.sideKey || side.key)}
      className={`scroll-mt-28 border-l-[3px] pl-3 transition-colors ${
        highlight ? "bg-accent/30" : ""
      }`}
      style={{ borderLeftColor: side.colorVar }}
    >
      {clashes?.map((c, i) => (
        <button
          key={`${c.toKey}-${i}`}
          type="button"
          onClick={() => onClashClick?.(c)}
          className="mb-2 flex w-full items-start gap-1 rounded-lg bg-muted/40 px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/70"
        >
          <CornerDownRight size={12} className="mt-0.5 shrink-0" />
          <span>
            <span className="font-medium text-foreground">回 {c.toName}</span>：
            {c.point}
          </span>
        </button>
      ))}
      <div className="flex items-center gap-2 text-xs">
        {run ? (
          <Button
            variant="ghost"
            onClick={() => showRunDetail(messageId, run.id, side.name)}
            className="h-auto justify-start gap-2 rounded-none px-0 py-0 hover:bg-transparent"
          >
            {meta}
          </Button>
        ) : (
          meta
        )}
        {showFullTextToggle && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            className="ml-auto shrink-0 text-xs font-medium text-primary hover:underline"
          >
            {showAll ? "收起全文" : "展开全文"}
          </button>
        )}
      </div>
      <div className="mt-1 pb-4 text-sm text-foreground">
        {streaming ? (
          <div className="whitespace-pre-wrap break-words">
            {output}
            <span
              className="ml-0.5 inline-block h-[1em] w-px animate-pulse bg-primary align-text-bottom"
              aria-hidden
            />
          </div>
        ) : output ? (
          <ArgumentSpeech
            output={output}
            sceneKey={sceneKey}
            arguments_={arguments_}
            showAll={showAll}
            setShowAll={setShowAll}
          />
        ) : (
          <p className="text-xs text-muted-foreground">
            {speechPlaceholder(run)}
          </p>
        )}
      </div>
    </div>
  );
}

function ArgumentSpeech({
  output,
  sceneKey,
  arguments_,
  showAll,
  setShowAll,
}: {
  output: string;
  sceneKey: string;
  arguments_: SpeechArgument[];
  showAll: boolean;
  setShowAll: (value: boolean | ((prev: boolean) => boolean)) => void;
}) {
  if (showAll) {
    // 用户显式「展开全文」= 要看完整内容，不再套 CollapsibleSpeech（避免双层折叠）。
    return (
      <div>
        <Markdown content={output} evidence />
        <button
          type="button"
          onClick={() => setShowAll(false)}
          className="mt-1 text-xs font-medium text-primary hover:underline"
        >
          收起全文
        </button>
      </div>
    );
  }

  if (arguments_.length === 0) {
    return (
      <CollapsibleSpeech contentKey={output} sceneKey={sceneKey}>
        <Markdown content={output} evidence />
      </CollapsibleSpeech>
    );
  }

  return (
    <ul className="space-y-0.5">
      {arguments_.map((arg) => (
        <ArgumentRow
          key={arg.id}
          argument={arg}
          sceneKey={`${sceneKey}:arg:${arg.id}`}
        />
      ))}
    </ul>
  );
}

function ArgumentRow({
  argument,
  sceneKey,
}: {
  argument: SpeechArgument;
  sceneKey: string;
}) {
  const [open, setOpen] = usePersistentDisclosure(sceneKey, false);
  return (
    <li className="list-none rounded-lg bg-muted/15">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-1.5 px-2 py-1.5 text-left text-xs hover:bg-muted/35"
      >
        {open ? (
          <ChevronDown
            size={12}
            className="mt-0.5 shrink-0 text-muted-foreground"
          />
        ) : (
          <ChevronRight
            size={12}
            className="mt-0.5 shrink-0 text-muted-foreground"
          />
        )}
        <span
          className={`min-w-0 flex-1 text-sm leading-snug text-foreground ${
            open ? "whitespace-normal break-words" : "truncate"
          }`}
        >
          {argument.title}
        </span>
      </button>
      <div
        className="grid transition-[grid-template-rows,opacity] duration-200 ease-out"
        style={{
          gridTemplateRows: open ? "1fr" : "0fr",
          opacity: open ? 1 : 0,
        }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border/40 px-2 pb-2 pt-1.5">
            <Markdown content={argument.body} evidence />
          </div>
        </div>
      </div>
    </li>
  );
}

function SpeakerMeta({
  name,
  colorVar,
  stage,
  status,
}: {
  name: string;
  colorVar: string;
  stage: string;
  status: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
      <span className="font-medium text-foreground" style={{ color: colorVar }}>
        {name}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="text-muted-foreground">{stage}</span>
      {status && (
        <>
          <span className="text-muted-foreground">·</span>
          {status}
        </>
      )}
    </div>
  );
}

export { speechStageLabel };
