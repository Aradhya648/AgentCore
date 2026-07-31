/**
 * Standing tasks / scheduled automations REST client (L1 + L2a Webhook).
 *
 * Wire shapes come from OpenAPI (`@agentcore/contract-rest-types` via
 * `@/types/api.generated`). Domain models stay camelCase like `folders` /
 * `handoff`.
 */

import { BASE_URL, api } from "@/services/api";
import type { PermissionAxes } from "@/services/permissionAxes";
import {
  DEFAULT_PERMISSION_AXES,
  normalizeAxes,
} from "@/services/permissionAxes";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

type StandingTaskWire = Schemas["StandingTaskSummary"];
type StandingTaskRunWire = Schemas["StandingTaskRunSummary"];
type StandingTaskRunListWire = Schemas["StandingTaskRunListResponse"];
type CreateStandingTaskWire = Schemas["CreateStandingTaskRequest"];
type UpdateStandingTaskWire = Schemas["UpdateStandingTaskRequest"];
type TriggerStandingTaskWire = Schemas["TriggerStandingTaskResponse"];
type RotateWebhookSecretWire = Schemas["RotateWebhookSecretResponse"];

/** Until gen:types picks up template / workflow fields. */
type StandingTaskWireExt = StandingTaskWire & {
  template_key?: string | null;
  template_config?: StandingTaskTemplateConfigWire | null;
  workflow_id?: string | null;
  workflow_name?: string | null;
};

/** openapi-typescript marks defaulted bools required; PATCH omits them unless clearing. */
type UpdateStandingTaskWireExt = Omit<
  UpdateStandingTaskWire,
  "clear_workflow"
> & {
  clear_workflow?: boolean;
};

/** System template key (Phase 1). */
export type StandingTaskTemplateKey = "daily_conversation_review";

export const DAILY_CONVERSATION_REVIEW_KEY: StandingTaskTemplateKey =
  "daily_conversation_review";

/** Domain: knobs for system templates (daily review scope). */
export interface StandingTaskTemplateConfig {
  includeGlobal?: boolean;
  folderIds?: string[];
  lookbackHours?: number;
}

/** Wire: snake_case template_config. */
export interface StandingTaskTemplateConfigWire {
  include_global?: boolean;
  folder_ids?: string[];
  lookback_hours?: number;
}

export interface StandingTaskTemplate {
  key: StandingTaskTemplateKey | string;
  title: string;
  description: string;
  defaultName: string;
  defaultCron: string;
  installedTaskId: string | null;
  enabled: boolean | null;
}

export interface StandingTaskTemplateWire {
  key: string;
  title: string;
  description: string;
  default_name: string;
  default_cron: string;
  installed_task_id?: string | null;
  enabled?: boolean | null;
}

/** Built-in schedule presets (UI + create/patch). Custom uses `cron`. */
export type SchedulePreset =
  | "daily"
  | "weekdays"
  | "weekly_mon"
  | "weekly_fri"
  | "monthly_1"
  | "custom";

export interface EnsureStandingTaskTemplateInput {
  folderId: string;
  cron?: string | null;
  schedulePreset?: SchedulePreset | null;
  enabled?: boolean;
  templateConfig?: StandingTaskTemplateConfig;
  permissionAxes?: PermissionAxes;
}

/** Per-task trigger; mutually exclusive (定案 L2a). */
export type TriggerKind = StandingTaskWire["trigger_kind"];

/** Optional run provenance for inbox display. */
export type TriggerSource = StandingTaskRunWire["trigger_source"];

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

export type StandingTaskRunStatus = StandingTaskRunWire["status"];

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
  lastRunAt: string | null;
  webhookId: string | null;
  /** Public POST URL when trigger is webhook; may be absolute or path. */
  webhookUrl: string | null;
  /**
   * One-time plaintext secret — only present on create / rotate responses.
   * List/GET never return this; treat as ephemeral UI state.
   */
  webhookSecret: string | null;
  /** System template key when this row was installed from catalog; else null. */
  templateKey: string | null;
  /** Template knobs (scope / lookback); empty object when not a template. */
  templateConfig: StandingTaskTemplateConfig;
  /** Bound user workflow id; null = open-mode standing task. */
  workflowId: string | null;
  /** Denormalized workflow name when API includes it. */
  workflowName: string | null;
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
  /** Optional bound workflow (定案 §10.3). */
  workflowId?: string | null;
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
  templateConfig?: StandingTaskTemplateConfig;
  workflowId?: string | null;
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
}

