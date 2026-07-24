/**
 * Main-process outbox writebacker (as-built: 双模式工作区 §10.3 / §10.4; 前端技术 §7.2).
 *
 * Reads sidecar outbox JSON under `<userData>/sidecar/outbox/`, POSTs ready
 * records to `/v1/conversations/{id}/local-turns` via pure Bearer, deletes on
 * cloud ack, and pushes reconcile payloads to the renderer.
 *
 * Pause/outbox split (as-built: 双模式工作区 §10.4): pause frames live under
 * `…/paused/` and are handled by SidecarManager — this module only processes
 * outbox. Shared scan entry: {@link recoverLocalPersistence}.
 */
import {
  mkdir,
  readFile,
  readdir,
  rename,
  unlink,
  writeFile,
} from "node:fs/promises";
import { join } from "node:path";
import {
  OUTBOX_CHANNELS,
  type OutboxFlushTurnResult,
  type OutboxPendingEntry,
  type OutboxStatusSnapshot,
  type OutboxSyncedPayload,
} from "@shared/outbox-contract";
import {
  deriveInterruptedAfterDecision,
  shouldRetainOpenForContinue,
} from "@shared/recoveryFold";
import type {
  SidecarCitation,
  SidecarInterruptedAfterDecision,
  SidecarRunsPayload,
  SidecarUnsyncedTurnSummary,
} from "@shared/sidecar-contract";
import { BrowserWindow, app, ipcMain } from "electron";
import { bearerPostJson, refreshAccessToken } from "./auth-client";

const PHASE_READY = "ready";
const PHASE_OPEN = "open";

const CHANNEL_CAPTAIN_CONTENT = "captain:content";
const CHANNEL_CAPTAIN_REASONING = "captain:reasoning";

/** Per-record writeback backoff: base 2s, double each failure, cap 5 min + jitter. */
const BACKOFF_BASE_MS = 2_000;
const BACKOFF_MAX_MS = 5 * 60_000;

export function sidecarDataDir(): string {
  return join(app.getPath("userData"), "sidecar");
}

export function outboxDir(): string {
  return join(sidecarDataDir(), "outbox");
}

export function pausedDir(): string {
  return join(sidecarDataDir(), "paused");
}

export function deadLetterDir(): string {
  return join(sidecarDataDir(), "dead-letter");
}

export interface OutboxRecord {
  schema_version?: number;
  user_message_id: string;
  conversation_id: string;
  message_id?: string | null;
  trace_id?: string;
  user_message?: string;
  content?: string;
  reasoning_content?: string | null;
  citations?: unknown[];
  runs?: unknown;
  /** seq(str) → {kind,payload,ts} — progressive journal; crash salvage has no runs. */
  journal?: Record<string, unknown>;
  /**
   * Mid-stream channel snapshots from StreamCheckpointer (D6).
   * channel → { text, generation }; desktop restart salvage reads captain:* when content is empty.
   */
  stream_segments?: Record<string, { text?: string; generation?: number }>;
  input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  cache_hit_tokens?: number;
  cache_miss_tokens?: number;
  rounds?: number;
  finish_reason?: string | null;
  phase?: string;
  updated_at?: number;
  /**
   * Desktop-owned retry bookkeeping (optional). Absent on fresh sidecar files;
   * written by writebacker after transient failures.
   */
  retry_count?: number;
  /** Epoch ms — skip POST until this time (unless flushTurn bypasses). */
  next_attempt_at?: number;
}

/**
 * HTTP 4xx except 401/408/429 → permanent (dead-letter).
 * 401/408/429/5xx/network (status 0) → transient (backoff retry).
 */
export function isPermanentHttpFailure(status: number): boolean {
  if (status < 400 || status >= 500) return false;
  return status !== 401 && status !== 408 && status !== 429;
}

