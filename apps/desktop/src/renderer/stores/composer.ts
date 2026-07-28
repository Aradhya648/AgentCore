import type { PendingAttachment } from "@/components/chat/message-input/composerAttachments";
import { registerConversationUiClearer, uiGet, uiSet } from "@/lib/uiStorage";
import { useConversationStore } from "@/stores/conversation";
import type { SetStateAction } from "react";
import { create } from "zustand";

/**
 * Per-conversation drafts for the unified turn composer (`TurnComposer` — the chat
 * `MessageInput` and the canvas `CanvasCommandBar` are two skins over the same core).
 *
 * Keying the draft (text + pending attachments) by conversation moves it OUT of
 * component state, which buys the two things the old local-state design couldn't do:
 * switching 聊天 ⇄ 画布 (which unmounts one skin and mounts the other) keeps the
 * half-typed order, and the 回填 channel below lands in a real draft even if the
 * subscribing composer is briefly unmounted. Entries self-delete once both text and
 * attachments are empty, so the map stays bounded to conversations with a live draft.
 *
 * Persistence: draft TEXT + attachment *metadata* survive an app restart
 * (`uiStorage`, debounced + flushed on unload, capped to the {@link PERSIST_LIMIT}
 * most recent). Binary bytes stay on disk under main-process ``attach-staging``
 * (indexed by ``stagingId``); we never put file bytes into localStorage. Preview
 * ``text`` is truncated for the quota; stale staging is honest at send time.
 *
 * 回填 channel: follow-up chips / 下一步推荐 (non-blocking ask no longer writes chips)
 * chip ({@link FollowupChips}) drops its pick into the ACTIVE conversation's draft via
 * {@link fill}. `append` (the default) adds the text as a new line after any existing
 * draft so a user can stack answers to several questions; `replace` overwrites.
 * `fillToken` is a monotonic focus hint — the mounted composer refocuses its textarea
 * when it changes (the draft text itself arrives through the store subscription).
 */
export interface ComposerDraft {
  value: string;
  attachments: PendingAttachment[];
  /** Last edit (ms epoch) — recency key for the persistence cap. */
  updatedAt: number;
}

const EMPTY_DRAFT: ComposerDraft = { value: "", attachments: [], updatedAt: 0 };

const COMPOSER_DRAFTS_KEY = "composer-drafts";
/** Persist at most this many drafts (most recently edited win). */
const PERSIST_LIMIT = 30;
const PERSIST_DEBOUNCE_MS = 300;
/** Cap attachment metadata per draft so ``composer-drafts`` stays bounded. */
const PERSIST_ATTACH_MAX = 8;
/** Truncate preview text when writing to uiStorage (full preview stays in-memory). */
const PERSIST_ATTACH_TEXT_CAP = 8 * 1024;

/** Draft-conversation (no id yet) drafts live under a fixed sentinel key. */
export function draftKeyFor(conversationId: string | null): string {
  return conversationId ?? "__draft__";
}

function sanitizeAttachment(raw: unknown): PendingAttachment | null {
  if (!raw || typeof raw !== "object") return null;
  const a = raw as Record<string, unknown>;
  if (typeof a.id !== "string" || !a.id) return null;
  if (typeof a.key !== "string" || !a.key) return null;
  if (typeof a.name !== "string" || !a.name) return null;
  if (typeof a.path !== "string") return null;
  if (typeof a.text !== "string") return null;
  if (typeof a.truncated !== "boolean") return null;
  if (
    a.kind !== "file" &&
    a.kind !== "dir" &&
    a.kind !== "conversation"
  ) {
    return null;
  }
  const out: PendingAttachment = {
    id: a.id,
    key: a.key,
    name: a.name,
    path: a.path,
    text: a.text,
    truncated: a.truncated,
    kind: a.kind,
  };
  if (typeof a.conversationId === "string")
    out.conversationId = a.conversationId;
  if (typeof a.workspacePath === "string") out.workspacePath = a.workspacePath;
  if (typeof a.stagingId === "string") out.stagingId = a.stagingId;
  if (typeof a.binary === "boolean") out.binary = a.binary;
  return out;
}

function serializeAttachments(
  attachments: PendingAttachment[],
): PendingAttachment[] {
  return attachments.slice(0, PERSIST_ATTACH_MAX).map((a) => {
    const text =
      a.text.length > PERSIST_ATTACH_TEXT_CAP
        ? a.text.slice(0, PERSIST_ATTACH_TEXT_CAP)
        : a.text;
    const out: PendingAttachment = {
      id: a.id,
      key: a.key,
      name: a.name,
      path: a.path,
      text,
      truncated: a.truncated || a.text.length > PERSIST_ATTACH_TEXT_CAP,
      kind: a.kind,
    };
    if (a.conversationId) out.conversationId = a.conversationId;
    if (a.workspacePath) out.workspacePath = a.workspacePath;
    if (a.stagingId) out.stagingId = a.stagingId;
    if (a.binary) out.binary = a.binary;
    return out;
  });
}

function draftHasContent(d: Pick<ComposerDraft, "value" | "attachments">): boolean {
  return Boolean(d.value) || d.attachments.length > 0;
}

function loadDrafts(): Record<string, ComposerDraft> {
  const parsed = uiGet<Record<string, unknown>>(COMPOSER_DRAFTS_KEY);
  if (!parsed || typeof parsed !== "object") return {};
  const out: Record<string, ComposerDraft> = {};
  for (const [key, entry] of Object.entries(parsed)) {
    if (!entry || typeof entry !== "object") continue;
    const { value, updatedAt, attachments: rawAtts } = entry as {
      value?: unknown;
      updatedAt?: unknown;
      attachments?: unknown;
    };
    const valueStr = typeof value === "string" ? value : "";
    const attachments = Array.isArray(rawAtts)
      ? rawAtts
          .map(sanitizeAttachment)
          .filter((a): a is PendingAttachment => a !== null)
          .slice(0, PERSIST_ATTACH_MAX)
      : [];
    if (!valueStr && attachments.length === 0) continue;
    out[key] = {
      value: valueStr,
      attachments,
      updatedAt: typeof updatedAt === "number" ? updatedAt : 0,
    };
  }
  return out;
}