/** Immediate-run response — OpenAPI `TriggerStandingTaskResponse`. */
export interface TriggerStandingTaskResult {
  runId: string;
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

export function toTemplateConfig(
  raw: StandingTaskTemplateConfigWire | null | undefined,
): StandingTaskTemplateConfig {
  if (!raw || typeof raw !== "object") {
    return {};
  }
  const out: StandingTaskTemplateConfig = {};
  if (raw.include_global !== undefined)
    out.includeGlobal = !!raw.include_global;
  if (Array.isArray(raw.folder_ids)) {
    out.folderIds = raw.folder_ids.map(String).filter(Boolean);
  }
  if (raw.lookback_hours !== undefined && raw.lookback_hours !== null) {
    const n = Number(raw.lookback_hours);
    if (Number.isFinite(n)) out.lookbackHours = n;
  }
  return out;
}

/** Product defaults — match server StandingTaskTemplateConfig Field defaults. */
const DEFAULT_TEMPLATE_INCLUDE_GLOBAL = true;
const DEFAULT_TEMPLATE_LOOKBACK_HOURS = 24;

function templateConfigWire(
  cfg: StandingTaskTemplateConfig,
): Schemas["StandingTaskTemplateConfig"] {
  const wire: Schemas["StandingTaskTemplateConfig"] = {
    include_global: cfg.includeGlobal ?? DEFAULT_TEMPLATE_INCLUDE_GLOBAL,
    lookback_hours: cfg.lookbackHours ?? DEFAULT_TEMPLATE_LOOKBACK_HOURS,
  };
  if (cfg.folderIds !== undefined) wire.folder_ids = cfg.folderIds;
  return wire;
}

export function toStandingTaskTemplate(
  w: StandingTaskTemplateWire,
): StandingTaskTemplate {
  return {
    key: w.key,
    title: w.title,
    description: w.description,
    defaultName: w.default_name,
    defaultCron: w.default_cron,
    installedTaskId: w.installed_task_id ?? null,
    enabled: w.enabled ?? null,
  };
}

export function toStandingTask(w: StandingTaskWire): StandingTask {
  const ext = w as StandingTaskWireExt;
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
    lastRunAt: w.last_run_at ?? null,
    webhookId: w.webhook_id ?? null,
    webhookUrl: absoluteWebhookUrl(w.webhook_url),
    webhookSecret: w.webhook_secret ?? null,
    templateKey: ext.template_key ?? null,
    templateConfig: toTemplateConfig(ext.template_config),
    workflowId: ext.workflow_id ?? null,
    workflowName: ext.workflow_name ?? null,
    createdAt: w.created_at,
    updatedAt: w.updated_at,
  };
}

/**
 * Parse UTC daily cron ``M H * * *`` → local wall-clock hour/minute.
 * Falls back to 09:00 local when the expression is missing or not daily.
 */
export function localHmFromUtcCron(cron: string | null | undefined): {
  hour: number;
  minute: number;
} {
  const m = cron?.trim().match(/^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$/);
  if (!m) return { hour: 9, minute: 0 };
  const utcMin = Number(m[1]);
  const utcHour = Number(m[2]);
  if (
    !Number.isFinite(utcMin) ||
    !Number.isFinite(utcHour) ||
    utcMin < 0 ||
    utcMin > 59 ||
    utcHour < 0 ||
    utcHour > 23
  ) {
    return { hour: 9, minute: 0 };
  }
  const d = new Date();
  d.setUTCHours(utcHour, utcMin, 0, 0);
  return { hour: d.getHours(), minute: d.getMinutes() };
}

/** Local hour/minute → UTC daily cron ``M H * * *``. */
export function utcCronFromLocalHm(hour: number, minute: number): string {
  const h = Math.max(0, Math.min(23, Math.floor(hour)));
  const min = Math.max(0, Math.min(59, Math.floor(minute)));
  const d = new Date();
  d.setHours(h, min, 0, 0);
  return `${d.getUTCMinutes()} ${d.getUTCHours()} * * *`;
}

export function toStandingTaskRun(w: StandingTaskRunWire): StandingTaskRun {
  return {
    id: w.id,
    standingTaskId: w.standing_task_id,
    taskName: w.task_name ?? null,
    status: asRunStatus(w.status),
    conversationId: w.conversation_id ?? null,
    userMessageId: w.user_message_id ?? null,
    summary: w.summary ?? null,
    error: w.error ?? null,
    ackedAt: w.acked_at ?? null,
    triggerSource: asTriggerSource(w.trigger_source),
    createdAt: w.created_at,
    finishedAt: w.finished_at ?? null,
  };
}

