/**
 * 同对话 FIFO 排队项（live · turn_queued；进程内，重启丢）。
 * 对齐桌面 queuedTurns store 行为；手机端自建，不 import 桌面。
 */
import { useSyncExternalStore } from "react";

export interface QueuedTurnEntry {
  queueId: string;
  conversationId: string;
  /** 主时间线乐观用户气泡所在 turn id（取消时移除）。 */
  turnId: string;
  content: string;
  position: number;
  queueDepth: number;
  degradedFrom?: "steer";
}

type Listener = () => void;

let byConversation: Record<string, QueuedTurnEntry[]> = {};
const listeners = new Set<Listener>();

function emit(): void {
  for (const l of listeners) l();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Record<string, QueuedTurnEntry[]> {
  return byConversation;
}

export function upsertQueuedTurn(entry: QueuedTurnEntry): void {
  const prev = byConversation[entry.conversationId] ?? [];
  const without = prev.filter((e) => e.queueId !== entry.queueId);
  byConversation = {
    ...byConversation,
    [entry.conversationId]: [...without, entry].sort(
      (a, b) => a.position - b.position,
    ),
  };
  emit();
}

export function removeQueuedTurn(
  conversationId: string,
  queueId: string,
): QueuedTurnEntry | null {
  const prev = byConversation[conversationId] ?? [];
  const hit = prev.find((e) => e.queueId === queueId) ?? null;
  if (!hit) return null;
  const next = prev.filter((e) => e.queueId !== queueId);
  const copy = { ...byConversation };
  if (next.length === 0) delete copy[conversationId];
  else copy[conversationId] = next;
  byConversation = copy;
  emit();
  return hit;
}

export function clearQueuedTurns(conversationId: string): void {
  if (!byConversation[conversationId]) return;
  const copy = { ...byConversation };
  delete copy[conversationId];
  byConversation = copy;
  emit();
}

export function listQueuedTurns(
  conversationId: string | null | undefined,
): QueuedTurnEntry[] {
  return conversationId ? (byConversation[conversationId] ?? []) : [];
}

const EMPTY: QueuedTurnEntry[] = [];

/** React 订阅：同对话 FIFO 排队项。 */
export function useQueuedTurns(
  conversationId: string | null | undefined,
): QueuedTurnEntry[] {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  if (!conversationId) return EMPTY;
  return snap[conversationId] ?? EMPTY;
}

/** 测试用：重置全部排队态。 */
export function __resetQueuedTurnsForTests(): void {
  byConversation = {};
  emit();
}
