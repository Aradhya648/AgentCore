/**
 * Standing tasks / scheduled automations REST client (L1 + L2a Webhook).
 *
 * OpenAPI types are not generated yet — narrow hand-written wire shapes aligned
 * with `docs/06-规划/站立任务定时自动化定案.md` §5.3 and
 * `docs/06-规划/站立任务L2-Webhook定案.md` §5. Domain models are camelCase
 * like `folders` / `handoff`; wire stays snake_case for the backend sketch.
 */

import { BASE_URL, api } from "@/services/api";
import type { PermissionAxes } from "@/services/permissionAxes";
import {
  DEFAULT_PERMISSION_AXES,
  normalizeAxes,
} from "@/services/permissionAxes";

/** Built-in schedule presets (UI + create/patch). Custom uses `cron`. */
export type SchedulePreset =
  | "daily"
  | "weekdays"
  | "weekly_mon"
  | "weekly_fri"
  | "monthly_1"
  | "custom";

/** Per-task trigger; mutually exclusive (定案 L2a). */
export type TriggerKind = "schedule" | "webhook";

/** Optional run provenance for inbox display. */
export type TriggerSource = "schedule" | "webhook" | "manual";

export const SCHEDULE_PRESET_ORDER: SchedulePreset[] = [
  "daily",
  "weekdays",
  "weekly_mon",
  "weekly_fri",
  "monthly_1",
  "custom",
];

export const SCHEDULE_PRESET_LABELS: Record<SchedulePreset, string> = {
  daily: "每天",
  weekdays: "工作日",
  weekly_mon: "每周一",
  weekly_fri: "每周五",
  monthly_1: "每月 1 日",
  custom: "自定义 cron",
};

export const TRIGGER_KIND_ORDER: TriggerKind[] = ["schedule", "webhook"];

export const TRIGGER_KIND_LABELS: Record<TriggerKind, string> = {
  schedule: "定时",
  webhook: "Webhook",
};

export const TRIGGER_SOURCE_LABELS: Record<TriggerSource, string> = {
  schedule: "定时",
  webhook: "Webhook",
  manual: "手动",
};

export type StandingTaskRunStatus =
  | "running"
  | "succeeded"
  | "failed"
  | "awaiting_user";