function persistDrafts(drafts: Record<string, ComposerDraft>): void {
  const entries = Object.entries(drafts)
    .filter(([, d]) => draftHasContent(d))
    .sort(([, a], [, b]) => b.updatedAt - a.updatedAt)
    .slice(0, PERSIST_LIMIT)
    .map(([key, d]) => {
      const payload: {
        value: string;
        updatedAt: number;
        attachments?: PendingAttachment[];
      } = { value: d.value, updatedAt: d.updatedAt };
      if (d.attachments.length > 0) {
        payload.attachments = serializeAttachments(d.attachments);
      }
      return [key, payload] as const;
    });
  if (entries.length === 0) uiSet(COMPOSER_DRAFTS_KEY, undefined);
  else uiSet(COMPOSER_DRAFTS_KEY, Object.fromEntries(entries));
}

function resolve<T>(action: SetStateAction<T>, prev: T): T {
  return typeof action === "function" ? (action as (p: T) => T)(prev) : action;
}

/** Write back a draft, dropping the key when it emptied (bounded map). */
function write(
  drafts: Record<string, ComposerDraft>,
  key: string,
  next: ComposerDraft,
): Record<string, ComposerDraft> {
  const out = { ...drafts };
  if (!draftHasContent(next)) delete out[key];
  else out[key] = next;
  return out;
}

interface ComposerDraftState {
  drafts: Record<string, ComposerDraft>;
  /** Monotonic; bumped on every {@link fill} so the mounted composer refocuses. */
  fillToken: number;
  /**
   * Monotonic; bumped ONLY when a draft promotes to a brand-new conversation on
   * first send ({@link armDockFlip}). The composer dock-flip animation (center →
   * bottom) keys off this instead of the passive centered→bottom transition, so
   * merely SWITCHING to another (already-persisted) conversation never triggers
   * the flight animation — that transition looked like "输入框跳动".
   */
  dockFlipToken: number;
  setValue: (key: string, action: SetStateAction<string>) => void;
  setAttachments: (
    key: string,
    action: SetStateAction<PendingAttachment[]>,
  ) => void;
  /** 回填 the active conversation's draft with `text` (default: append as a new line). */
  fill: (text: string, mode?: "append" | "replace") => void;
  /** Arm the one-shot center→bottom dock-flip for the imminent first-send promote. */
  armDockFlip: () => void;
}

export const useComposerDraftStore = create<ComposerDraftState>((set) => ({
  drafts: loadDrafts(),
  fillToken: 0,
  dockFlipToken: 0,
  setValue: (key, action) =>
    set((s) => {
      const prev = s.drafts[key] ?? EMPTY_DRAFT;
      return {
        drafts: write(s.drafts, key, {
          ...prev,
          value: resolve(action, prev.value),
          updatedAt: Date.now(),
        }),
      };
    }),
  setAttachments: (key, action) =>
    set((s) => {
      const prev = s.drafts[key] ?? EMPTY_DRAFT;
      return {
        drafts: write(s.drafts, key, {
          ...prev,
          attachments: resolve(action, prev.attachments),
          updatedAt: Date.now(),
        }),
      };
    }),
  fill: (text, mode = "append") =>
    set((s) => {
      const key = draftKeyFor(
        useConversationStore.getState().currentConversationId,
      );
      const prev = s.drafts[key] ?? EMPTY_DRAFT;
      const value =
        mode === "append" && prev.value.trim()
          ? `${prev.value}\n${text}`
          : text;
      return {
        drafts: write(s.drafts, key, { ...prev, value, updatedAt: Date.now() }),
        fillToken: s.fillToken + 1,
      };
    }),
  armDockFlip: () => set((s) => ({ dockFlipToken: s.dockFlipToken + 1 })),
}));

// Debounced persistence: setValue fires per keystroke, so batch writes; flush on
// unload so the last keystrokes before closing the app aren't lost to the debounce.
let persistTimer: ReturnType<typeof setTimeout> | null = null;
let lastPersisted: Record<string, ComposerDraft> | null = null;

function flushPersist(): void {
  if (persistTimer !== null) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
  const drafts = useComposerDraftStore.getState().drafts;
  if (drafts === lastPersisted) return;
  lastPersisted = drafts;
  persistDrafts(drafts);
}

useComposerDraftStore.subscribe((s, prev) => {
  if (s.drafts === prev.drafts) return;
  if (persistTimer !== null) clearTimeout(persistTimer);
  persistTimer = setTimeout(flushPersist, PERSIST_DEBOUNCE_MS);
});

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", flushPersist);
}

registerConversationUiClearer((conversationId) => {
  const key = draftKeyFor(conversationId);
  const drafts = useComposerDraftStore.getState().drafts;
  if (!(key in drafts)) return;
  const next = { ...drafts };
  delete next[key];
  useComposerDraftStore.setState({ drafts: next });
  persistDrafts(next);
  lastPersisted = next;
});

/** @internal vitest — reload drafts from uiStorage without `vi.resetModules` (hangs on the conversation graph). */
export function __reloadComposerDraftsForTests(): void {
  if (persistTimer !== null) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
  lastPersisted = null;
  useComposerDraftStore.setState({
    drafts: loadDrafts(),
    fillToken: 0,
    dockFlipToken: 0,
  });
}