function createBody(
  input: CreateStandingTaskInput,
): CreateStandingTaskWire & { workflow_id?: string | null } {
  const kind = input.triggerKind;
  const body: CreateStandingTaskWire & { workflow_id?: string | null } = {
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
  if (input.workflowId !== undefined) {
    body.workflow_id = input.workflowId;
  }
  return body;
}

function patchBody(input: PatchStandingTaskInput): UpdateStandingTaskWireExt {
  const body: UpdateStandingTaskWireExt = {};
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
  if (input.templateConfig !== undefined) {
    body.template_config = templateConfigWire(input.templateConfig);
  }
  // Backend clears binding only via clear_workflow=true (null workflow_id is ignored).
  if (input.workflowId !== undefined) {
    if (input.workflowId === null) {
      body.clear_workflow = true;
    } else {
      body.workflow_id = input.workflowId;
    }
  }
  return body;
}

/** List the signed-in user's standing tasks. */
export async function listStandingTasks(): Promise<StandingTask[]> {
  const res = await api.get<StandingTaskWire[]>("/v1/standing-tasks");
  return (Array.isArray(res) ? res : []).map(toStandingTask);
}

/** Catalog of system templates + install state for the signed-in user. */
export async function listStandingTaskTemplates(): Promise<
  StandingTaskTemplate[]
> {
  const res = await api.get<StandingTaskTemplateWire[]>(
    "/v1/standing-task-templates",
  );
  return (Array.isArray(res) ? res : []).map(toStandingTaskTemplate);
}

/**
 * Idempotent install of a system template (default ``enabled=false``).
 * Returns the existing row when already installed.
 */
export async function ensureStandingTaskTemplate(
  key: string,
  input: EnsureStandingTaskTemplateInput,
): Promise<StandingTask> {
  const body: Record<string, unknown> = {
    folder_id: input.folderId,
    enabled: input.enabled ?? false,
  };
  if (input.cron !== undefined) body.cron = input.cron;
  if (input.schedulePreset !== undefined && input.schedulePreset !== null) {
    body.schedule_preset = input.schedulePreset;
  }
  if (input.templateConfig !== undefined) {
    body.template_config = templateConfigWire(input.templateConfig);
  }
  if (input.permissionAxes !== undefined) {
    body.permission_axes = input.permissionAxes;
  }
  const res = await api.post<StandingTaskWire>(
    `/v1/standing-task-templates/${encodeURIComponent(key)}/ensure`,
    body,
  );
  return toStandingTask(res);
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

/**
 * Trigger one run now. Response is OpenAPI `TriggerStandingTaskResponse`
 * (`run_id` only) — not a full inbox row.
 */
export async function runStandingTaskNow(
  id: string,
): Promise<TriggerStandingTaskResult> {
  const res = await api.post<TriggerStandingTaskWire>(
    `/v1/standing-tasks/${id}/run`,
    {},
  );
  if (!res?.run_id) {
    throw new Error("trigger standing task response missing run_id");
  }
  return { runId: res.run_id };
}

/**
 * Rotate webhook secret. Plaintext `webhook_secret` is returned once
 * (`RotateWebhookSecretResponse`).
 */
export async function rotateWebhookSecret(
  id: string,
): Promise<RotateWebhookSecretResult> {
  const res = await api.post<RotateWebhookSecretWire>(
    `/v1/standing-tasks/${id}/rotate-webhook-secret`,
    {},
  );
  if (!res?.webhook_secret) {
    throw new Error("rotate-webhook-secret response missing webhook_secret");
  }
  return {
    webhookSecret: res.webhook_secret,
    webhookUrl: absoluteWebhookUrl(res.webhook_url),
    webhookId: res.webhook_id,
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
  const res = await api.get<StandingTaskRunListWire>(
    `/v1/standing-task-runs${runsQueryString(query)}`,
  );
  return (res?.items ?? []).map(toStandingTaskRun);
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
 * Badge = unacked awaiting_user + unacked failed.
 * Prefer server ``badge`` on the list payload.
 */
export async function countInboxBadge(): Promise<number> {
  const res = await api.get<StandingTaskRunListWire>(
    "/v1/standing-task-runs?limit=1",
  );
  if (typeof res?.badge === "number" && Number.isFinite(res.badge)) {
    return res.badge;
  }
  return (res?.items ?? []).map(toStandingTaskRun).filter((r) => {
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
