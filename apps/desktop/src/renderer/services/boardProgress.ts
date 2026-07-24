import {
  type Execution,
  type ExecutionStatus,
  type RunStatus,
  executionStatusLabel,
  runStatusLabel,
} from "@/stores/execution";
import {
  type RunVisualStatus,
  SCENE_SCHEMA_VERSION,
  type SceneElement,
} from "@/whiteboard";

export { runStatusLabel };

/**
 * Project a live team run tree into the board's transient progress overlay (AI协作白板.md §十
 * M3 Slice 2 进度贴源).
 *
 * Pure & deterministic: a {@link Execution} (the same fold the chat team graph reads) + the
 * brief anchor (the launching selection / `frame` bbox) → a flat list of overlay
 * {@link SceneElement}s the engine draws ON TOP of the scene (never serialized / never in
 * history). One `agentNode` card per run, status-colored, laid out in a column beside the
 * anchor, with a connector arrow pointing back at the brief ("贴源"). The host re-runs this on
 * every frame the execution mutates and hands the result to `WhiteboardApi.setOverlay`.
 *
 * Decoupled from persistence by design (M3 §四.3): live progress is a throwaway overlay, so
 * this never touches the scene — only on run completion does Slice 3 crystallize persistent
 * `agentNode` / `artifactCard` elements.
 */

/** The launching brief's bounding box (world) the overlay anchors beside. */
export interface OverlayAnchor {
  x: number;
  y: number;
  width: number;
  height: number;
}

const CARD_W = 184;
const CARD_H = 56;
const HEADER_H = 40;
const GAP_Y = 14;
/** Horizontal breathing room between the brief's right edge and the team column. */
const GAP_X = 96;

/** Map the execution store's {@link RunStatus} onto the engine's {@link RunVisualStatus}.
 * Shared with the Slice 3 crystallizer so a live overlay card and its persisted twin
 * read the same status color. */
export function runVisualStatus(status: RunStatus): RunVisualStatus {
  switch (status) {
    case "running":
      return "running";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    case "skipped":
      return "cancelled"; // muted「未执行」— engine has no skipped chip; reuse cancelled tone
    default:
      return "pending";
  }
}

function execVisualStatus(status: ExecutionStatus): RunVisualStatus {
  switch (status) {
    case "running":
      return "running";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return "pending";
  }
}

/**
 * Build the overlay element list for a live execution anchored to a brief box.
 *
 * Returns `[]` when there is no team to show (no runs) so the host clears the layer. The first
 * element is a header card ("团队 · {status}"), followed by one status card per run; a single
 * connector arrow runs from the header back to the brief's right edge.
 */
export function buildProgressOverlay(
  execution: Execution,
  anchor: OverlayAnchor,
): SceneElement[] {
  const runs = execution.runs;
  if (runs.length === 0) return [];

  const roleByAgent = new Map(execution.agents.map((a) => [a.id, a.role]));
  const colX = anchor.x + anchor.width + GAP_X;
  const out: SceneElement[] = [];

  // Header — the team summary, and the connector arrow's source.
  const headerY = anchor.y;
  out.push({
    id: "ovl-header",
    type: "agentNode",
    x: colX,
    y: headerY,
    width: CARD_W,
    height: HEADER_H,
    text: `团队 · ${executionStatusLabel(execution.status)}`,
    runStatus: execVisualStatus(execution.status),
    schemaVersion: SCENE_SCHEMA_VERSION,
  });

  // Connector arrow: header → brief (head at the brief, so it reads as "贴源 / 照这实现").
  out.push({
    id: "ovl-link",
    type: "arrow",
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    points: [
      [colX, headerY + HEADER_H / 2],
      [anchor.x + anchor.width, anchor.y + anchor.height / 2],
    ],
    schemaVersion: SCENE_SCHEMA_VERSION,
  });

  // One card per run, stacked below the header.
  let y = headerY + HEADER_H + GAP_Y;
  for (const run of runs) {
    const role = roleByAgent.get(run.agentId) ?? run.task ?? run.agentId;
    out.push({
      id: `ovl-run-${run.id}`,
      type: "agentNode",
      x: colX,
      y,
      width: CARD_W,
      height: CARD_H,
      text: `${role}\n${runStatusLabel(run.status)}`,
      runStatus: runVisualStatus(run.status),
      schemaVersion: SCENE_SCHEMA_VERSION,
    });
    y += CARD_H + GAP_Y;
  }

  return out;
}
