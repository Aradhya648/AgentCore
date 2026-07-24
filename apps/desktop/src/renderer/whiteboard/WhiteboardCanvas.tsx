import { IconButton } from "@/components/ui";
import { notifyActionError } from "@/lib/toast";
import { useIsDark } from "@/lib/useIsDark";
import { cn } from "@/lib/utils";
import { saveBlob } from "@/services/workspaceHttp";
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignLeft,
  AlignRight,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
  Ban,
  Circle,
  Diamond,
  Eraser,
  Frame,
  Hand,
  ImagePlus,
  LayoutGrid,
  Maximize,
  Minus,
  MousePointer2,
  MoveUpRight,
  Pencil,
  Redo2,
  RefreshCw,
  Sparkles,
  Square,
  StickyNote,
  Trash2,
  Type,
  Undo2,
  Users,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  type ChangeEvent,
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { readSwatches } from "./colors";
import { WhiteboardEngine } from "./engine";
import type { AlignEdge } from "./selectionOps";
import {
  DEFAULT_STROKE_WIDTH,
  STROKE_WIDTHS,
  type SceneElement,
  type StrokeStyle,
  type TextAlign,
  type Tool,
  type Viewport,
  type WhiteboardApi,
} from "./types";

interface MenuState {
  x: number;
  y: number;
}

interface SelStyle {
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  strokeStyle?: StrokeStyle;
  textAlign?: TextAlign;
  opacity?: number;
}

export interface WhiteboardCanvasProps {
  initialElements: SceneElement[];
  initialViewport?: Viewport;
  /** Preselect these element ids after the scene loads — the offline preview
   * (`#/preview/whiteboard`) uses it to render a selected state (rotation handle / selection
   * bar); the app never sets it (selection comes from pointer). */
  initialSelectedIds?: string[];
  /** Fired on every committed element mutation (host debounces + autosaves). */
  onChange: (elements: SceneElement[], viewport: Viewport) => void;
  /** Host triggers「整理选区」from the floating selection bar. */
  onOrganizeSelection?: () => void;
  /** Host triggers「让团队照这实现」(M3 发起入口) from the floating selection bar. */
  onImplementSelection?: () => void;
  /** Host triggers「在产物上迭代」(M3 Slice 4 贴源迭代) — shown only when the selection holds a
   * crystallized `artifactCard`. */
  onIterateArtifact?: () => void;
  /** Double-click a crystallized `artifactCard` — open file preview or expand text body. */
  onArtifactActivate?: (el: SceneElement) => void;
  aiBusy?: boolean;
  className?: string;
}

const TOOLS: Array<{ tool: Tool; icon: typeof Square; label: string }> = [
  { tool: "select", icon: MousePointer2, label: "选择 (V)" },
  { tool: "hand", icon: Hand, label: "抓手 / 平移 (H / 空格)" },
  { tool: "rectangle", icon: Square, label: "矩形 (R)" },
  { tool: "ellipse", icon: Circle, label: "椭圆 (O)" },
  { tool: "diamond", icon: Diamond, label: "菱形 (D)" },
  { tool: "arrow", icon: MoveUpRight, label: "箭头 (A)" },
  { tool: "line", icon: Minus, label: "直线 (L)" },
  { tool: "sticky", icon: StickyNote, label: "便签 (S)" },
  { tool: "text", icon: Type, label: "文字 (T)" },
  { tool: "freedraw", icon: Pencil, label: "画笔 (P)" },
  { tool: "frame", icon: Frame, label: "区域框 (F)" },
  { tool: "eraser", icon: Eraser, label: "橡皮 (E)" },
];

