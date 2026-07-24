/**
 * Interpret a batch of AI `board_ops` into scene mutations (AI协作白板.md §六/§十 M2).
 *
 * Mirrors the closed verb set shared with the server tool + applier: `add_node`,
 * `connect`, `move`, `set_text`, `delete`, `group`. Pure — returns a NEW element array
 * (the engine snapshots history, then swaps it in) plus the ids created this batch.
 */

import type { BoardOp } from "@/types/events";
import { cloneElement } from "./clone";
import {
  type ElementType,
  SCENE_SCHEMA_VERSION,
  type SceneElement,
} from "./types";

const NODE_W = 180;
const NODE_H = 90;
const TEXT_FONT = 20;

function newId(): string {
  return `brd-${crypto.randomUUID()}`;
}

// (deep clone moved to ./clone — shared with history + clipboard)

/** Tidy 4-wide cascade for nodes that omit explicit coordinates. */
function autoPos(index: number): { x: number; y: number } {
  const col = index % 4;
  const row = Math.floor(index / 4);
  return { x: 120 + col * 240, y: 120 + row * 170 };
}

export function applyBoardOps(
  current: readonly SceneElement[],
  ops: readonly BoardOp[],
): { elements: SceneElement[]; created: string[] } {
  const elements = current.map(cloneElement);
  const byId = new Map(elements.map((e) => [e.id, e]));
  const refToId = new Map<string, string>();
  const created: string[] = [];
  let nodeIndex = 0;

  // 1) add_node
  for (const op of ops) {
    if (op.op !== "add_node") continue;
    const id = newId();
    created.push(id);
    if (op.ref) refToId.set(op.ref, id);
    const pos = {
      x: op.x ?? autoPos(nodeIndex).x,
      y: op.y ?? autoPos(nodeIndex).y,
    };
    nodeIndex++;
    const kind = op.kind || "sticky";
    let el: SceneElement;
    if (kind === "text") {
      const text = op.text ?? "";
      el = {
        id,
        type: "text",
        x: pos.x,
        y: pos.y,
        width: Math.max(40, text.length * TEXT_FONT * 0.6),
        height: TEXT_FONT * 1.4,
        text,
        stroke: op.color,
        fontSize: TEXT_FONT,
        schemaVersion: SCENE_SCHEMA_VERSION,
      };
    } else {
      const type = (kind === "sticky" ? "sticky" : kind) as ElementType;
      el = {
        id,
        type,
        x: pos.x,
        y: pos.y,
        width: op.width ?? NODE_W,
        height: op.height ?? NODE_H,
        text: op.text,
        fill: op.color,
        schemaVersion: SCENE_SCHEMA_VERSION,
      };
    }
    elements.push(el);
    byId.set(id, el);
  }

  const resolve = (key: string): string | null =>
    refToId.get(key) ?? (byId.has(key) ? key : null);

  // 2) connect (arrow bound to both endpoints)
  for (const op of ops) {
    if (op.op !== "connect" || !op.from || !op.to) continue;
    const from = resolve(op.from);
    const to = resolve(op.to);
    if (!from || !to) continue;
    const id = newId();
    const arrow: SceneElement = {
      id,
      type: "arrow",
      x: 0,
      y: 0,
      width: 0,
      height: 0,
      start: { id: from },
      end: { id: to },
      text: op.label,
      schemaVersion: SCENE_SCHEMA_VERSION,
    };
    elements.push(arrow);
    byId.set(id, arrow);
  }

  // 3) move / set_text / delete (target an existing id or a same-batch ref)
  const deleted = new Set<string>();
  for (const op of ops) {
    const key = op.id ?? op.ref;
    const target = key ? resolve(key) : null;
    if (!target) continue;
    const el = byId.get(target);
    if (!el) continue;
    if (op.op === "delete") {
      deleted.add(target);
    } else if (op.op === "move") {
      if (typeof op.x === "number") el.x = op.x;
      if (typeof op.y === "number") el.y = op.y;
    } else if (op.op === "set_text") {
      el.text = op.text ?? "";
    }
  }

  // 4) group
  let seq = 0;
  for (const op of ops) {
    if (op.op !== "group" || !op.members?.length) continue;
    const groupId = `grp-${Date.now()}-${seq++}`;
    for (const member of op.members) {
      const el = byId.get(resolve(member) ?? member);
      if (el) el.groupIds = [...(el.groupIds ?? []), groupId];
    }
  }

  // Drop deleted elements, then dangling arrows whose endpoint vanished.
  const survivors = elements.filter((e) => !deleted.has(e.id));
  const alive = new Set(survivors.map((e) => e.id));
  const pruned = survivors.filter(
    (e) =>
      e.type !== "arrow" ||
      ((!e.start?.id || alive.has(e.start.id)) &&
        (!e.end?.id || alive.has(e.end.id))),
  );
  return { elements: pruned, created };
}