/** Delay after `retryCount` failures (1-based). Caps at 5 min; adds up to 25% jitter. */
export function computeBackoffDelayMs(
  retryCount: number,
  random: () => number = Math.random,
): number {
  const failures = Math.max(1, retryCount);
  const exp = Math.min(failures - 1, 20);
  const base = Math.min(BACKOFF_BASE_MS * 2 ** exp, BACKOFF_MAX_MS);
  const jitter = Math.floor(random() * base * 0.25);
  return base + jitter;
}

function journalEntriesFromMap(
  journal: Record<string, unknown> | undefined,
): unknown[] | undefined {
  if (!journal || typeof journal !== "object") return undefined;
  const keys = Object.keys(journal).sort((a, b) => {
    const na = Number(a);
    const nb = Number(b);
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
    return a.localeCompare(b);
  });
  if (keys.length === 0) return undefined;
  return keys.map((k) => journal[k]);
}

/**
 * When hard-kill left content empty, promote captain stream snapshots into
 * content / reasoning_content (incomplete salvage). Returns true when the
 * record has any salvageable body after this fill.
 */
export function fillFromCaptainStreamSegments(record: OutboxRecord): boolean {
  const segs = record.stream_segments;
  if (!segs || typeof segs !== "object") {
    return (
      !!(record.content || "").trim() ||
      !!(record.reasoning_content || "").trim()
    );
  }
  const contentSeg = segs[CHANNEL_CAPTAIN_CONTENT];
  const contentText =
    contentSeg && typeof contentSeg === "object"
      ? String(contentSeg.text || "")
      : "";
  if (!(record.content || "").trim() && contentText.trim()) {
    record.content = contentText;
  }
  const reasoningSeg = segs[CHANNEL_CAPTAIN_REASONING];
  const reasoningText =
    reasoningSeg && typeof reasoningSeg === "object"
      ? String(reasoningSeg.text || "")
      : "";
  if (!(record.reasoning_content || "").trim() && reasoningText.trim()) {
    record.reasoning_content = reasoningText;
  }
  return (
    !!(record.content || "").trim() || !!(record.reasoning_content || "").trim()
  );
}

function toRecordTurnBody(record: OutboxRecord): Record<string, unknown> {
  const body: Record<string, unknown> = {
    user_message: record.user_message || "",
    user_message_id: record.user_message_id,
    content: record.content || "",
    reasoning_content: record.reasoning_content ?? null,
    citations: record.citations || [],
    runs: record.runs ?? null,
    message_id: record.message_id ?? null,
    input_tokens: record.input_tokens ?? 0,
    output_tokens: record.output_tokens ?? 0,
    reasoning_tokens: record.reasoning_tokens ?? 0,
    cache_hit_tokens: record.cache_hit_tokens ?? 0,
    cache_miss_tokens: record.cache_miss_tokens ?? 0,
    rounds: record.rounds ?? 0,
    trace_id: record.trace_id || "",
    finish_reason: record.finish_reason ?? null,
  };
  const journal = journalEntriesFromMap(record.journal);
  if (journal) body.journal = journal;
  return body;
}

async function readOutboxRecords(): Promise<OutboxRecord[]> {
  const dir = outboxDir();
  let names: string[];
  try {
    names = await readdir(dir);
  } catch {
    return [];
  }
  const records: OutboxRecord[] = [];
  for (const name of names) {
    if (!name.endsWith(".json") || name.endsWith(".tmp")) continue;
    try {
      const raw = await readFile(join(dir, name), "utf-8");
      const data = JSON.parse(raw) as OutboxRecord;
      if (data?.user_message_id && data.conversation_id) records.push(data);
    } catch {
      // torn / unreadable — skip
    }
  }
  return records;
}

function pushSynced(payload: OutboxSyncedPayload): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send(OUTBOX_CHANNELS.synced, payload);
    }
  }
}

async function writeRecord(record: OutboxRecord): Promise<void> {
  const dir = outboxDir();
  await mkdir(dir, { recursive: true });
  const target = join(dir, `${record.user_message_id}.json`);
  const tmp = `${target}.tmp`;
  await writeFile(tmp, JSON.stringify(record), "utf-8");
  await rename(tmp, target);
}

