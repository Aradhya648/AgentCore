/**
 * User workflows REST client (定案 §10.6 / §10.7 / §10.8).
 *
 * Wire shapes hand-written; domain stays camelCase like `standingTasks`.
 * CRUD 404/501 → uiStorage local draft for that call (no sticky session flag).
 * Official templates: GET /v1/workflow-playbook-templates；复制:
 * POST /v1/workflows/from-playbook. Templates 404/501 → empty list (UI hides section).
 */

import { uiGet, uiSet } from "@/lib/uiStorage";
import { ApiError, api } from "@/services/api";
import {
  type WorkflowDefinition,
  emptyWorkflowDefinition,
  parseWorkflowDefinition,
} from "@/services/workflowDefinition";

/** Leaf under `agentcore:` namespace (uiStorage). */
const LOCAL_KEY = "user_workflows.v1";

/** Test hook — wipe local draft store. */
export function __resetWorkflowClientForTests(): void {
  uiSet(LOCAL_KEY, undefined);
}

export function isWorkflowBackendUnavailable(): boolean {
  return false;
}

export interface UserWorkflow {
  id: string;
  name: string;
  description: string | null;
  definition: WorkflowDefinition;
  version: number;
  createdAt: string;
  updatedAt: string;
  /** True when persisted only in this browser (API not ready). */
  localOnly?: boolean;
}

export interface CreateWorkflowInput {
  name: string;
  description?: string | null;
  definition?: WorkflowDefinition;
}

export interface PatchWorkflowInput {
  name?: string;
  description?: string | null;
  definition?: WorkflowDefinition;
}

export interface RunWorkflowInput {
  folderId: string;
  /** Optional per-run supplement (本轮补充). */
  note?: string | null;
}

export interface RunWorkflowResult {
  conversationId: string | null;
  runId: string | null;
}

/** Official playbook template slot (domain). */
export interface WorkflowTemplateSlot {
  key: string;
  label: string;
  required: boolean;
  hint: string | null;
}

/** Official playbook → copy-as-mine catalog entry (定案 §10.8). */
export interface WorkflowTemplate {
  id: string;
  title: string;
  summary: string;
  slots: WorkflowTemplateSlot[];
}

export interface FromPlaybookInput {
  playbook: string;
  /** Optional display name for the new user workflow. */
  name?: string | null;
  /** Primary slot values (topic / feature / site / task / app …). */
  slots: Record<string, string>;
}

