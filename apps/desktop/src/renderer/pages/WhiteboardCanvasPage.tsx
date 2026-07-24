import { Button, IconButton } from "@/components/ui";
import { FilePreviewView } from "@/components/workspace/FilePreviewView";
import { notifyError, notifyInfo } from "@/lib/toast";
import {
  buildCrystallizedElements,
  crystallizedRunIds,
} from "@/services/boardCrystallize";
import {
  type BoardApplyResult,
  registerBoardApplier,
} from "@/services/boardOps";
import {
  type OverlayAnchor,
  buildProgressOverlay,
} from "@/services/boardProgress";
import {
  type BoardRasterResult,
  registerBoardReader,
} from "@/services/boardRead";
import {
  implementSelectionPrompt,
  iterateArtifactPrompt,
  organizeSelectionPrompt,
  sendBoardTurn,
} from "@/services/boardTurn";
import {
  type BoardDetail,
  type BoardScene,
  getBoard,
  renameBoard,
  saveBoardScene,
} from "@/services/boards";
import { createWorkspaceSource } from "@/services/sources/workspaceSource";
import {
  lastAssistantProjectionId,
  runtimeOf,
  useConversationStore,
} from "@/stores/conversation";
import { type Execution, useMessageExecution } from "@/stores/execution";
import type { BoardOp } from "@/types/events";
import {
  type SceneElement,
  type Viewport,
  type WhiteboardApi,
  WhiteboardCanvas,
  parseScene,
  serializeScene,
} from "@/whiteboard";
import { ArrowLeft, ArrowUp, Loader2, Sparkles, Square, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

/** Subscribe to a board conversation's live team run tree (M3 进度贴源). The execution store is
 * keyed by projection id (`serverMessageId ?? id`), so resolve the board conversation's latest
 * assistant turn reactively, then project its run tree — re-folds on every frame and re-targets
 * when a new turn appends a new assistant message. Null until a turn delegates a team (a solo
 * CEO turn declares no run plan, so there is nothing to show). */
function useBoardExecution(conversationId: string | null): Execution | null {
  const messageId = useConversationStore((s) =>
    conversationId
      ? lastAssistantProjectionId(runtimeOf(s, conversationId).messages)
      : null,
  );
  return useMessageExecution(messageId);
}

/** A team run that has stopped producing frames — its progress overlay can hand off to the
 * persistent crystallized cards (M3 Slice 3). */
function isExecTerminal(status: Execution["status"]): boolean {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}

type SaveStatus = "idle" | "saving" | "saved" | "error";

const STATUS_TEXT: Record<SaveStatus, string> = {
  idle: "",
  saving: "保存中…",
  saved: "已保存",
  error: "保存失败",
};

/** One board's canvas (AI协作白板.md §六 自研引擎 / §十 M1). Loads the scene from the
 * backend into the self-built {@link WhiteboardCanvas}, autosaves it back (debounced) with
 * a CAS ``baseline`` so a stale tab/device never clobbers — on conflict autosave pauses and
 * offers a reload (§七 不覆盖). The 2026-06-27 engine reversal replaced Excalidraw here; the
 * backend board_ops protocol is unchanged (§五.4), the applier now drives `applyOps`. */
export function WhiteboardCanvasPage() {
  const { boardId = "" } = useParams();
  const navigate = useNavigate();

  const [board, setBoard] = useState<BoardDetail | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [conflict, setConflict] = useState(false);
  const [title, setTitle] = useState("");

  // 老板命令栏 (AI协作白板.md §六 M2 入口): the draft order + whether an AI turn on this
  // board is in flight (turns don't stack — the bar is disabled meanwhile, with a stop).
  const [aiInput, setAiInput] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const aiAbortRef = useRef<AbortController | null>(null);
  /** File artifact preview (WB-003): opened from a crystallized `artifactCard`. */
  const [filePreview, setFilePreview] = useState<{
    path: string;
    name: string;
  } | null>(null);
  const [textExpand, setTextExpand] = useState<{
    title: string;
    body: string;
  } | null>(null);

  // M3 进度贴源 (AI协作白板.md §十 Slice 2): the board's AI conversation id (resolved on the
  // first turn) drives the live run-tree subscription; the brief anchor is the launching
  // selection's bbox, snapshotted at send so the team cards sit beside what was asked.
  const [boardConvId, setBoardConvId] = useState<string | null>(null);
  const briefAnchorRef = useRef<OverlayAnchor | null>(null);
  // M3 产物回贴 (Slice 3): the execution id already crystallized into the scene, so a finished
  // team becomes persistent cards exactly once per turn (re-fires also dedupe by run id below).
  const crystallizedExecRef = useRef<string | null>(null);

  // Imperative engine handle — the AI applier reads the live scene + pushes ops through it.
  const apiRef = useRef<WhiteboardApi | null>(null);
  // CAS version of the last load/save; sent as the next write's baseline.
  const versionRef = useRef(0);
  // Latest scene snapshot from the engine (the debounced flush reads this).
  const latestRef = useRef<{
    elements: SceneElement[];
    viewport: Viewport;
  } | null>(null);
  // Serialized elements of the last persisted/loaded state — skip no-op saves (and ignore
  // pan/zoom, which never reach onChange) so merely opening a board doesn't bump the version.
  const savedSceneRef = useRef("");
  const conflictRef = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchBoard = useCallback(() => {
    setBoard(null);
    setLoadError(false);
    setStatus("idle");
    setConflict(false);
    conflictRef.current = false;
    latestRef.current = null;
    getBoard(boardId)
      .then((b) => {
        versionRef.current = b.version;
        setTitle(b.title);
        setBoard(b);
      })
      .catch(() => setLoadError(true));
  }, [boardId]);

  useEffect(() => {
    fetchBoard();
  }, [fetchBoard]);

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      // Leaving the board: stop pumping this turn's stream (it detaches server-side; the
      // applier is unregistered on unmount, so further ops would have nowhere to land).
      aiAbortRef.current?.abort();
    };
  }, []);

  const initialData = useMemo(() => {
    if (!board) return null;
    const parsed = parseScene(board.scene);
    savedSceneRef.current = JSON.stringify(parsed.elements);
    return parsed;
  }, [board]);

  // CAS-write the scene. Shared by the debounced autosave (user edits) and the AI applier
  // (which needs the resulting version for its 回执). Returns the new version, or null on
  // conflict/error. A no-op (elements unchanged) returns the current version.
  const persistScene = useCallback(
    async (
      elements: SceneElement[],
      viewport: Viewport,
    ): Promise<number | null> => {
      const key = JSON.stringify(elements);
      if (key === savedSceneRef.current) return versionRef.current;
      setStatus("saving");
      try {
        const scene = serializeScene(
          elements,
          viewport,
        ) as unknown as BoardScene;
        const res = await saveBoardScene(boardId, scene, versionRef.current);
        if (res.conflict) {
          conflictRef.current = true;
          setConflict(true);
          setStatus("idle");
          return null;
        }
        versionRef.current = res.version;
        savedSceneRef.current = key;
        setStatus("saved");
        return res.version;
      } catch {
        setStatus("error");
        return null;
      }
    },
    [boardId],
  );

  const flush = useCallback(async () => {
    const snap = latestRef.current;
    if (!snap || conflictRef.current) return;
    await persistScene(snap.elements, snap.viewport);
  }, [persistScene]);

  const handleChange = useCallback(
    (elements: SceneElement[], viewport: Viewport) => {
      latestRef.current = { elements, viewport };
      if (conflictRef.current) return;
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => void flush(), 1500);
    },
    [flush],
  );

  // The AI's hands on this canvas (AI协作白板.md §六 M2): apply the op batch through the
  // engine, then CAS-save so the 回执 carries the real version. Registered (keyed by board
  // id) only while THIS canvas is open, so board_op_required for a board no one is viewing
  // fails cleanly (the handler reports「画布未打开」).
  const applyOps = useCallback(
    async (ops: BoardOp[]): Promise<BoardApplyResult> => {
      const api = apiRef.current;
      if (!api) throw new Error("画布尚未就绪");
      if (conflictRef.current) {
        throw new Error("白板存在版本冲突，已暂停修改，请先重新加载");
      }
      const { created } = api.applyOps(ops);
      const version = await persistScene(api.getScene(), api.getViewport());
      if (version === null) throw new Error("白板保存失败（可能版本冲突）");
      return { applied: ops.length, created, version };
    },
    [persistScene],
  );

  useEffect(() => {
    if (!boardId) return;
    return registerBoardApplier(boardId, applyOps);
  }, [boardId, applyOps]);

  // The AI's eyes on this canvas (AI协作白板.md §九 读图): rasterize a subset of elements to a
  // PNG for the vision reader. Read-only (no CAS save). Registered (keyed by board id) only
  // while THIS canvas is open, so board_read for a board no one is viewing fails cleanly.
  const rasterize = useCallback(
    async (ids: string[]): Promise<BoardRasterResult> => {
      const api = apiRef.current;
      if (!api) throw new Error("画布尚未就绪");
      return api.rasterizeElements(ids);
    },
    [],
  );

  useEffect(() => {
    if (!boardId) return;
    return registerBoardReader(boardId, rasterize);
  }, [boardId, rasterize]);

  const runBoardTurn = useCallback(
    async (prompt: string) => {
      if (!boardId || aiBusy) return;
      // Snapshot the brief anchor (the selection the team works "from") so live progress cards
      // dock beside it; no selection (a bare command-bar order) → no anchor → no overlay.
      briefAnchorRef.current = apiRef.current?.getSelectionBounds() ?? null;
      setAiBusy(true);
      const ac = new AbortController();
      aiAbortRef.current = ac;
      try {
        await sendBoardTurn(boardId, prompt, {
          signal: ac.signal,
          onConversation: setBoardConvId,
        });
      } catch (err) {
        if (!ac.signal.aborted) notifyError(err, "AI 作画失败");
      } finally {
        if (aiAbortRef.current === ac) aiAbortRef.current = null;
        setAiBusy(false);
      }
    },
    [boardId, aiBusy],
  );

  // M3 进度贴源 (Slice 2): the live team run tree → transient overlay cards anchored beside the
  // brief. Shows ONLY a non-terminal run — a finished turn hands off to the persistent
  // crystallize below, so the completed cards aren't briefly doubled. Clears when there is no
  // team (a solo CEO turn) or no anchor. Pure overlay — never enters the scene / history / save.
  const execution = useBoardExecution(boardConvId);
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const anchor = briefAnchorRef.current;
    const live =
      execution && !isExecTerminal(execution.status) ? execution : null;
    api.setOverlay(live && anchor ? buildProgressOverlay(live, anchor) : []);
  }, [execution]);

  // M3 产物回贴 (Slice 3): when a team turn ends, crystallize its run tree into persistent
  // `agentNode` / `artifactCard` cards beside the brief (one CAS save via the normal autosave),
  // then drop the transient overlay. Idempotent — keyed by execution id and deduped by the run
  // ids already on the board, so a re-fire or a follow-up iteration turn (Slice 4) never dupes.
  useEffect(() => {
    const api = apiRef.current;
    if (!api || !execution || !isExecTerminal(execution.status)) return;
    if (crystallizedExecRef.current === execution.id) return;
    const anchor = briefAnchorRef.current;
    if (!anchor) return;
    const cards = buildCrystallizedElements(
      execution,
      anchor,
      crystallizedRunIds(api.getScene()),
    );
    crystallizedExecRef.current = execution.id;
    if (cards.length > 0) {
      api.addElements(cards);
      api.setOverlay([]);
    }
  }, [execution]);

  const submitOrder = useCallback(() => {
    const text = aiInput.trim();
    if (!text || aiBusy) return;
    setAiInput("");
    void runBoardTurn(text);
  }, [aiInput, aiBusy, runBoardTurn]);

  // 选区 → 帮我整理结构 (§九 混合 payload): structured elements go as text (real ids the AI
  // targets with board_ops); hand-drawn/截图 (freedraw) in the selection make the prompt tell
  // the CEO to board_read those ids first. No selection → a hint, not a turn.
  const organizeSelection = useCallback(() => {
    const api = apiRef.current;
    if (!api || aiBusy) return;
    const ids = api.getSelectedIds();
    if (ids.length === 0) {
      notifyInfo("请先在白板上选择要整理的元素");
      return;
    }
    void runBoardTurn(organizeSelectionPrompt(api.getScene(), ids));
  }, [aiBusy, runBoardTurn]);

  // 选区 / frame →「让团队照这实现」(§十 M3 发起入口): hand the selection to the CEO as the
  // requirement brief and let it assemble the team + implement — delegate / debate / 单干 is
  // the CEO's call (提案 A). Same 混合 payload as 整理 (structured as text, 手绘/截图 via
  // board_read); no selection → a hint, not a turn.
  const implementSelection = useCallback(() => {
    const api = apiRef.current;
    if (!api || aiBusy) return;
    const ids = api.getSelectedIds();
    if (ids.length === 0) {
      notifyInfo("请先在白板上选择作为需求的内容");
      return;
    }
    void runBoardTurn(implementSelectionPrompt(api.getScene(), ids));
  }, [aiBusy, runBoardTurn]);

  // 在产物上迭代 (§十 M3 Slice 4 贴源迭代): feed the selected crystallized artifactCard(s) — plus
  // any annotations drawn beside them — back to the CEO as「上一版 + 改进意见」for the next
  // version. The crystallizer appends the new run's cards beside the old (旧版留痕). The floating
  // button is shown only when an artifactCard is selected, so ids always carry one here.
  const iterateArtifact = useCallback(() => {
    const api = apiRef.current;
    if (!api || aiBusy) return;
    const ids = api.getSelectedIds();
    if (ids.length === 0) {
      notifyInfo("请先选中要迭代的产物卡");
      return;
    }
    void runBoardTurn(iterateArtifactPrompt(api.getScene(), ids));
  }, [aiBusy, runBoardTurn]);

  const fileSource = useMemo(
    () =>
      boardConvId ? createWorkspaceSource(boardConvId, "白板工作区") : null,
    [boardConvId],
  );

  const handleArtifactActivate = useCallback(
    (el: SceneElement) => {
      if (el.type !== "artifactCard") return;
      if (el.artifactKind === "file" && el.ref) {
        if (!boardConvId || !fileSource) {
          notifyInfo("先发起一次团队任务后才有工作区文件可预览");
          return;
        }
        const slash = el.ref.lastIndexOf("/");
        setFilePreview({
          path: el.ref,
          name: slash >= 0 ? el.ref.slice(slash + 1) : el.ref,
        });
        return;
      }
      setTextExpand({
        title: el.title ?? "产物",
        body: el.text ?? "",
      });
    },
    [boardConvId, fileSource],
  );

  const stopBoardTurn = useCallback(() => {
    aiAbortRef.current?.abort();
  }, []);

  const commitTitle = useCallback(async () => {
    const next = title.trim();
    if (!board || !next || next === board.title) {
      setTitle(board?.title ?? "");
      return;
    }
    try {
      const updated = await renameBoard(boardId, next);
      setBoard((b) => (b ? { ...b, title: updated.title } : b));
    } catch {
      setTitle(board.title);
    }
  }, [title, board, boardId]);

  if (loadError) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
        <p className="text-sm text-muted-foreground">白板加载失败</p>
        <div className="flex gap-2">
          <Button variant="neutral" onClick={() => navigate("/whiteboard")}>
            返回列表
          </Button>
          <Button variant="primary" onClick={fetchBoard}>
            重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 flex flex-col">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-background px-3">
        <IconButton
          aria-label="返回白板列表"
          onClick={() => navigate("/whiteboard")}
        >
          <ArrowLeft size={16} />
        </IconButton>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => void commitTitle()}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
          placeholder="未命名白板"
          aria-label="白板标题"
          className="min-w-0 max-w-xs flex-1 rounded-lg bg-transparent px-2 py-1 text-sm font-medium text-foreground outline-none hover:bg-accent focus:bg-accent"
        />
        <span className="ml-auto text-xs text-muted-foreground">
          {STATUS_TEXT[status]}
        </span>
      </header>

      {conflict ? (
        <div className="flex shrink-0 items-center gap-3 border-b border-border bg-destructive/10 px-3 py-2">
          <span className="text-xs text-foreground">
            此白板已在别处更新，为避免覆盖已暂停自动保存。
          </span>
          <Button
            variant="primary"
            size="sm"
            className="ml-auto"
            onClick={fetchBoard}
          >
            重新加载
          </Button>
        </div>
      ) : null}

      <div className="relative flex-1">
        {board && initialData ? (
          <WhiteboardCanvas
            key={board.id}
            ref={apiRef}
            initialElements={initialData.elements}
            initialViewport={initialData.viewport}
            onChange={handleChange}
            onOrganizeSelection={organizeSelection}
            onImplementSelection={implementSelection}
            onIterateArtifact={iterateArtifact}
            onArtifactActivate={handleArtifactActivate}
            aiBusy={aiBusy}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="animate-spin text-muted-foreground" size={24} />
          </div>
        )}
      </div>

      <footer className="flex shrink-0 items-end gap-2 border-t border-border bg-card px-4 py-3">
        <Button
          variant="neutral"
          size="sm"
          onClick={organizeSelection}
          disabled={aiBusy || !board}
          className="shrink-0 gap-1.5"
        >
          <Sparkles size={15} />
          整理选区
        </Button>
        <textarea
          value={aiInput}
          onChange={(e) => {
            setAiInput(e.target.value);
            e.target.style.height = "0";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
          }}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submitOrder();
            }
          }}
          rows={1}
          disabled={aiBusy}
          placeholder="让 AI 在白板上作画 / 整理结构…（Enter 发送，Shift+Enter 换行）"
          aria-label="向 AI 下达白板指令"
          className="max-h-28 min-h-[2.5rem] flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-60"
        />
        {aiBusy ? (
          <IconButton
            aria-label="停止"
            onClick={stopBoardTurn}
            className="size-10 rounded-xl"
          >
            <Square size={16} />
          </IconButton>
        ) : (
          <IconButton
            aria-label="下达指令"
            tone="primary"
            onClick={submitOrder}
            disabled={!aiInput.trim() || !board}
            className="size-10 rounded-xl"
          >
            <ArrowUp size={18} />
          </IconButton>
        )}
      </footer>

      {filePreview && fileSource ? (
        <div className="absolute inset-0 z-40 flex flex-col bg-background">
          <FilePreviewView
            source={fileSource}
            path={filePreview.path}
            name={filePreview.name}
            onClose={() => setFilePreview(null)}
          />
        </div>
      ) : null}

      {textExpand ? (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-background/80 p-6 backdrop-blur-sm">
          <div className="flex max-h-[min(80vh,640px)] w-full max-w-lg flex-col rounded-xl border border-border bg-card shadow-lg">
            <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
              <h2 className="truncate text-sm font-semibold text-foreground">
                {textExpand.title}
              </h2>
              <IconButton aria-label="关闭" onClick={() => setTextExpand(null)}>
                <X size={16} />
              </IconButton>
            </header>
            <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 text-sm text-foreground">
              {textExpand.body}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}