async function deleteRecord(userMessageId: string): Promise<void> {
  try {
    await unlink(join(outboxDir(), `${userMessageId}.json`));
  } catch {
    /* already gone */
  }
}

/** Move outbox record to dead-letter/ (keep body for forensics; stop polling). */
async function moveToDeadLetter(
  record: OutboxRecord,
  status: number,
): Promise<void> {
  console.error(
    "[outbox] permanent failure → dead-letter",
    record.user_message_id,
    status,
  );
  const destDir = deadLetterDir();
  await mkdir(destDir, { recursive: true });
  const src = join(outboxDir(), `${record.user_message_id}.json`);
  const dest = join(destDir, `${record.user_message_id}.json`);
  try {
    await rename(src, dest);
  } catch (err) {
    console.error(
      "[outbox] dead-letter move failed",
      record.user_message_id,
      err,
    );
  }
}

async function recordTransientFailure(record: OutboxRecord): Promise<void> {
  const count = (record.retry_count ?? 0) + 1;
  record.retry_count = count;
  record.next_attempt_at = Date.now() + computeBackoffDelayMs(count);
  try {
    await writeRecord(record);
  } catch (err) {
    console.error(
      "[outbox] retry state write failed",
      record.user_message_id,
      err,
    );
  }
}

/** Recent successful writebacks — fills synthetic flushTurn ack when the file is already gone. */
const recentSyncedConversation = new Map<string, string>();

let drainInFlight: Promise<{
  status: OutboxStatusSnapshot;
  synced: OutboxSyncedPayload[];
}> | null = null;

/**
 * At-least-once drain of ready outbox records. Idempotent cloud side
 * (`user_message_id`); retries leave the file until ack.
 */
export async function drainOutbox(): Promise<OutboxStatusSnapshot> {
  const result = await drainOutboxDetailed();
  return result.status;
}

async function drainOutboxDetailed(opts?: {
  /** Promote abandoned open records (app-restart salvage). Never use while turns may still run. */
  salvageOpen?: boolean;
  /** User-initiated flushTurn: ignore next_attempt_at and try immediately. */
  bypassBackoff?: boolean;
}): Promise<{
  status: OutboxStatusSnapshot;
  synced: OutboxSyncedPayload[];
}> {
  const salvageOpen = opts?.salvageOpen === true;
  const bypassBackoff = opts?.bypassBackoff === true;
  // Coalesce regular polls only; salvage / flushTurn wait then run their own pass.
  if (drainInFlight) {
    if (!salvageOpen && !bypassBackoff) return drainInFlight;
    await drainInFlight;
  }
  drainInFlight = (async () => {
    const synced: OutboxSyncedPayload[] = [];
    const records = await readOutboxRecords();
    for (const record of records) {
      // App-restart salvage only: open + salvageable body → treat as ready incomplete.
      // Body may come from content, or (D6 hard-kill) captain stream_segments when
      // content was never checkpointed. Regular polling must NOT promote open rows.
      if (salvageOpen && record.phase === PHASE_OPEN) {
        // D2: settled-but-unterminated turns keep open so frameless continue still
        // has local journal + resume_frame (do not salvage→ready→sync-delete).
        if (
          shouldRetainOpenForContinue({
            finishReason: record.finish_reason,
            journal: record.journal as Record<string, unknown> | undefined,
          })
        ) {
          continue;
        }
        const salvageable = fillFromCaptainStreamSegments(record);
        if (salvageable) {
          record.phase = PHASE_READY;
          // Align with CloudStore.salvage / OutboxStore.salvage: cancelled + incomplete.
          record.finish_reason = record.finish_reason || "cancelled";
          try {
            await writeRecord(record);
          } catch (err) {
            console.error("[outbox] salvage promote failed", err);
            continue;
          }
        }
      }
      if (record.phase !== PHASE_READY) continue;
      if (!(record.user_message || "").trim()) continue;
      if (
        !(record.trace_id || "").trim() ||
        (record.trace_id || "").length !== 32
      ) {
        continue;
      }
      if (
        !bypassBackoff &&
        typeof record.next_attempt_at === "number" &&
        record.next_attempt_at > Date.now()
      ) {
        continue;
      }

      const path = `/v1/conversations/${record.conversation_id}/local-turns`;
      let result: { ok: boolean; status: number; body: unknown };
      try {
        result = await bearerPostJson(path, toRecordTurnBody(record));
      } catch (err) {
        console.error(
          "[outbox] writeback network error",
          record.user_message_id,
          err,
        );
        await recordTransientFailure(record);
        continue;
      }
      if (!result.ok) {
        console.error(
          "[outbox] writeback failed",
          record.user_message_id,
          result.status,
          result.body,
        );
        if (isPermanentHttpFailure(result.status)) {
          await moveToDeadLetter(record, result.status);
        } else {
          await recordTransientFailure(record);
        }
        continue;
      }
      const body = result.body as {
        user_message_id?: string;
        assistant_message_id?: string | null;
        title?: string | null;
        followups?: string[] | null;
      };
      const payload: OutboxSyncedPayload = {
        conversationId: record.conversation_id,
        userMessageId: record.user_message_id,
        cloudUserMessageId: body.user_message_id || record.user_message_id,
        assistantMessageId: body.assistant_message_id ?? null,
        title: body.title ?? null,
        followups: body.followups ?? null,
      };
      await deleteRecord(record.user_message_id);
      recentSyncedConversation.set(
        record.user_message_id,
        record.conversation_id,
      );
      pushSynced(payload);
      synced.push(payload);
    }
    return { status: await statusSnapshot(), synced };
  })().finally(() => {
    drainInFlight = null;
  });
  return drainInFlight;
}