export interface StandingTask {
  id: string;
  name: string;
  triggerKind: TriggerKind;
  schedulePreset: SchedulePreset | null;
  cron: string | null;
  folderId: string;
  goal: string;
  permissionAxes: PermissionAxes;
  enabled: boolean;
  nextRunAt: string | null;
  conversationId: string | null;
  webhookId: string | null;
  /** Public POST URL when trigger is webhook; may be absolute or path. */
  webhookUrl: string | null;
  /**
   * One-time plaintext secret — only present on create / rotate responses.
   * List/GET never return this; treat as ephemeral UI state.
   */
  webhookSecret: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface StandingTaskRun {
  id: string;
  standingTaskId: string;
  /** Denormalized task name when the API includes it; else null. */
  taskName: string | null;
  status: StandingTaskRunStatus;
  conversationId: string | null;
  userMessageId: string | null;
  summary: string | null;
  error: string | null;
  /** Null = unread / not dismissed. */
  ackedAt: string | null;
  /** Present when backend sends it; inbox may show a source chip. */
  triggerSource: TriggerSource | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface CreateStandingTaskInput {
  name: string;
  triggerKind: TriggerKind;
  /** Required when `triggerKind === "schedule"`. */
  schedulePreset?: SchedulePreset;
  cron?: string | null;
  folderId: string;
  goal: string;
  permissionAxes: PermissionAxes;
  enabled?: boolean;
}

export interface PatchStandingTaskInput {
  name?: string;
  triggerKind?: TriggerKind;
  schedulePreset?: SchedulePreset | null;
  cron?: string | null;
  folderId?: string;
  goal?: string;
  permissionAxes?: PermissionAxes;
  enabled?: boolean;
}

export interface ListStandingTaskRunsQuery {
  status?: StandingTaskRunStatus | StandingTaskRunStatus[];
  /** Prefer unread badge rows when the API supports it. */
  unacked?: boolean;
  limit?: number;
}

export interface RotateWebhookSecretResult {
  webhookSecret: string;
  webhookUrl: string | null;
  webhookId: string | null;
  /** Full task when the API returns one; else null. */
  task: StandingTask | null;
}

// ---- wire ----

interface StandingTaskWire {
  id: string;
  name: string;
  trigger_kind?: string | null;
  schedule_preset?: string | null;
  cron?: string | null;
  folder_id: string;
  goal: string;
  permission_axes?: PermissionAxes | null;
  enabled: boolean;
  next_run_at?: string | null;
  conversation_id?: string | null;
  webhook_id?: string | null;
  webhook_url?: string | null;
  /** One-shot plaintext; create / rotate only. */
  webhook_secret?: string | null;
  created_at: string;
  updated_at: string;
}

interface StandingTaskRunWire {
  id: string;
  standing_task_id: string;
  task_name?: string | null;
  name?: string | null;
  status: string;
  conversation_id?: string | null;
  user_message_id?: string | null;
  summary?: string | null;
  error?: string | null;
  acked_at?: string | null;
  read_at?: string | null;
  trigger_source?: string | null;
  created_at: string;
  finished_at?: string | null;
}

interface RotateWebhookSecretWire {
  webhook_secret?: string | null;
  webhook_url?: string | null;
  webhook_id?: string | null;
  id?: string;
  name?: string;
  trigger_kind?: string | null;
  folder_id?: string;
  goal?: string;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

function asPreset(raw: string | null | undefined): SchedulePreset | null {
  if (!raw) return null;
  return (SCHEDULE_PRESET_ORDER as string[]).includes(raw)
    ? (raw as SchedulePreset)
    : "custom";
}

function asTriggerKind(raw: string | null | undefined): TriggerKind {
  return raw === "webhook" ? "webhook" : "schedule";
}

function asTriggerSource(raw: string | null | undefined): TriggerSource | null {
  if (raw === "schedule" || raw === "webhook" || raw === "manual") return raw;
  return null;
}

/** Backend returns a path; external callers need an absolute URL. */
export function absoluteWebhookUrl(
  raw: string | null | undefined,
): string | null {
  if (!raw) return null;
  if (/^https?:\/\//i.test(raw)) return raw;
  const base = BASE_URL.replace(/\/$/, "");
  const path = raw.startsWith("/") ? raw : `/${raw}`;
  return `${base}${path}`;
}

function asRunStatus(raw: string): StandingTaskRunStatus {
  switch (raw) {
    case "running":
    case "succeeded":
    case "failed":
    case "awaiting_user":
      return raw;
    default:
      return "failed";
  }
}

export function toStandingTask(w: StandingTaskWire): StandingTask {
  return {
    id: w.id,
    name: w.name,
    triggerKind: asTriggerKind(w.trigger_kind),
    schedulePreset: asPreset(w.schedule_preset),
    cron: w.cron ?? null,
    folderId: w.folder_id,
    goal: w.goal,
    permissionAxes: normalizeAxes(w.permission_axes ?? DEFAULT_PERMISSION_AXES),
    enabled: w.enabled,
    nextRunAt: w.next_run_at ?? null,
    conversationId: w.conversation_id ?? null,
    webhookId: w.webhook_id ?? null,
    webhookUrl: absoluteWebhookUrl(w.webhook_url),
    webhookSecret: w.webhook_secret ?? null,
    createdAt: w.created_at,
    updatedAt: w.updated_at,
  };
}

export function toStandingTaskRun(w: StandingTaskRunWire): StandingTaskRun {
  return {
    id: w.id,
    standingTaskId: w.standing_task_id,
    taskName: w.task_name ?? w.name ?? null,
    status: asRunStatus(w.status),
    conversationId: w.conversation_id ?? null,
    userMessageId: w.user_message_id ?? null,
    summary: w.summary ?? null,
    error: w.error ?? null,
    ackedAt: w.acked_at ?? w.read_at ?? null,
    triggerSource: asTriggerSource(w.trigger_source),
    createdAt: w.created_at,
    finishedAt: w.finished_at ?? null,
  };
}

function unwrapList<T>(payload: unknown, keys: string[]): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const obj = payload as Record<string, unknown>;
    for (const k of keys) {
      const v = obj[k];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

function createBody(input: CreateStandingTaskInput): Record<string, unknown> {
  const kind = input.triggerKind;
  const body: Record<string, unknown> = {
    name: input.name,
    trigger_kind: kind,
    folder_id: input.folderId,
    goal: input.goal,
    permission_axes: input.permissionAxes,
    enabled: input.enabled ?? true,
  };
  if (kind === "schedule") {
    const preset = input.schedulePreset ?? "weekly_mon";
    body.schedule_preset = preset;
    // Named presets must not send cron (backend rejects both); custom requires it.
    if (preset === "custom") {
      body.cron = input.cron ?? null;
    }
  }
  return body;
}

function patchBody(input: PatchStandingTaskInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.triggerKind !== undefined) body.trigger_kind = input.triggerKind;

  const kind = input.triggerKind;
  if (kind === "webhook") {
    // Switching to / staying on webhook: do not send schedule fields.
  } else if (kind === "schedule" || input.schedulePreset !== undefined) {
    if (input.schedulePreset !== undefined && input.schedulePreset !== null) {
      body.schedule_preset = input.schedulePreset;
      if (input.schedulePreset === "custom" && input.cron !== undefined) {
        body.cron = input.cron;
      }
    } else if (input.cron !== undefined && input.schedulePreset === undefined) {
      body.cron = input.cron;
    }
  } else if (input.cron !== undefined) {
    body.cron = input.cron;
  }

  if (input.folderId !== undefined) body.folder_id = input.folderId;
  if (input.goal !== undefined) body.goal = input.goal;
  if (input.permissionAxes !== undefined)
    body.permission_axes = input.permissionAxes;
  if (input.enabled !== undefined) body.enabled = input.enabled;
  return body;
}

/** List the signed-in user's standing tasks. */
export async function listStandingTasks(): Promise<StandingTask[]> {
  const res = await api.get<unknown>("/v1/standing-tasks");
  return unwrapList<StandingTaskWire>(res, ["items", "data", "tasks"]).map(
    toStandingTask,
  );
}

export async function getStandingTask(id: string): Promise<StandingTask> {
  const res = await api.get<StandingTaskWire>(`/v1/standing-tasks/${id}`);
  return toStandingTask(res);
}

export async function createStandingTask(
  input: CreateStandingTaskInput,
): Promise<StandingTask> {
  const res = await api.post<StandingTaskWire>(
    "/v1/standing-tasks",
    createBody(input),
  );
  return toStandingTask(res);
}

export async function patchStandingTask(
  id: string,
  input: PatchStandingTaskInput,
): Promise<StandingTask> {
  const res = await api.patch<StandingTaskWire>(
    `/v1/standing-tasks/${id}`,
    patchBody(input),
  );
  return toStandingTask(res);
}

export async function deleteStandingTask(id: string): Promise<void> {
  await api.delete(`/v1/standing-tasks/${id}`);
}

/** Trigger one run now (backend sketch: `POST …/run`). */
export async function runStandingTaskNow(
  id: string,
): Promise<StandingTaskRun | null> {
  const res = await api.post<StandingTaskRunWire | StandingTaskWire | unknown>(
    `/v1/standing-tasks/${id}/run`,
    {},
  );
  if (
    res &&
    typeof res === "object" &&
    "standing_task_id" in (res as object) &&
    "status" in (res as object)
  ) {
    return toStandingTaskRun(res as StandingTaskRunWire);
  }
  return null;
}

/**
 * Rotate webhook secret. Plaintext `webhook_secret` is returned once.
 * Accepts either a full task wire or a slim `{ webhook_secret, webhook_url? }`.
 */
export async function rotateWebhookSecret(
  id: string,
): Promise<RotateWebhookSecretResult> {
  const res = await api.post<RotateWebhookSecretWire>(
    `/v1/standing-tasks/${id}/rotate-webhook-secret`,
    {},
  );
  const secret =
    typeof res?.webhook_secret === "string" ? res.webhook_secret : "";
  if (!secret) {
    throw new Error("rotate-webhook-secret response missing webhook_secret");
  }
  const looksLikeTask =
    typeof res.id === "string" &&
    typeof res.folder_id === "string" &&
    typeof res.name === "string";
  return {
    webhookSecret: secret,
    webhookUrl: absoluteWebhookUrl(res.webhook_url),
    webhookId: res.webhook_id ?? null,
    task: looksLikeTask ? toStandingTask(res as StandingTaskWire) : null,
  };
}

function runsQueryString(q: ListStandingTaskRunsQuery = {}): string {
  const params = new URLSearchParams();
  if (q.status !== undefined) {
    const statuses = Array.isArray(q.status) ? q.status : [q.status];
    for (const s of statuses) params.append("status", s);
  }
  if (q.unacked === true) params.set("unacked", "true");
  if (q.limit !== undefined) params.set("limit", String(q.limit));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export async function listStandingTaskRuns(
  query: ListStandingTaskRunsQuery = {},
): Promise<StandingTaskRun[]> {
  const res = await api.get<unknown>(
    `/v1/standing-task-runs${runsQueryString(query)}`,
  );
  return unwrapList<StandingTaskRunWire>(res, ["items", "data", "runs"]).map(
    toStandingTaskRun,
  );
}

/** Mark a run card read / dismiss a failure card. */
export async function ackStandingTaskRun(id: string): Promise<StandingTaskRun> {
  const res = await api.post<StandingTaskRunWire>(
    `/v1/standing-task-runs/${id}/ack`,
    {},
  );
  return toStandingTaskRun(res);
}

/**
 * Badge = unacked awaiting_user + unacked failed (定案 §5.3 / §5.4；ack 可清待拍板).
 * Prefer server ``badge`` on the list payload; fall back to client filter.
 */
export async function countInboxBadge(): Promise<number> {
  const res = await api.get<unknown>("/v1/standing-task-runs?limit=1");
  if (res && typeof res === "object" && "badge" in res) {
    const n = (res as { badge?: unknown }).badge;
    if (typeof n === "number" && Number.isFinite(n)) return n;
  }
  const runs = unwrapList<StandingTaskRunWire>(res, [
    "items",
    "data",
    "runs",
  ]).map(toStandingTaskRun);
  return runs.filter((r) => {
    if (r.status === "awaiting_user" && !r.ackedAt) return true;
    if (r.status === "failed" && !r.ackedAt) return true;
    return false;
  }).length;
}

/** List / editor subtitle for trigger. */
export function scheduleLabel(task: StandingTask): string {
  if (task.triggerKind === "webhook") return TRIGGER_KIND_LABELS.webhook;
  if (task.schedulePreset && task.schedulePreset !== "custom") {
    return SCHEDULE_PRESET_LABELS[task.schedulePreset];
  }
  if (task.cron) return task.cron;
  if (task.schedulePreset === "custom") return "自定义";
  return "未设置周期";
}

export function triggerSourceLabel(source: TriggerSource): string {
  return TRIGGER_SOURCE_LABELS[source];
}