/** One labeled row of color swatches (描边 / 填充) for the selection style panel. */
function StyleRow({
  label,
  swatches,
  active,
  onPick,
}: {
  label: string;
  swatches: string[];
  active?: string;
  onPick: (c: string | null) => void;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="px-0.5 text-xs text-muted-foreground">{label}</span>
      {swatches.map((c) => (
        <button
          key={c}
          type="button"
          aria-label={`${label} ${c}`}
          title={label}
          onClick={() => onPick(c)}
          // Content color (token-derived oklch from --agent-*) — applied inline per
          // color-tokens.mdc's content-color carve-out, not a hardcoded chrome color.
          style={{ backgroundColor: c }}
          className={cn(
            "size-5 rounded-full border border-border/60 transition",
            active === c &&
              "ring-2 ring-primary ring-offset-1 ring-offset-card",
          )}
        />
      ))}
      <button
        type="button"
        aria-label={`清除${label}`}
        title={`清除${label}（恢复默认）`}
        onClick={() => onPick(null)}
        className={cn(
          "flex size-5 items-center justify-center rounded-full border border-border text-muted-foreground hover:bg-accent",
          active === undefined &&
            "ring-2 ring-primary ring-offset-1 ring-offset-card",
        )}
      >
        <Ban size={12} />
      </button>
    </div>
  );
}

const WIDTH_LABELS = ["细", "中", "粗"];

/** Outline width presets + solid/dashed toggle for the selection style panel. Visuals are
 * pure CSS (a thickening dot, a solid / dashed rule) so no extra icons are needed. */
function StrokeRow({
  activeWidth,
  dashed,
  onWidth,
  onStyle,
}: {
  activeWidth: number;
  dashed: boolean;
  onWidth: (w: number) => void;
  onStyle: (s: StrokeStyle) => void;
}) {
  const cell =
    "flex size-5 items-center justify-center rounded-full border border-border/60 text-foreground transition hover:bg-accent";
  const ring = "ring-2 ring-primary ring-offset-1 ring-offset-card";
  return (
    <div className="flex items-center gap-1">
      <span className="px-0.5 text-xs text-muted-foreground">线宽</span>
      {STROKE_WIDTHS.map((w, i) => (
        <button
          key={w}
          type="button"
          aria-label={`线宽 ${WIDTH_LABELS[i]}`}
          title={WIDTH_LABELS[i]}
          onClick={() => onWidth(w)}
          className={cn(cell, activeWidth === w && ring)}
        >
          <span
            className="block rounded-full bg-current"
            style={{ width: 12, height: Math.min(6, w) }}
          />
        </button>
      ))}
      <div className="h-5 w-px bg-border" />
      <span className="px-0.5 text-xs text-muted-foreground">线型</span>
      <button
        type="button"
        aria-label="实线"
        title="实线"
        onClick={() => onStyle("solid")}
        className={cn(cell, !dashed && ring)}
      >
        <span className="block w-3.5 border-current border-t-2 border-solid" />
      </button>
      <button
        type="button"
        aria-label="虚线"
        title="虚线"
        onClick={() => onStyle("dashed")}
        className={cn(cell, dashed && ring)}
      >
        <span className="block w-3.5 border-current border-t-2 border-dashed" />
      </button>
    </div>
  );
}

/** Text horizontal alignment for sticky / text elements. */
function TextAlignRow({
  active,
  onPick,
}: {
  active?: TextAlign;
  onPick: (a: TextAlign) => void;
}) {
  const cell =
    "flex size-5 items-center justify-center rounded-full border border-border/60 text-foreground transition hover:bg-accent";
  const ring = "ring-2 ring-primary ring-offset-1 ring-offset-card";
  const items: Array<{
    align: TextAlign;
    icon: typeof AlignLeft;
    label: string;
  }> = [
    { align: "left", icon: AlignLeft, label: "左对齐" },
    { align: "center", icon: AlignCenterHorizontal, label: "居中" },
    { align: "right", icon: AlignRight, label: "右对齐" },
  ];
  return (
    <div className="flex items-center gap-1">
      <span className="px-0.5 text-xs text-muted-foreground">对齐</span>
      {items.map(({ align, icon: Icon, label }) => (
        <button
          key={align}
          type="button"
          aria-label={label}
          title={label}
          onClick={() => onPick(align)}
          className={cn(cell, active === align && ring)}
        >
          <Icon size={13} />
        </button>
      ))}
    </div>
  );
}