export async function statusSnapshot(): Promise<OutboxStatusSnapshot> {
  const records = await readOutboxRecords();
  const pending: OutboxPendingEntry[] = records
    .filter((r) => r.phase === PHASE_OPEN || r.phase === PHASE_READY)
    .map((r) => ({
      userMessageId: r.user_message_id,
      conversationId: r.conversation_id,
      phase: r.phase === PHASE_READY ? "ready" : "open",
      updatedAt: r.updated_at ?? 0,
    }));
  return { pending };
}

/**
 * Project outbox records for a conversation into recovery summaries (D3/D5).
 *
 * Fills empty open-phase bodies from captain stream_segments. Does **not**
 * promote open→ready (that stays in startup salvage). Caller filters out the
 * live turn's open row when attaching.
 */
/**
 * Journal-fold projection of interrupted_after_decision for a conversation (D2).
 * Uses outbox journal facts — not ``unsynced.length``.
 */
export async function listInterruptedAfterDecision(
  conversationId: string,
  liveMessageId?: string | null,
): Promise<SidecarInterruptedAfterDecision[]> {
  const records = await readOutboxRecords();
  const out: SidecarInterruptedAfterDecision[] = [];
  for (const record of records) {
    if (record.conversation_id !== conversationId) continue;
    const hit = deriveInterruptedAfterDecision({
      conversationId,
      userMessageId: record.user_message_id,
      messageId: record.message_id,
      finishReason: record.finish_reason,
      journal: record.journal as Record<string, unknown> | undefined,
      liveMessageId,
    });
    if (hit) out.push(hit);
  }
  return out;
}

