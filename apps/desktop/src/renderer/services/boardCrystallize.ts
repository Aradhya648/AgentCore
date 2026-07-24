import type { Execution, RunNode } from "@/stores/execution";
import { SCENE_SCHEMA_VERSION, type SceneElement } from "@/whiteboard";
import {
  type OverlayAnchor,
  runStatusLabel,
  runVisualStatus,
} from "./boardProgress";

/**
 * Crystallize a finished team run tree into PERSISTENT board elements (AI协作白板.md §十 M3
 * Slice 3 产物回贴).
 *
 * The live overlay ({@link buildProgressOverlay}) is a throwaway layer that vanishes when the
 * run store changes; this is its terminal counterpart — when a turn ends, its team becomes real
 * scene content (serialized + autosaved + undoable) so the board keeps a record of who did what
 * and what they produced. The host appends the result through `WhiteboardApi.addElements` and
 * clears the overlay (§四.3 持久化策略: live = overlay, done = crystallize, one CAS save).
 *
 * Pure & deterministic. For each delegated worker run that reached a terminal状态 it mints a
 * status-colored `agentNode`; a `completed` run that carried an `outputSummary` also gets an
 * `artifactCard` (the text product, v1) connected to its node by a bound arrow. A single
 * provenance arrow ties the cluster back to the launching brief (持久贴源 / 照这实现).
 *
 * Idempotent via `existingRunIds` (the run ids already crystallized on the board): a run already
 * present is skipped, so re-firing on a later fold — or a follow-up iteration turn (Slice 4)
 * that appends NEW runs to the same conversation — never duplicates. Returns `[]` when there is
 * nothing new to add (no team, or every worker already crystallized).
 */

const NODE_W = 184;
const NODE_H = 56;
const ART_W = 248;
const ART_H = 132;
/** Horizontal breathing room between the brief's right edge and the team column. */
const GAP_X = 96;
/** Gap between an `agentNode` and its `artifactCard` (left→right: brief → agent → product). */
const GAP_NODE_ART = 40;
/** Vertical gap between worker rows. */
const GAP_Y = 24;

/** Pick the primary workspace file path to surface on an artifact card — last written wins
 * (typical final deliverable ordering in files_touched). */
export function primaryOutputFile(files: readonly string[]): string | null {
  const trimmed = files.map((p) => p.trim()).filter(Boolean);
  return trimmed.length > 0 ? trimmed[trimmed.length - 1] : null;
}

function fileBaseName(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

/** Map a completed worker run to artifact card fields (pure — unit-tested). */
export function artifactFromRun(run: {
  outputSummary?: string | null;
  outputFiles?: readonly string[];
}): {
  kind: "text" | "file";
  body: string;
  titleSuffix: string;
  ref?: string;
} | null {
  const summary = run.outputSummary?.trim() ?? "";
  const ref = primaryOutputFile(run.outputFiles ?? []);
  if (ref) {
    const name = fileBaseName(ref);
    return {
      kind: "file",
      body: summary || name,
      titleSuffix: name,
      ref,
    };
  }
  if (summary) {
    return { kind: "text", body: summary, titleSuffix: "产物" };
  }
  return null;
}

function isWorkerRun(run: RunNode): boolean {
  return run.kind !== "captain";
}

/** A worker worth persisting: a delegated run that finished. `completed` carries a product;
 * `failed` is kept as a red node so the board shows what broke; `cancelled` / unfinished runs
 * are skipped (a stopped turn shouldn't litter the board with ghost cards). */
function isCrystallizable(run: RunNode): boolean {
  return (
    isWorkerRun(run) && (run.status === "completed" || run.status === "failed")
  );
}

export function buildCrystallizedElements(
  execution: Execution,
  anchor: OverlayAnchor,
  existingRunIds: ReadonlySet<string>,
): SceneElement[] {
  const roleByAgent = new Map(execution.agents.map((a) => [a.id, a.role]));
  const workers = execution.runs.filter(
    (r) => isCrystallizable(r) && !existingRunIds.has(r.id),
  );
  if (workers.length === 0) return [];

  const nodeX = anchor.x + anchor.width + GAP_X;
  const artX = nodeX + NODE_W + GAP_NODE_ART;
  const out: SceneElement[] = [];
  let y = anchor.y;
  let first = true;

  for (const run of workers) {
    const role = roleByAgent.get(run.agentId) ?? run.task ?? run.agentId;
    const status = runVisualStatus(run.status);
    const rowH = Math.max(NODE_H, ART_H);
    const nodeY = y + (rowH - NODE_H) / 2;
    const nodeId = `crys-node-${run.id}`;

    out.push({
      id: nodeId,
      type: "agentNode",
      x: nodeX,
      y: nodeY,
      width: NODE_W,
      height: NODE_H,
      text: `${role}\n${runStatusLabel(run.status)}`,
      role,
      runId: run.id,
      runStatus: status,
      schemaVersion: SCENE_SCHEMA_VERSION,
    });

    // Only a completed worker yields a product card; a failed one leaves just its red node.
    const artifact = run.status === "completed" ? artifactFromRun(run) : null;
    if (artifact) {
      const artId = `crys-art-${run.id}`;
      const artY = y + (rowH - ART_H) / 2;
      out.push({
        id: artId,
        type: "artifactCard",
        x: artX,
        y: artY,
        width: ART_W,
        height: ART_H,
        title: `${role} · ${artifact.titleSuffix}`,
        text: artifact.body,
        artifactKind: artifact.kind,
        ref: artifact.ref,
        runId: run.id,
        runStatus: status,
        schemaVersion: SCENE_SCHEMA_VERSION,
      });
      // node → artifact connector (bound both ends, so moving either reroutes).
      out.push({
        id: `crys-link-${run.id}`,
        type: "arrow",
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        start: { id: nodeId },
        end: { id: artId },
        points: [
          [nodeX + NODE_W, nodeY + NODE_H / 2],
          [artX, artY + ART_H / 2],
        ],
        schemaVersion: SCENE_SCHEMA_VERSION,
      });
    }

    // One provenance arrow from the first node back to the brief's right edge (持久贴源). The
    // brief is a free-form selection (no single element id), so the brief end stays unbound.
    if (first) {
      out.push({
        id: `crys-src-${execution.id}`,
        type: "arrow",
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        start: { id: nodeId },
        points: [
          [nodeX, nodeY + NODE_H / 2],
          [anchor.x + anchor.width, anchor.y + anchor.height / 2],
        ],
        schemaVersion: SCENE_SCHEMA_VERSION,
      });
      first = false;
    }

    y += rowH + GAP_Y;
  }

  return out;
}

/** Collect the run ids already crystallized on a scene — the dedupe set
 * {@link buildCrystallizedElements} consumes so a re-fire / iteration never duplicates cards. */
export function crystallizedRunIds(
  elements: readonly SceneElement[],
): Set<string> {
  const ids = new Set<string>();
  for (const el of elements) {
    if (el.runId) ids.add(el.runId);
  }
  return ids;
}
