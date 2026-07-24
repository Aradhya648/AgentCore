/**
 * 统一 UI 持久化层（对齐 VS Code storage service / Memento）。
 *
 * - 命名空间：所有 key 强制 `agentcore:` 冒号前缀
 * - 作用域：global（整机偏好）与 conversation（按对话）
 * - 值一律 JSON 序列化
 * - `#/preview` 离线回放（{@link isWebPreview}）自动切内存后端、不落盘
 * - 删除对话时走 {@link clearConversationUiState} 一次清干净该对话全部 UI 态
 *
 * 业务模块禁止直接碰 `localStorage`——见 lint 门禁 `check-no-localstorage.mjs`。
 */

import { isWebPreview } from "@/lib/preview";
import type { StateStorage } from "zustand/middleware";

export const UI_STORAGE_PREFIX = "agentcore:";

/** Conversation-scoped keys: `agentcore:c:{conversationId}:{leaf}`. */
const CONV_SEGMENT = "c:";

type Backend = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  keys(): string[];
};

const memoryStore = new Map<string, string>();

const memoryBackend: Backend = {
  getItem: (key) => memoryStore.get(key) ?? null,
  setItem: (key, value) => {
    memoryStore.set(key, value);
  },
  removeItem: (key) => {
    memoryStore.delete(key);
  },
  keys: () => [...memoryStore.keys()],
};

const localStorageBackend: Backend = {
  getItem: (key) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem: (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private mode / quota — session-only */
    }
  },
  removeItem: (key) => {
    try {
      localStorage.removeItem(key);
    } catch {
      /* unavailable */
    }
  },
  keys: () => {
    try {
      const out: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k) out.push(k);
      }
      return out;
    } catch {
      return [];
    }
  },
};

/** Test override — null restores the normal preview/localStorage selection. */
let backendOverride: Backend | null = null;

function getBackend(): Backend {
  if (backendOverride) return backendOverride;
  if (isWebPreview()) return memoryBackend;
  return localStorageBackend;
}

/** @internal vitest helper — swap backend or pass `null` to restore. */
export function __setUiStorageBackendForTests(backend: Backend | null): void {
  backendOverride = backend;
}

/** @internal vitest helper — wipe the in-memory preview store. */
export function __clearMemoryUiStorageForTests(): void {
  memoryStore.clear();
}

/** Ensure a storage key carries the `agentcore:` namespace. */
export function uiStorageKey(leaf: string): string {
  return leaf.startsWith(UI_STORAGE_PREFIX)
    ? leaf
    : `${UI_STORAGE_PREFIX}${leaf}`;
}

/** Build a per-conversation storage key. */
export function conversationStorageKey(
  conversationId: string,
  leaf: string,
): string {
  const clean = leaf.startsWith(UI_STORAGE_PREFIX)
    ? leaf.slice(UI_STORAGE_PREFIX.length)
    : leaf;
  return `${UI_STORAGE_PREFIX}${CONV_SEGMENT}${conversationId}:${clean}`;
}

function conversationKeyPrefix(conversationId: string): string {
  return `${UI_STORAGE_PREFIX}${CONV_SEGMENT}${conversationId}:`;
}

/** Read a JSON value from global (or any fully-qualified) scope. */
export function uiGet<T>(key: string): T | undefined {
  const raw = getBackend().getItem(uiStorageKey(key));
  if (raw == null) return undefined;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return undefined;
  }
}

/** Write a JSON value. Passing `undefined` removes the key. */
export function uiSet(key: string, value: unknown): void {
  const full = uiStorageKey(key);
  if (value === undefined) {
    getBackend().removeItem(full);
    return;
  }
  try {
    getBackend().setItem(full, JSON.stringify(value));
  } catch {
    /* unavailable — session-only */
  }
}

/** Remove a key. */
export function uiRemove(key: string): void {
  getBackend().removeItem(uiStorageKey(key));
}

/** Read a JSON value from conversation scope. */
export function conversationUiGet<T>(
  conversationId: string,
  leaf: string,
): T | undefined {
  return uiGet<T>(conversationStorageKey(conversationId, leaf));
}

/** Write a JSON value in conversation scope. */
export function conversationUiSet(
  conversationId: string,
  leaf: string,
  value: unknown,
): void {
  uiSet(conversationStorageKey(conversationId, leaf), value);
}

/** Remove a conversation-scoped key. */
export function conversationUiRemove(
  conversationId: string,
  leaf: string,
): void {
  uiRemove(conversationStorageKey(conversationId, leaf));
}

type ConversationClearer = (conversationId: string) => void;

const conversationClearers: ConversationClearer[] = [];

/**
 * Register a module-level clearer for conversation-scoped state that lives
 * inside a global blob (disclosure map, composer drafts, …). Called by
 * {@link clearConversationUiState}.
 */
export function registerConversationUiClearer(
  clearer: ConversationClearer,
): void {
  conversationClearers.push(clearer);
}

/**
 * Delete-conversation cleanup: drop every `agentcore:c:{id}:*` key, then run
 * registered blob-map clearers (disclosure / drafts / views / graph-fold / …).
 */
export function clearConversationUiState(conversationId: string): void {
  const prefix = conversationKeyPrefix(conversationId);
  for (const key of getBackend().keys()) {
    if (key.startsWith(prefix)) getBackend().removeItem(key);
  }
  for (const clearer of conversationClearers) clearer(conversationId);
}

/**
 * Zustand `persist` storage adapter — routes through this layer (preview →
 * memory; otherwise localStorage), and normalizes the persist `name` to the
 * `agentcore:` namespace.
 */
export function createZustandUiStorage(): StateStorage {
  return {
    getItem: (name) => getBackend().getItem(uiStorageKey(name)),
    setItem: (name, value) => {
      getBackend().setItem(uiStorageKey(name), value);
    },
    removeItem: (name) => {
      getBackend().removeItem(uiStorageKey(name));
    },
  };
}