export async function listUnsyncedSummaries(
  conversationId: string,
): Promise<SidecarUnsyncedTurnSummary[]> {
  const records = await readOutboxRecords();
  const out: SidecarUnsyncedTurnSummary[] = [];
  for (const record of records) {
    if (record.conversation_id !== conversationId) continue;
    if (record.phase !== PHASE_OPEN && record.phase !== PHASE_READY) continue;
    // Mutate a shallow copy so we don't rewrite the on-disk open record here.
    const view: OutboxRecord = {
      ...record,
      stream_segments: record.stream_segments,
    };
    fillFromCaptainStreamSegments(view);
    out.push({
      user_message_id: view.user_message_id,
      user_message: view.user_message || "",
      message_id: view.message_id ?? null,
      trace_id: view.trace_id || "",
      phase: view.phase === PHASE_READY ? "ready" : "open",
      updated_at: view.updated_at ?? 0,
      content: view.content || "",
      reasoning_content: view.reasoning_content ?? null,
      citations: (view.citations as SidecarCitation[]) || [],
      runs: (view.runs as SidecarRunsPayload) ?? null,
      finish_reason: view.finish_reason ?? null,
      input_tokens: view.input_tokens ?? 0,
      output_tokens: view.output_tokens ?? 0,
      reasoning_tokens: view.reasoning_tokens ?? 0,
      cache_hit_tokens: view.cache_hit_tokens ?? 0,
      cache_miss_tokens: view.cache_miss_tokens ?? 0,
    });
  }
  out.sort((a, b) => a.updated_at - b.updated_at);
  return out;
}

export async function flushTurn(
  userMessageId: string,
): Promise<OutboxFlushTurnResult> {
  // Poll briefly: sidecar may still be sealing finalize when renderer asks.
  const deadline = Date.now() + 15_000;
  let lastConversationId = "";
  while (Date.now() < deadline) {
    // Bypass backoff so an explicit user wait is not stuck behind next_attempt_at.
    const { synced } = await drainOutboxDetailed({ bypassBackoff: true });
    const hit = synced.find((s) => s.userMessageId === userMessageId);
    if (hit) return { ok: true, synced: hit };

    const records = await readOutboxRecords();
    const still = records.find((r) => r.user_message_id === userMessageId);
    if (!still) {
      // Already drained by a concurrent poll — treat as success (idempotent).
      const conversationId =
        lastConversationId || recentSyncedConversation.get(userMessageId) || "";
      return {
        ok: true,
        synced: {
          conversationId,
          userMessageId,
          cloudUserMessageId: userMessageId,
          assistantMessageId: null,
          title: null,
        },
      };
    }
    lastConversationId = still.conversation_id || lastConversationId;
    if (still.phase === PHASE_OPEN) {
      await new Promise((r) => setTimeout(r, 100));
      continue;
    }
    // Still ready after drain ⇒ auth / network failure — keep file for retry.
    return { ok: false, error: "writeback_pending" };
  }
  return { ok: false, error: "timeout" };
}

/**
 * Local-persistence recovery (as-built: 双模式工作区 §10.4): pause stale-claim
 * recovery is owned by the Python store on sidecar start; here we drain outbox
 * and salvage abandoned open rows.
 */
export async function recoverLocalPersistence(): Promise<void> {
  await drainOutboxDetailed({ salvageOpen: true });
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

export function startOutboxPolling(intervalMs = 2000): void {
  if (pollTimer) return;
  pollTimer = setInterval(() => {
    void drainOutbox();
  }, intervalMs);
}

export function stopOutboxPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

export function registerOutboxIpc(): void {
  ipcMain.handle(OUTBOX_CHANNELS.flush, async () => drainOutbox());
  ipcMain.handle(
    OUTBOX_CHANNELS.flushTurn,
    async (_e, req: { userMessageId?: string }) => {
      const id = String(req?.userMessageId || "").trim();
      if (!id) return { ok: false, error: "missing_user_message_id" };
      return flushTurn(id);
    },
  );
  ipcMain.handle(OUTBOX_CHANNELS.status, async () => statusSnapshot());
  ipcMain.handle(OUTBOX_CHANNELS.authRefresh, async () => refreshAccessToken());

  void recoverLocalPersistence();
  startOutboxPolling();

  app.on("before-quit", () => {
    stopOutboxPolling();
    void drainOutbox();
  });
}