/** Wire: snake_case — mirrors OpenAPI. */
export interface UserWorkflowWire {
  id: string;
  name: string;
  description?: string | null;
  definition: unknown;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Wire: GET /v1/workflow-playbook-templates item. */
export interface WorkflowTemplateSlotWire {
  key: string;
  label?: string;
  title?: string;
  required?: boolean;
  hint?: string | null;
  description?: string | null;
}

export interface WorkflowTemplateWire {
  id: string;
  title?: string;
  name?: string;
  summary?: string;
  description?: string | null;
  /**
   * Backend Phase-1: human-readable slot help string
   * (e.g. ``topic（必填，主题）``). Structured arrays accepted if a later API adds them.
   */
  primary_slots?: string | WorkflowTemplateSlotWire[];
  slots?: WorkflowTemplateSlotWire[];
}

interface LocalStore {
  items: UserWorkflowWire[];
}

function nowIso(): string {
  return new Date().toISOString();
}

function readLocal(): LocalStore {
  const parsed = uiGet<LocalStore>(LOCAL_KEY);
  if (!parsed) return { items: [] };
  return { items: Array.isArray(parsed.items) ? parsed.items : [] };
}

function writeLocal(store: LocalStore): void {
  if (store.items.length === 0) uiSet(LOCAL_KEY, undefined);
  else uiSet(LOCAL_KEY, store);
}

function newLocalId(): string {
  return `local_${Math.random().toString(36).slice(2, 12)}`;
}

export function toUserWorkflow(
  w: UserWorkflowWire,
  localOnly = false,
): UserWorkflow {
  return {
    id: w.id,
    name: w.name,
    description: w.description ?? null,
    definition: parseWorkflowDefinition(w.definition),
    version: w.version,
    createdAt: w.created_at,
    updatedAt: w.updated_at,
    localOnly,
  };
}

/**
 * Fallback primary slots when the API only returns id/title/summary
 * (Phase-1 catalog from §10.8 / playbook registry).
 */
const FALLBACK_PRIMARY_SLOTS: Record<
  string,
  Array<{ key: string; label: string; hint?: string }>
> = {
  research_report: [{ key: "topic", label: "主题", hint: "调研 / 报告主题" }],
  multi_lens_research: [{ key: "topic", label: "主题", hint: "事件或议题" }],
  build_feature: [{ key: "feature", label: "功能", hint: "要实现的功能简述" }],
  build_app: [{ key: "app", label: "应用", hint: "要搭建的应用 / SPA 简述" }],
  build_website: [
    { key: "site", label: "站点", hint: "要建的站点 / 落地页简述" },
  ],
  build_toolshed: [
    { key: "site", label: "工具台", hint: "控制台 / 工具台简述" },
  ],
  parallel_brief: [
    { key: "topic", label: "主题", hint: "要摸底对齐的主题" },
    {
      key: "angles",
      label: "方向",
      hint: "≥2 个可并行方向，逗号分隔，如：法律,品牌,舆情",
    },
  ],
};

function slotLabel(key: string): string {
  const known: Record<string, string> = {
    topic: "主题",
    feature: "功能",
    site: "站点",
    task: "任务",
    app: "应用",
    problem: "问题",
    verify: "验收",
    angles: "方向",
  };
  return known[key] ?? key;
}

function toTemplateSlot(raw: WorkflowTemplateSlotWire): WorkflowTemplateSlot {
  const key = String(raw.key ?? "").trim();
  return {
    key,
    label: (raw.label ?? raw.title ?? slotLabel(key)).trim() || key,
    required: raw.required !== false,
    hint: (raw.hint ?? raw.description ?? null)?.trim() || null,
  };
}

function fallbackSlotsFor(playbookId: string): WorkflowTemplateSlot[] {
  const rows = FALLBACK_PRIMARY_SLOTS[playbookId] ?? [
    { key: "topic", label: "主参数", hint: "按模板所需填写" },
  ];
  return rows.map((r) => ({
    key: r.key,
    label: r.label,
    required: true,
    hint: r.hint ?? null,
  }));
}

export function toWorkflowTemplate(w: WorkflowTemplateWire): WorkflowTemplate {
  const id = String(w.id ?? "").trim();
  const title = (w.title ?? w.name ?? id).trim() || id;
  const summary = (w.summary ?? w.description ?? "").trim();
  const structured =
    Array.isArray(w.slots) && w.slots.length > 0
      ? w.slots
      : Array.isArray(w.primary_slots)
        ? w.primary_slots
        : null;
  const helpText =
    typeof w.primary_slots === "string" ? w.primary_slots.trim() : "";
  let slots =
    structured && structured.length > 0
      ? structured.map(toTemplateSlot).filter((s) => s.key)
      : fallbackSlotsFor(id);
  const only = slots.length === 1 ? slots[0] : undefined;
  if (helpText && only) {
    slots = [{ ...only, hint: helpText }];
  }
  return { id, title, summary, slots };
}

function isMissingRoute(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 404 || e.status === 501);
}

function isLocalId(id: string): boolean {
  return id.startsWith("local_");
}

function listLocal(): UserWorkflow[] {
  return readLocal().items.map((w) => toUserWorkflow(w, true));
}

function createLocal(input: CreateWorkflowInput): UserWorkflow {
  const store = readLocal();
  const ts = nowIso();
  const wire: UserWorkflowWire = {
    id: newLocalId(),
    name: input.name.trim(),
    description: input.description?.trim() || null,
    definition: input.definition ?? emptyWorkflowDefinition(),
    version: 1,
    created_at: ts,
    updated_at: ts,
  };
  store.items.unshift(wire);
  writeLocal(store);
  return toUserWorkflow(wire, true);
}

function getLocal(id: string): UserWorkflow {
  const found = readLocal().items.find((w) => w.id === id);
  if (!found) {
    throw new ApiError(
      404,
      JSON.stringify({ error: { message: "工作流不存在" } }),
    );
  }
  return toUserWorkflow(found, true);
}

function patchLocal(id: string, input: PatchWorkflowInput): UserWorkflow {
  const store = readLocal();
  const idx = store.items.findIndex((w) => w.id === id);
  const prev = idx >= 0 ? store.items[idx] : undefined;
  if (idx < 0 || !prev) {
    throw new ApiError(
      404,
      JSON.stringify({ error: { message: "工作流不存在" } }),
    );
  }
  const next: UserWorkflowWire = {
    ...prev,
    name: input.name !== undefined ? input.name.trim() : prev.name,
    description:
      input.description !== undefined
        ? input.description?.trim() || null
        : prev.description,
    definition:
      input.definition !== undefined ? input.definition : prev.definition,
    version: prev.version + (input.definition !== undefined ? 1 : 0),
    updated_at: nowIso(),
  };
  store.items[idx] = next;
  writeLocal(store);
  return toUserWorkflow(next, true);
}

function deleteLocal(id: string): void {
  const store = readLocal();
  store.items = store.items.filter((w) => w.id !== id);
  writeLocal(store);
}

