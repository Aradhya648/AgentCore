import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui";
import { useIsDark } from "@/lib/useIsDark";
import type { RunNode } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { MergeView } from "@codemirror/merge";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { ChevronRight, Eye, GitCompare } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { type ResolvedCell, looksLikeEdit, placeholder } from "./cells";

/**
 * 共享精读对比面（{@link import("./TurnCompare").TurnCompare} 的下层）——把选中的**两格**
 * （版本链跨版本、或辩论跨轮/跨方，皆可）并排细读。读起来像一次**编辑**（{@link looksLikeEdit}）
 * → 自动开真·文本 diff（@codemirror/merge，可切回渲染）；否则（跨角色 / 辩论每轮针对新焦点重答）
 * → 2-up 渲染并读。每侧各标自己的角色（这一对可能跨链/跨方）。辩论与修订共用此面，故辩论侧也能
 * 对某方 round3 × round5 看论证怎么演进（旧擂台做不到、旧版本对比又对辩论一刀切禁了 diff）。
 */
export function ComparePane({
  a,
  b,
  messageId,
}: {
  a: ResolvedCell | null;
  b: ResolvedCell | null;
  messageId: string;
}) {
  const outA = a?.output ?? "";
  const outB = b?.output ?? "";
  const canDiff = looksLikeEdit(outA, outB);
  const [mode, setMode] = useState<"diff" | "render">(
    canDiff ? "diff" : "render",
  );

  // 每换一对就重置默认视图——读作编辑的新对开 diff、否则渲染；手动 差异/渲染 切换只在当前对内粘住。
  const aId = a?.run.id ?? "";
  const bId = b?.run.id ?? "";
  // biome-ignore lint/correctness/useExhaustiveDependencies: aId/bId are intentional re-run keys — reset the default view when the compared pair changes.
  useEffect(() => {
    setMode(canDiff ? "diff" : "render");
  }, [aId, bId, canDiff]);

  if (!a || !b) {
    return (
      <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground">
        选两段内容进行对比。
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-muted/20">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <PairTag slot="A" cell={a} />
        <ChevronRight size={12} className="shrink-0 text-muted-foreground/50" />
        <PairTag slot="B" cell={b} />
        <span className="flex-1" />
        {canDiff && (
          <div className="flex items-center gap-0.5 rounded-lg border border-border p-0.5">
            <SegBtn
              active={mode === "diff"}
              onClick={() => setMode("diff")}
              icon={<GitCompare size={12} />}
              label="差异"
            />
            <SegBtn
              active={mode === "render"}
              onClick={() => setMode("render")}
              icon={<Eye size={12} />}
              label="渲染"
            />
          </div>
        )}
      </div>

      {mode === "diff" ? (
        <DiffPane a={outA} b={outB} />
      ) : (
        <div className="grid grid-cols-2 gap-3 p-3">
          <CompareCell
            output={outA}
            run={a.run}
            role={a.role}
            messageId={messageId}
          />
          <CompareCell
            output={outB}
            run={b.run}
            role={b.role}
            messageId={messageId}
          />
        </div>
      )}
    </div>
  );
}

/** 2-up 渲染对比的一侧：有产出则渲染 markdown，否则给一枚钻右坞完整产出的占位。 */
function CompareCell({
  output,
  run,
  role,
  messageId,
}: {
  output: string;
  run: RunNode;
  role: string;
  messageId: string;
}) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  return (
    <div className="min-w-0">
      {output ? (
        <div className="max-h-[60vh] overflow-y-auto text-sm">
          <Markdown content={output} />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => showRunDetail(messageId, run.id, role)}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          {placeholder(run)}
        </button>
      )}
    </div>
  );
}

/** 两段的真·文本 diff（@codemirror/merge 左右并排）：未变区折叠、只读改动，删在左 / 增在右。
 * 纯文本（不 markdown 高亮）——改动高亮才是信息；配色随 app 明暗。只读。 */
function DiffPane({ a, b }: { a: string; b: string }) {
  const host = useRef<HTMLDivElement>(null);
  const dark = useIsDark();

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const ext = [
      EditorView.editable.of(false),
      EditorState.readOnly.of(true),
      EditorView.lineWrapping,
      EditorView.theme(DIFF_LAYOUT, { dark }),
    ];
    const view = new MergeView({
      a: { doc: a, extensions: ext },
      b: { doc: b, extensions: ext },
      parent: el,
      gutter: true,
      highlightChanges: true,
      collapseUnchanged: { margin: 3, minSize: 8 },
    });
    return () => view.destroy();
  }, [a, b, dark]);

  return <div ref={host} className="max-h-[60vh] overflow-auto" />;
}

/** 紧凑的「slot · 角色 label 原始/最新」对比头标签（显角色，因这一对可能跨链/跨方）。 */
function PairTag({ slot, cell }: { slot: "A" | "B"; cell: ResolvedCell }) {
  return (
    <span className="flex items-center gap-1 text-xs">
      <span className="rounded bg-primary px-1 text-xs font-semibold text-primary-foreground">
        {slot}
      </span>
      <StatusDot status={cell.run.status} />
      <span className="truncate text-muted-foreground">{cell.role}</span>
      <span className="font-medium text-foreground">{cell.label}</span>
      {cell.tag && <span className="text-muted-foreground">{cell.tag}</span>}
    </span>
  );
}

/** 差异/渲染 分段控件按钮。 */
function SegBtn({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <Button
      variant={active ? "primary" : "ghost"}
      size="sm"
      onClick={onClick}
      className="h-6 gap-1 px-2 text-xs"
    >
      {icon}
      {label}
    </Button>
  );
}

const STATUS_DOT: Record<RunNode["status"], string> = {
  pending: "bg-muted-foreground/30",
  running: "bg-primary",
  completed: "bg-success",
  failed: "bg-destructive",
  cancelled: "bg-muted-foreground/30",
  skipped: "bg-muted-foreground/30",
};

/** 一枚随 run 状态着色的状态点（对比透镜两层共用）。 */
export function StatusDot({ status }: { status: RunNode["status"] }) {
  return (
    <span className={`size-2 shrink-0 rounded-full ${STATUS_DOT[status]}`} />
  );
}

/** diff 的布局-only CodeMirror 主题（改动色来自 merge baseTheme 的 `{ dark }`）：app 正文字体、
 * 克制内距、透明底。 */
const SANS =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif';
const DIFF_LAYOUT = {
  "&": { backgroundColor: "transparent", fontSize: "13px" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: SANS, lineHeight: "1.6" },
  ".cm-content": { padding: "6px 0" },
  ".cm-line": { padding: "0 10px" },
  ".cm-gutters": { backgroundColor: "transparent", border: "none" },
};