/** Opacity slider 10%–100% for the selection. */
function OpacityRow({
  active,
  onPick,
}: {
  active: number;
  onPick: (o: number) => void;
}) {
  const pct = Math.round(active * 100);
  return (
    <div className="flex items-center gap-1.5">
      <span className="px-0.5 text-xs text-muted-foreground">透明度</span>
      <input
        type="range"
        min={10}
        max={100}
        value={pct}
        onChange={(e) => onPick(Number(e.target.value) / 100)}
        className="h-1 w-20 accent-primary"
        aria-label="透明度"
      />
      <span className="w-8 text-xs text-muted-foreground">{pct}%</span>
    </div>
  );
}

/** One row in the right-click context menu. */
function MenuItem({
  label,
  hint,
  disabled,
  onClick,
}: {
  label: string;
  hint?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full items-center justify-between gap-6 rounded-lg px-2.5 py-1.5 text-left text-sm text-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-40"
    >
      <span>{label}</span>
      {hint ? (
        <span className="text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </button>
  );
}

const ALIGN_ACTIONS: Array<{
  icon: typeof Square;
  label: string;
  edge: AlignEdge;
}> = [
  { icon: AlignStartVertical, label: "左对齐", edge: "left" },
  { icon: AlignCenterVertical, label: "水平居中", edge: "centerX" },
  { icon: AlignEndVertical, label: "右对齐", edge: "right" },
  { icon: AlignStartHorizontal, label: "顶对齐", edge: "top" },
  { icon: AlignCenterHorizontal, label: "垂直居中", edge: "centerY" },
  { icon: AlignEndHorizontal, label: "底对齐", edge: "bottom" },
];

/** Compact icon row of align (≥2 selected) + distribute (≥3) actions for the context menu. */
function AlignRow({
  canAlign,
  canDistribute,
  run,
}: {
  canAlign: boolean;
  canDistribute: boolean;
  run: (fn: (e: WhiteboardEngine) => void) => void;
}) {
  const btn =
    "flex size-7 items-center justify-center rounded-lg text-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-40";
  return (
    <div className="flex items-center gap-0.5 px-1 py-1">
      {ALIGN_ACTIONS.map(({ icon: Icon, label, edge }) => (
        <button
          key={edge}
          type="button"
          title={label}
          aria-label={label}
          disabled={!canAlign}
          onClick={() => run((e) => e.alignSelected(edge))}
          className={btn}
        >
          <Icon size={15} />
        </button>
      ))}
      <div className="mx-0.5 h-5 w-px bg-border" />
      <button
        type="button"
        title="水平分布"
        aria-label="水平分布"
        disabled={!canDistribute}
        onClick={() => run((e) => e.distributeSelected("x"))}
        className={btn}
      >
        <AlignHorizontalDistributeCenter size={15} />
      </button>
      <button
        type="button"
        title="垂直分布"
        aria-label="垂直分布"
        disabled={!canDistribute}
        onClick={() => run((e) => e.distributeSelected("y"))}
        className={btn}
      >
        <AlignVerticalDistributeCenter size={15} />
      </button>
    </div>
  );
}

/** Self-built whiteboard canvas (AI协作白板.md §六) — replaces the old Excalidraw embed.
 * Owns a {@link WhiteboardEngine}; exposes an imperative {@link WhiteboardApi} (read scene,
 * apply AI ops, undo/redo, zoom) to the host page via ref. */
export const WhiteboardCanvas = forwardRef<
  WhiteboardApi,
  WhiteboardCanvasProps
>(function WhiteboardCanvas(
  {
    initialElements,
    initialViewport,
    initialSelectedIds,
    onChange,
    onOrganizeSelection,
    onImplementSelection,
    onIterateArtifact,
    onArtifactActivate,
    aiBusy = false,
    className,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const engineRef = useRef<WhiteboardEngine | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onArtifactActivateRef = useRef(onArtifactActivate);
  onArtifactActivateRef.current = onArtifactActivate;

  const [tool, setTool] = useState<Tool>("select");
  const [zoom, setZoom] = useState(1);
  const [selectionCount, setSelectionCount] = useState(0);
  // M3 Slice 4 (贴源迭代): whether the selection includes a crystallized `artifactCard`, which
  // gates the「迭代」action in the floating bar.
  const [selHasArtifact, setSelHasArtifact] = useState(false);
  const [selHasFrame, setSelHasFrame] = useState(false);
  const [selStyle, setSelStyle] = useState<SelStyle>({});
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [swatches, setSwatches] = useState<string[]>(() => readSwatches());
  const dark = useIsDark();

  // Mount once; the host remounts (key={boardId}) to load a different board, so
  // initialElements/initialViewport are an init-only seed — re-running this effect would
  // recreate the engine and drop edits.
  // biome-ignore lint/correctness/useExhaustiveDependencies: init-only seed, see above.
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const engine = new WhiteboardEngine(canvas, container, {
      onChange: () =>
        onChangeRef.current(engine.getScene(), engine.getViewport()),
      onSelectionChange: (ids) => {
        setSelectionCount(ids.length);
        setSelStyle(engine.getSelectedStyle());
        setSelHasArtifact(engine.hasSelectedType("artifactCard"));
        setSelHasFrame(engine.hasSelectedType("frame"));
      },
      onToolChange: (t) => setTool(t),
      onViewportChange: (z) => setZoom(z),
      onContextMenu: (x, y) => setMenu({ x, y }),
      onArtifactActivate: (el) => onArtifactActivateRef.current?.(el),
    });
    engineRef.current = engine;
    engine.loadScene(initialElements, initialViewport);
    if (initialSelectedIds?.length) engine.selectIds(initialSelectedIds);

    const ro = new ResizeObserver(() => {
      const rect = container.getBoundingClientRect();
      engine.resize(rect.width, rect.height, window.devicePixelRatio || 1);
    });
    ro.observe(container);
    const rect = container.getBoundingClientRect();
    engine.resize(rect.width, rect.height, window.devicePixelRatio || 1);

    return () => {
      ro.disconnect();
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  // `dark` is a trigger only: re-read the palette + swatches from the DOM when the theme
  // flips (the values aren't referenced in the body).
  // biome-ignore lint/correctness/useExhaustiveDependencies: theme-flip trigger, see above.
  useEffect(() => {
    engineRef.current?.setDark();
    setSwatches(readSwatches());
  }, [dark]);

  // Close the context menu on Escape while it's open.
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  // 导出选区 PNG：引擎只负责出 blob（保持框架/IO 无关），落盘统一走 saveBlob 下载
  // 接缝（桌面 = 主进程另存为；web = anchor）。
  const exportSelectionPng = useCallback(() => {
    const blob = engineRef.current?.selectionPngBlob();
    if (!blob) return;
    void saveBlob(blob, "whiteboard-selection.png").catch((e) =>
      notifyActionError("导出选区失败", e),
    );
  }, []);

  useImperativeHandle(
    ref,
    (): WhiteboardApi => ({
      getScene: () => engineRef.current?.getScene() ?? [],
      getViewport: () =>
        engineRef.current?.getViewport() ?? { panX: 0, panY: 0, zoom: 1 },
      getSelectedIds: () => engineRef.current?.getSelectedIds() ?? [],
      getSelectionBounds: () => engineRef.current?.getSelectionBounds() ?? null,
      setOverlay: (elements) => engineRef.current?.setOverlay(elements),
      addElements: (elements) => engineRef.current?.addElements(elements),
      rasterizeElements: (ids) => {
        const engine = engineRef.current;
        if (!engine) throw new Error("画布尚未就绪");
        return engine.rasterizeElements(ids);
      },
      applyOps: (ops) => engineRef.current?.applyOps(ops) ?? { created: [] },
      undo: () => engineRef.current?.undo(),
      redo: () => engineRef.current?.redo(),
      deleteSelected: () => engineRef.current?.deleteSelected(),
      zoomIn: () => engineRef.current?.zoomIn(),
      zoomOut: () => engineRef.current?.zoomOut(),
      zoomToFit: () => engineRef.current?.zoomToFit(),
      zoomToSelection: () => engineRef.current?.zoomToSelection(),
      resetZoom: () => engineRef.current?.resetZoom(),
      exportSelectionPng,
    }),
    [exportSelectionPng],
  );

  const pick = useCallback((t: Tool) => engineRef.current?.setTool(t), []);

  const openImagePicker = useCallback(() => fileInputRef.current?.click(), []);
  const onImagesPicked = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files?.length) engineRef.current?.insertImageFiles(files);
    e.target.value = ""; // reset so picking the same file again still fires onChange
  }, []);

  const applyFill = useCallback((c: string | null) => {
    engineRef.current?.applyStyle({ fill: c });
    setSelStyle(engineRef.current?.getSelectedStyle() ?? {});
  }, []);
  const applyStroke = useCallback((c: string | null) => {
    engineRef.current?.applyStyle({ stroke: c });
    setSelStyle(engineRef.current?.getSelectedStyle() ?? {});
  }, []);
  const applyStrokeWidth = useCallback((w: number) => {
    engineRef.current?.applyStyle({ strokeWidth: w });
    setSelStyle(engineRef.current?.getSelectedStyle() ?? {});
  }, []);
  const applyStrokeStyle = useCallback((s: StrokeStyle) => {
    engineRef.current?.applyStyle({ strokeStyle: s });
    setSelStyle(engineRef.current?.getSelectedStyle() ?? {});
  }, []);
  const applyTextAlign = useCallback((a: TextAlign) => {
    engineRef.current?.applyStyle({ textAlign: a });
    setSelStyle(engineRef.current?.getSelectedStyle() ?? {});
  }, []);
  const applyOpacity = useCallback((o: number) => {
    engineRef.current?.applyStyle({ opacity: o });
    setSelStyle(engineRef.current?.getSelectedStyle() ?? {});
  }, []);
  const runMenu = useCallback((fn: (e: WhiteboardEngine) => void) => {
    const engine = engineRef.current;
    if (engine) fn(engine);
    setMenu(null);
  }, []);

  return (
    <div
      ref={containerRef}
      className={cn("relative h-full w-full overflow-hidden", className)}
    >
      <canvas ref={canvasRef} className="block touch-none" />

      {/* Hidden picker backing the toolbar「插入图片」button (paste / drop also work). */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={onImagesPicked}
      />

      {/* Tool palette */}
      <div className="absolute left-3 top-3 flex flex-col gap-1 rounded-xl border border-border bg-card/95 p-1 shadow-md backdrop-blur">
        {TOOLS.map(({ tool: t, icon: Icon, label }) => (
          <IconButton
            key={t}
            aria-label={label}
            title={label}
            onClick={() => pick(t)}
            className={cn(tool === t && "bg-accent text-foreground")}
          >
            <Icon size={16} />
          </IconButton>
        ))}
        <div className="my-0.5 h-px bg-border" />
        <IconButton
          aria-label="插入图片"
          title="插入图片（也可粘贴 / 拖入）"
          onClick={openImagePicker}
        >
          <ImagePlus size={16} />
        </IconButton>
        <IconButton
          aria-label="删除所选"
          title="删除所选 (Delete)"
          onClick={() => engineRef.current?.deleteSelected()}
          disabled={selectionCount === 0}
        >
          <Trash2 size={16} />
        </IconButton>
      </div>

      {/* History */}
      <div className="absolute right-3 top-3 flex gap-1 rounded-xl border border-border bg-card/95 p-1 shadow-md backdrop-blur">
        <IconButton
          aria-label="撤销"
          title="撤销 (Ctrl+Z)"
          onClick={() => engineRef.current?.undo()}
        >
          <Undo2 size={16} />
        </IconButton>
        <IconButton
          aria-label="重做"
          title="重做 (Ctrl+Shift+Z)"
          onClick={() => engineRef.current?.redo()}
        >
          <Redo2 size={16} />
        </IconButton>
      </div>

      {/* Zoom controls */}
      <div className="absolute bottom-3 right-3 flex items-center gap-1 rounded-xl border border-border bg-card/95 p-1 shadow-md backdrop-blur">
        <IconButton
          aria-label="缩小"
          title="缩小"
          onClick={() => engineRef.current?.zoomOut()}
        >
          <ZoomOut size={16} />
        </IconButton>
        <button
          type="button"
          onClick={() => engineRef.current?.resetZoom()}
          className="min-w-12 rounded-lg px-1 py-1 text-center text-xs text-muted-foreground hover:bg-accent"
          title="重置为 100%"
        >
          {Math.round(zoom * 100)}%
        </button>
        <IconButton
          aria-label="放大"
          title="放大"
          onClick={() => engineRef.current?.zoomIn()}
        >
          <ZoomIn size={16} />
        </IconButton>
        <IconButton
          aria-label="适应内容"
          title="适应内容"
          onClick={() => engineRef.current?.zoomToFit()}
        >
          <Maximize size={16} />
        </IconButton>
        <IconButton
          aria-label="缩放至选区"
          title="缩放至选区 (Ctrl+2)"
          onClick={() => engineRef.current?.zoomToSelection()}
          disabled={selectionCount === 0}
        >
          <Frame size={16} />
        </IconButton>
      </div>

      {/* Selection floating bar — quick AI + layout actions */}
      {selectionCount > 0 && onOrganizeSelection ? (
        <div className="absolute bottom-14 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-xl border border-border bg-card/95 p-1 shadow-md backdrop-blur">
          <button
            type="button"
            disabled={aiBusy}
            onClick={onOrganizeSelection}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-foreground hover:bg-accent disabled:opacity-40"
          >
            <Sparkles size={15} />
            整理选区
          </button>
          {onImplementSelection ? (
            <button
              type="button"
              disabled={aiBusy}
              onClick={onImplementSelection}
              title="让团队照这块内容实现"
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-foreground hover:bg-accent disabled:opacity-40"
            >
              <Users size={15} />
              让团队实现
            </button>
          ) : null}
          {onIterateArtifact && selHasArtifact ? (
            <button
              type="button"
              disabled={aiBusy}
              onClick={onIterateArtifact}
              title="在选中的产物上再迭代一版（旧版留痕）"
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-foreground hover:bg-accent disabled:opacity-40"
            >
              <RefreshCw size={15} />
              迭代
            </button>
          ) : null}
          <div className="h-5 w-px bg-border" />
          <IconButton
            aria-label="网格布局"
            title="网格布局选区"
            disabled={selectionCount < 2}
            onClick={() => engineRef.current?.layoutSelectedGrid()}
          >
            <LayoutGrid size={16} />
          </IconButton>
          <IconButton
            aria-label="导出选区 PNG"
            title="导出选区 PNG"
            onClick={exportSelectionPng}
          >
            <ImagePlus size={16} />
          </IconButton>
        </div>
      ) : null}

      {/* Selection style panel (描边 / 填充 / 线宽 / 线型) — visible only with a selection. */}
      {selectionCount > 0 ? (
        <div className="absolute left-1/2 top-3 flex max-w-[92vw] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded-xl border border-border bg-card/95 px-2 py-1.5 shadow-md backdrop-blur">
          <StyleRow
            label="描边"
            swatches={swatches}
            active={selStyle.stroke}
            onPick={applyStroke}
          />
          <div className="h-5 w-px bg-border" />
          <StyleRow
            label="填充"
            swatches={swatches}
            active={selStyle.fill}
            onPick={applyFill}
          />
          <div className="h-5 w-px bg-border" />
          <StrokeRow
            activeWidth={selStyle.strokeWidth ?? DEFAULT_STROKE_WIDTH}
            dashed={selStyle.strokeStyle === "dashed"}
            onWidth={applyStrokeWidth}
            onStyle={applyStrokeStyle}
          />
          <div className="h-5 w-px bg-border" />
          <TextAlignRow active={selStyle.textAlign} onPick={applyTextAlign} />
          <div className="h-5 w-px bg-border" />
          <OpacityRow active={selStyle.opacity ?? 1} onPick={applyOpacity} />
        </div>
      ) : null}

      {/* Right-click context menu */}
      {menu ? (
        <>
          <button
            type="button"
            aria-label="关闭菜单"
            className="fixed inset-0 z-20 cursor-default"
            onClick={() => setMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu(null);
            }}
          />
          <div
            className="absolute z-30 min-w-40 rounded-xl border border-border bg-card p-1 shadow-lg"
            style={{ left: menu.x, top: menu.y }}
          >
            <MenuItem
              label="复制"
              hint="Ctrl+C"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.copySelection())}
            />
            <MenuItem
              label="粘贴"
              hint="Ctrl+V"
              onClick={() => runMenu((e) => e.paste())}
            />
            <MenuItem
              label="再制"
              hint="Ctrl+D"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.duplicateSelected())}
            />
            <MenuItem
              label="删除"
              hint="Delete"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.deleteSelected())}
            />
            <div className="my-1 h-px bg-border" />
            <AlignRow
              canAlign={selectionCount >= 2}
              canDistribute={selectionCount >= 3}
              run={runMenu}
            />
            <div className="my-1 h-px bg-border" />
            <MenuItem
              label="置顶"
              hint="Ctrl+]"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.bringToFront())}
            />
            <MenuItem
              label="上移一层"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.bringForward())}
            />
            <MenuItem
              label="下移一层"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.sendBackward())}
            />
            <MenuItem
              label="置底"
              hint="Ctrl+["
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.sendToBack())}
            />
            <div className="my-1 h-px bg-border" />
            <MenuItem
              label="编组"
              hint="Ctrl+G"
              disabled={selectionCount < 2}
              onClick={() => runMenu((e) => e.groupSelected())}
            />
            <MenuItem
              label="取消编组"
              hint="Ctrl+Shift+G"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.ungroupSelected())}
            />
            <div className="my-1 h-px bg-border" />
            {onOrganizeSelection ? (
              <MenuItem
                label="整理选区"
                disabled={selectionCount === 0 || aiBusy}
                onClick={() => {
                  setMenu(null);
                  onOrganizeSelection();
                }}
              />
            ) : null}
            {onImplementSelection && (selectionCount > 0 || selHasFrame) ? (
              <MenuItem
                label="让团队实现"
                disabled={selectionCount === 0 || aiBusy}
                onClick={() => {
                  setMenu(null);
                  onImplementSelection();
                }}
              />
            ) : null}
            {selHasArtifact ? (
              <>
                <MenuItem
                  label="复制产物正文"
                  onClick={() =>
                    runMenu((e) => {
                      const arts = e
                        .getScene()
                        .filter(
                          (el) =>
                            el.type === "artifactCard" &&
                            e.getSelectedIds().includes(el.id) &&
                            el.text,
                        );
                      const text = arts.map((a) => a.text).join("\n\n");
                      if (text) void navigator.clipboard.writeText(text);
                    })
                  }
                />
                <MenuItem
                  label="展开产物全文"
                  onClick={() =>
                    runMenu((e) => {
                      const art = e
                        .getScene()
                        .find(
                          (el) =>
                            el.type === "artifactCard" &&
                            e.getSelectedIds().includes(el.id),
                        );
                      if (art) onArtifactActivateRef.current?.(art);
                    })
                  }
                />
              </>
            ) : null}
            <div className="my-1 h-px bg-border" />
            <MenuItem
              label="网格布局"
              disabled={selectionCount < 2}
              onClick={() => runMenu((e) => e.layoutSelectedGrid())}
            />
            <MenuItem
              label="链路布局"
              disabled={selectionCount < 2}
              onClick={() => runMenu((e) => e.layoutSelectedDagre())}
            />
            <MenuItem
              label="导出选区 PNG"
              disabled={selectionCount === 0}
              onClick={() => runMenu(() => exportSelectionPng())}
            />
            <MenuItem
              label="缩放至选区"
              hint="Ctrl+2"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.zoomToSelection())}
            />
            <div className="my-1 h-px bg-border" />
            <MenuItem
              label="锁定"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.lockSelected())}
            />
            <MenuItem
              label="解锁"
              disabled={selectionCount === 0}
              onClick={() => runMenu((e) => e.unlockSelected())}
            />
            <MenuItem
              label="解锁全部"
              onClick={() => runMenu((e) => e.unlockAllOnBoard())}
            />
          </div>
        </>
      ) : null}
    </div>
  );
});