/** List the signed-in user's workflows (or local drafts if API missing). */
export async function listWorkflows(): Promise<UserWorkflow[]> {
  try {
    const res = await api.get<UserWorkflowWire[]>("/v1/workflows");
    return (Array.isArray(res) ? res : []).map((w) => toUserWorkflow(w));
  } catch (e) {
    if (isMissingRoute(e)) return listLocal();
    throw e;
  }
}

export async function getWorkflow(id: string): Promise<UserWorkflow> {
  if (isLocalId(id)) return getLocal(id);
  try {
    const res = await api.get<UserWorkflowWire>(
      `/v1/workflows/${encodeURIComponent(id)}`,
    );
    return toUserWorkflow(res);
  } catch (e) {
    if (isMissingRoute(e)) return getLocal(id);
    throw e;
  }
}

export async function createWorkflow(
  input: CreateWorkflowInput,
): Promise<UserWorkflow> {
  const body = {
    name: input.name.trim(),
    description: input.description?.trim() || null,
    definition: input.definition ?? emptyWorkflowDefinition(),
  };
  try {
    const res = await api.post<UserWorkflowWire>("/v1/workflows", body);
    return toUserWorkflow(res);
  } catch (e) {
    if (isMissingRoute(e)) return createLocal(input);
    throw e;
  }
}

export async function patchWorkflow(
  id: string,
  input: PatchWorkflowInput,
): Promise<UserWorkflow> {
  if (isLocalId(id)) return patchLocal(id, input);
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name.trim();
  if (input.description !== undefined) {
    const trimmed = input.description?.trim() || "";
    if (!trimmed) {
      body.clear_description = true;
    } else {
      body.description = trimmed;
    }
  }
  if (input.definition !== undefined) body.definition = input.definition;
  try {
    const res = await api.patch<UserWorkflowWire>(
      `/v1/workflows/${encodeURIComponent(id)}`,
      body,
    );
    return toUserWorkflow(res);
  } catch (e) {
    if (isMissingRoute(e)) return patchLocal(id, input);
    throw e;
  }
}

export async function deleteWorkflow(id: string): Promise<void> {
  if (isLocalId(id)) {
    deleteLocal(id);
    return;
  }
  try {
    await api.delete(`/v1/workflows/${encodeURIComponent(id)}`);
  } catch (e) {
    if (isMissingRoute(e)) {
      deleteLocal(id);
      return;
    }
    throw e;
  }
}

/**
 * Run once: select workspace + optional note → direct-start bypass.
 * Local drafts cannot run against a missing backend.
 */
export async function runWorkflow(
  id: string,
  input: RunWorkflowInput,
): Promise<RunWorkflowResult> {
  if (isLocalId(id)) {
    throw new ApiError(
      501,
      JSON.stringify({
        error: {
          code: "workflow_backend_unavailable",
          message: "本地草稿无法跑一次，请先在已接后端的环境保存到云端",
        },
      }),
    );
  }
  const body = {
    folder_id: input.folderId,
    note: input.note?.trim() || null,
  };
  const res = await api.post<{
    conversation_id?: string | null;
    run_id?: string | null;
  }>(`/v1/workflows/${encodeURIComponent(id)}/run`, body);
  return {
    conversationId: res?.conversation_id ?? null,
    runId: res?.run_id ?? null,
  };
}

/** Lightweight list for standing-task binder (id + name only). */
export async function listWorkflowOptions(): Promise<
  Array<{ id: string; name: string }>
> {
  const list = await listWorkflows();
  return list.map((w) => ({ id: w.id, name: w.name }));
}

/**
 * Official playbook templates (只读目录).
 * Missing route (404/501) → empty list so UI can hide the section.
 * Path: GET /v1/workflow-playbook-templates (avoid clash with /workflows/{id}).
 */
export async function listWorkflowTemplates(): Promise<WorkflowTemplate[]> {
  try {
    const res = await api.get<WorkflowTemplateWire[]>(
      "/v1/workflow-playbook-templates",
    );
    return (Array.isArray(res) ? res : [])
      .map(toWorkflowTemplate)
      .filter((t) => t.id);
  } catch (e) {
    if (isMissingRoute(e)) return [];
    throw e;
  }
}

/**
 * Copy an official playbook into the signed-in user's workflows (使用 = 复制为我的).
 * No localStorage fallback — expansion requires the backend.
 */
export async function createWorkflowFromPlaybook(
  input: FromPlaybookInput,
): Promise<UserWorkflow> {
  const slots: Record<string, string> = {};
  for (const [k, v] of Object.entries(input.slots)) {
    const key = k.trim();
    const val = v.trim();
    if (key && val) slots[key] = val;
  }
  const body: Record<string, unknown> = {
    playbook: input.playbook.trim(),
    slots,
  };
  const name = input.name?.trim();
  if (name) body.name = name;
  const res = await api.post<UserWorkflowWire>(
    "/v1/workflows/from-playbook",
    body,
  );
  return toUserWorkflow(res);
}
