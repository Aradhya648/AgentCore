/**
 * Undo/redo as a snapshot stack (AI协作白板.md §六「统一 command/transaction 模型承载
 * undo」). For the MVP each committed mutation snapshots the whole element array — simple
 * and robust; if scenes grow large this can move to per-op inverse commands without
 * changing the engine's call sites.
 */

import { cloneElements } from "./clone";
import type { SceneElement } from "./types";

export class History {
  private past: SceneElement[][] = [];
  private future: SceneElement[][] = [];

  constructor(private readonly limit = 100) {}

  /** Record state BEFORE a mutation. Clears the redo stack. */
  push(snapshot: readonly SceneElement[]): void {
    this.past.push(cloneElements(snapshot));
    if (this.past.length > this.limit) this.past.shift();
    this.future = [];
  }

  canUndo(): boolean {
    return this.past.length > 0;
  }

  canRedo(): boolean {
    return this.future.length > 0;
  }

  /** Returns the previous snapshot to restore, pushing `current` onto redo. */
  undo(current: readonly SceneElement[]): SceneElement[] | null {
    const prev = this.past.pop();
    if (!prev) return null;
    this.future.push(cloneElements(current));
    return prev;
  }

  redo(current: readonly SceneElement[]): SceneElement[] | null {
    const next = this.future.pop();
    if (!next) return null;
    this.past.push(cloneElements(current));
    return next;
  }

  clear(): void {
    this.past = [];
    this.future = [];
  }
}
