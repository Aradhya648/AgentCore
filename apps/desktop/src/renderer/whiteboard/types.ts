/**
 * Self-built whiteboard engine — scene model (AI协作白板.md §六 自研引擎架构).
 *
 * Geometry is in WORLD coordinates; the {@link Viewport} maps world→screen at render
 * time. `SceneElement` is a pragmatic single interface keyed by `type` (the doc's
 * discriminated-union target — kept as one shape for the MVP skeleton so the renderer
 * and hit-test stay compact; tighten into a strict union as the shape set grows).
 *
 * `schemaVersion` is the per-element migration 后悔药 (§六/§七): bump + migrate when an
 * element's fields change so an old persisted scene never silently misreads.
 */

export const SCENE_FORMAT = "agentcore-board";
export const SCENE_SCHEMA_VERSION = 1;

/** Outline thickness presets (world units) offered by the style panel; the renderer falls
 * back to {@link DEFAULT_STROKE_WIDTH} when an element has none. */
export const STROKE_WIDTHS = [2, 4, 7] as const;
export const DEFAULT_STROKE_WIDTH = 2;

export type StrokeStyle = "solid" | "dashed";
export type TextAlign = "left" | "center" | "right";

/** A delegated run's lifecycle status as the board renders it (AI协作白板 M3 进度贴源). A
 * whiteboard-local mirror of the execution store's `RunStatus`
 * so the engine stays independent of the run store; drives the `agentNode` card's status accent
 * (running→primary, completed→success, failed→destructive, pending/cancelled/skipped→muted). */
export type RunVisualStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type ElementType =
  | "rectangle"
  | "ellipse"
  | "diamond"
  | "sticky"
  | "text"
  | "freedraw"
  | "image"
  | "arrow"
  | "line"
  | "frame"
  // AgentCore-native shapes (护城河第一公民, §五.1) — reserved; rendered as labeled
  // cards for now, wired to runs in M3.
  | "agentNode"
  | "artifactCard";

export interface SceneElement {
  id: string;
  type: ElementType;
  /** Top-left corner (world). For `freedraw`/`arrow` it is the points' bbox origin. */
  x: number;
  y: number;
  width: number;
  height: number;
  /** Label / text body (the `text` element uses it as its content). */
  text?: string;
  /** Explicit CSS color (e.g. AI-supplied); omit = theme-default per type at render. */
  fill?: string;
  stroke?: string;
  /** Outline thickness in world units; omit = renderer default ({@link DEFAULT_STROKE_WIDTH}). */
  strokeWidth?: number;
  /** Outline style; omit = solid. `dashed` strokes the shape (arrowheads stay solid). */
  strokeStyle?: StrokeStyle;
  fontSize?: number;
  /** freedraw: points RELATIVE to (x,y). arrow: absolute world points (used when unbound). */
  points?: Array<[number, number]>;
  /** Horizontal alignment of a `text` element's lines (omit = left). */
  textAlign?: TextAlign;
  /** image: the picture as a data URL (base64 PNG/JPEG), downscaled on import. Like 手绘,
   * its meaning lives in pixels → read via vision (board_read, §九 混合 payload). */
  src?: string;
  /** Clockwise rotation in radians about the element's box center (omit = 0). Linear
   * elements (`arrow`/`line`) and `freedraw` are not rotated (their geometry is the points).
   * Exposed via the rotation handle above a single selection (WB-007). */
  rotation?: number;
  /** Whole-element opacity 0..1 (omit = 1). */
  opacity?: number;
  /** Locked elements ignore pointer hit-testing / marquee / move / resize / delete until
   * unlocked (right-click →「解锁」or「解锁全部」). */
  locked?: boolean;
  /** arrow/line endpoint bindings (element ids) — endpoints computed from the bound elements. */
  start?: { id?: string };
  end?: { id?: string };
  groupIds?: string[];
  /** AI协作白板 M3 进度贴源: on an `agentNode` card, the tracked run's lifecycle status —
   * drives the status accent + dot. Set on the live-progress overlay layer (a delegated
   * worker run → one card) and, once a run completes, on its crystallized `agentNode`. */
  runStatus?: RunVisualStatus;
  /** AI协作白板 M3 产物回贴 (Slice 3): the delegated run a crystallized card was minted from.
   * The dedupe key (re-crystallizing a finished run is a no-op) + the future「@ 回工作区」handle.
   * Set on persistent `agentNode` / `artifactCard` elements written when a team turn ends;
   * absent on user-drawn shapes and on the throwaway live overlay. */
  runId?: string;
  /** The delegated worker's role, on a crystallized `agentNode` — a structured copy of what its
   * `text` shows (lets a later pass re-style without re-parsing the label). */
  role?: string;
  /** On a crystallized `artifactCard`, the kind of product it carries: `text` = an inline output
   * summary (v1, from the run's `outputSummary`); `file` = a workspace file (reserved for when a
   * file signal reaches the client). */
  artifactKind?: "text" | "file";
  /** On a `file` {@link artifactKind} card, the workspace path / id the「@ 回工作区」affordance
   * opens (母文 §八 产物回贴接缝). Absent for text products. */
  ref?: string;
  /** Heading of a crystallized `artifactCard` (role + 产物), kept distinct from `text` (the body)
   * so the renderer can weight them differently. */
  title?: string;
  schemaVersion: number;
}

/** screen = world * zoom + pan (pan in CSS px). */
export interface Viewport {
  panX: number;
  panY: number;
  zoom: number;
}

/** The opaque scene blob we persist to `boards.scene` (our own format, not Excalidraw). */
export interface BoardScenePayload {
  format: string;
  schemaVersion: number;
  elements: SceneElement[];
  appState?: { viewport?: Viewport };
}

export type Tool =
  | "select"
  | "hand"
  | "rectangle"
  | "ellipse"
  | "diamond"
  | "sticky"
  | "text"
  | "freedraw"
  | "arrow"
  | "line"
  | "frame"
  | "eraser";

export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 8;

/** Imperative handle the host (WhiteboardCanvasPage) drives — the engine's public API. */
export interface WhiteboardApi {
  getScene(): SceneElement[];
  getViewport(): Viewport;
  getSelectedIds(): string[];
  /** Bounding box (world) of the current selection, or null if nothing is selected. The host
   * anchors the M3 live-progress overlay (进度贴源) beside this. */
  getSelectionBounds(): {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  /** Replace the transient AI-progress overlay layer (M3 进度贴源): cards drawn ON TOP of the
   * scene that live entirely outside it — never serialized, never in history, never hit-tested.
   * The host rebuilds them from the live run tree each tick; pass `[]` to clear. */
  setOverlay(elements: SceneElement[]): void;
  /** Append persistent elements to the scene as ONE history step (M3 产物回贴 crystallize): when
   * a team turn ends, its `agentNode` / `artifactCard` cards land in the real scene (unlike the
   * throwaway {@link setOverlay} layer) so they serialize + autosave + undo. No-op for `[]`. */
  addElements(elements: SceneElement[]): void;
  /** Rasterize a subset of elements to a PNG for the AI's vision reader (board_read, §九). */
  rasterizeElements(ids: string[]): { pngBase64: string; w: number; h: number };
  /** Apply a batch of AI board ops; returns the ids created this batch (in op order). */
  applyOps(ops: import("@/types/events").BoardOp[]): { created: string[] };
  undo(): void;
  redo(): void;
  deleteSelected(): void;
  zoomIn(): void;
  zoomOut(): void;
  zoomToFit(): void;
  zoomToSelection(): void;
  resetZoom(): void;
  exportSelectionPng(): void;
}
