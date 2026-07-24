import { StreamError } from "@/lib/errors";
import {
  type ChangeType,
  type HandoffApplySelection,
  type HandoffFileChange,
  sha256HexFromBase64,
} from "@/lib/handoff-review";
import {
  BASE_URL,
  api,
  getCsrfHeaders,
  notifyUnauthorized,
  tryRefresh,
} from "@/services/api";
import { performWorkspaceOp } from "@/services/workspaceOps";
import type { components } from "@/types/api.generated";
import type {
  HandoffApplyDonePayload,
  HandoffJobStartedPayload,
  HandoffSnapshotDonePayload,
  SSEEvent,
  WorkspaceOpRequiredPayload,
} from "@/types/events";
import type { WorkspaceOpName } from "@shared/ipc-contract";

type Schemas = components["schemas"];

export interface HandoffResult {
  snapshotId: string;
  sizeBytes: number;
}

/** 派发成功的回执：作业 id 与承载团队回放的隐藏作业对话 id。 */
export interface HandoffJobStarted {
  jobId: string;
  jobConversationId: string;
}

/** 一个本地→云交接作业（双模式工作区 P2e / e2，camelCase 域模型）。 */
export interface HandoffJob {
  id: string;
  sourceConversationId: string;
  jobConversationId: string;
  baseSnapshotId: string;
  resultSnapshotId: string | null;
  task: string;
  status: "pending" | "running" | "succeeded" | "failed";
  error: string | null;
  createdAt: string;
  updatedAt: string;
  finishedAt: string | null;
}

/** 一次交接结果的 diff：变更集 + 表头计数（双模式工作区 P2e / e3）。 */
export interface HandoffDiff {
  jobId: string;
  changes: HandoffFileChange[];
  total: number;
  added: number;
  modified: number;
  deleted: number;
}

/** 应用回写中单文件的结果，对齐后端 `ApplyOutcome`。 */
export interface HandoffApplyResultRow {
  path: string;
  status: "applied" | "skipped" | "conflict" | "error";
  changeType: ChangeType | null;
  detail: string;
}

/** 一次应用回写的汇总：逐文件结果 + 卷起的计数（双模式工作区 P2e / e3）。 */
export interface HandoffApplySummary {
  jobId: string;
  results: HandoffApplyResultRow[];
  applied: number;
  skipped: number;
  conflicts: number;
  errors: number;
}

/** Server handoff-job payload (`/handoff/jobs`), generated from OpenAPI. */
type BackendJob = Schemas["HandoffJobSummary"];

/** Server diff file-change row (`/handoff/jobs/{id}/diff`), generated from OpenAPI. */
type BackendFileChange = Schemas["HandoffFileChange"];

/** Server diff payload (`/handoff/jobs/{id}/diff`), generated from OpenAPI. */
type BackendDiff = Schemas["HandoffDiffResponse"];

function toJob(b: BackendJob): HandoffJob {
  return {
    id: b.id,
    sourceConversationId: b.source_conversation_id,
    jobConversationId: b.job_conversation_id,
    baseSnapshotId: b.base_snapshot_id,
    resultSnapshotId: b.result_snapshot_id,
    task: b.task,
    status: b.status,
    error: b.error,
    createdAt: b.created_at,
    updatedAt: b.updated_at,
    finishedAt: b.finished_at,
  };
}

function toChange(b: BackendFileChange): HandoffFileChange {
  return {
    path: b.path,
    changeType: b.change_type,
    baseSha: b.base_sha,
    resultSha: b.result_sha,
    isBinary: b.is_binary,
    content: b.content,
    sizeBytes: b.size_bytes,
  };
}

/**
 * 一条工作区交接 SSE 流的通用消费器（e1 快照 / e2 派发 / e3 应用共用）。
 *
 * 三条流形状一致：服务端经通道下发若干 `workspace_op_required`（ARCHIVE / WRITE_BYTES
 * / DELETE），本端用既有 `performWorkspaceOp` 在绑定根上履行并回填；末尾发一条「完成」
 * 事件携结果。`onEvent` 只负责认出并映射那条完成事件（返回非 undefined 即为最终结果）。
 *
 * 复用 send 路径的鉴权：access token 过期则刷新一次重放，否则跳登录。这是独立于聊天流
 * 的专用消费器（聊天流改 store，交接流返回值），故不复用 `dispatchSSEEvent`。失败（内联
 * error 事件 / 传输失败 / 流结束仍无结果）抛出，以便 UI 收口。
 */
async function consumeWorkspaceStream<T>(
  path: string,
  conversationId: string,
  opts: { body?: unknown; signal?: AbortSignal },
  onEvent: (event: SSEEvent) => T | undefined,
): Promise<T> {
  const hasBody = opts.body !== undefined;
  const doFetch = () =>
    fetch(`${BASE_URL}${path}`, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "text/event-stream",
        ...getCsrfHeaders("POST"),
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
      },
      body: hasBody ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });

  let response: Response;
  try {
    response = await doFetch();
    if (response.status === 401) {
      const outcome = await tryRefresh();
      if (outcome === "renewed") {
        response = await doFetch();
      } else if (outcome === "auth_dead") {
        notifyUnauthorized();
        throw new StreamError("auth");
      } else {
        throw new StreamError("network");
      }
      if (response.status === 401) {
        notifyUnauthorized();
        throw new StreamError("auth");
      }
    }
  } catch (err) {
    if (err instanceof StreamError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new StreamError("network");
  }
  if (!response.ok) throw new StreamError("http", response.status);

  const reader = response.body?.getReader();
  if (!reader) throw new StreamError("network");

  const decoder = new TextDecoder();
  let buffer = "";
  let result: T | undefined;
  let failure: string | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let event: SSEEvent;
        try {
          event = JSON.parse(line.slice(6)) as SSEEvent;
        } catch {
          continue; // malformed event — skip
        }
        if (event.type === "workspace_op_required") {
          // Fulfil the op (ARCHIVE / WRITE_BYTES / DELETE) against the bound root,
          // exactly as the chat stream does; it POSTs its result to the ops resolve
          // endpoint, settling the paused server-side op so the flow can proceed.
          void performWorkspaceOp(
            event.payload as WorkspaceOpRequiredPayload,
            conversationId,
          );
        } else if (event.type === "error") {
          failure =
            (event.payload as { message?: string }).message ?? "操作失败";
        } else {
          const mapped = onEvent(event);
          if (mapped !== undefined) result = mapped;
        }
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new StreamError("network");
  }

  if (failure) throw new Error(failure);
  if (result === undefined) throw new StreamError("network");
  return result;
}

/**
 * 本地→云交接（双模式工作区 P2e / e1）：把绑定的本地工作区快照到云端。
 *
 * POST 一个 SSE 端点：服务端下发一个 `workspace_op_required`（ARCHIVE op），本端打包
 * 绑定根并回填；服务端解包暂存、快照入 OSS，末尾发 `handoff_snapshot_done` 带新快照 id。
 */
export async function runHandoff(
  conversationId: string,
  signal?: AbortSignal,
): Promise<HandoffResult> {
  return consumeWorkspaceStream(
    `/v1/conversations/${conversationId}/workspace/handoff`,
    conversationId,
    { signal },
    (event) => {
      if (event.type === "handoff_snapshot_done") {
        const p = event.payload as HandoffSnapshotDonePayload;
        return { snapshotId: p.snapshot_id, sizeBytes: p.size_bytes };
      }
      return undefined;
    },
  );
}

/**
 * 把任务交给云端团队（双模式工作区 P2e / e2）：快照本地文件后在云端后台跑一支 Agent
 * 团队。SSE 先下发 ARCHIVE op（本端履行），末尾发 `handoff_job_started` 带作业 id；云端
 * 运行在流关闭后继续，轮询 `listHandoffJobs` 看状态。仅本地模式可派发（否则 422）。
 */
export async function dispatchHandoffJob(
  conversationId: string,
  task: string,
  signal?: AbortSignal,
): Promise<HandoffJobStarted> {
  return consumeWorkspaceStream(
    `/v1/conversations/${conversationId}/workspace/handoff/dispatch`,
    conversationId,
    { body: { task }, signal },
    (event) => {
      if (event.type === "handoff_job_started") {
        const p = event.payload as HandoffJobStartedPayload;
        return { jobId: p.job_id, jobConversationId: p.job_conversation_id };
      }
      return undefined;
    },
  );
}

/** 一个对话的本地→云交接作业，按时间倒序（双模式工作区 P2e / e2）。 */
export async function listHandoffJobs(
  conversationId: string,
): Promise<HandoffJob[]> {
  const res = await api.get<Schemas["HandoffJobListResponse"]>(
    `/v1/conversations/${conversationId}/handoff/jobs`,
  );
  return res.data.map(toJob);
}

/**
 * 一个已完成交接的结果 diff（双模式工作区 P2e / e3）：result 对 base 快照的变更集，
 * 每条携 base 哈希供客户端三方判定。作业未成功时后端返回 409。
 */
export async function getHandoffDiff(
  conversationId: string,
  jobId: string,
): Promise<HandoffDiff> {
  const res = await api.get<BackendDiff>(
    `/v1/conversations/${conversationId}/handoff/jobs/${jobId}/diff`,
  );
  return {
    jobId: res.job_id,
    changes: res.data.map(toChange),
    total: res.total,
    added: res.added,
    modified: res.modified,
    deleted: res.deleted,
  };
}

/**
 * 应用一个已完成交接的所选变更回本地（双模式工作区 P2e / e3）。SSE 下发 WRITE_BYTES /
 * DELETE op（本端履行），末尾发 `handoff_apply_done` 带逐文件结果。冲突门服务端权威：
 * 本地自基线偏离的文件被拒（status `conflict`），除非该选择 `force`。请求体转回后端的
 * snake_case（`local_sha`）。
 */
export async function applyHandoffJob(
  conversationId: string,
  jobId: string,
  selections: HandoffApplySelection[],
  signal?: AbortSignal,
): Promise<HandoffApplySummary> {
  const body = {
    selections: selections.map((s) => ({
      path: s.path,
      decision: s.decision,
      local_sha: s.localSha,
      force: s.force,
    })),
  };
  return consumeWorkspaceStream(
    `/v1/conversations/${conversationId}/handoff/jobs/${jobId}/apply`,
    conversationId,
    { body, signal },
    (event) => {
      if (event.type === "handoff_apply_done") {
        const p = event.payload as HandoffApplyDonePayload;
        return {
          jobId: p.job_id,
          results: p.results.map((r) => ({
            path: r.path,
            status: r.status,
            changeType: r.change_type,
            detail: r.detail,
          })),
          applied: p.applied,
          skipped: p.skipped,
          conflicts: p.conflicts,
          errors: p.errors,
        } satisfies HandoffApplySummary;
      }
      return undefined;
    },
  );
}

/**
 * 逐文件读本地字节并算 sha256 hex，供 e3 三方判定的「第三方输入」。对每个路径在绑定根上
 * 跑 `read_bytes`（服务端回 base64）→ 解码哈希；文件本地不存在/不可读/非桌面环境一律为
 * null（= 本地无此文件）。并发读取，返回 path→sha|null 映射。
 */
export async function readLocalShas(
  rootId: string,
  paths: string[],
): Promise<Map<string, string | null>> {
  const map = new Map<string, string | null>();
  const fsApi = typeof window !== "undefined" ? window.fsApi : undefined;
  if (!fsApi?.workspaceOp) {
    for (const p of paths) map.set(p, null);
    return map;
  }
  await Promise.all(
    paths.map(async (path) => {
      try {
        const res = await fsApi.workspaceOp(
          rootId,
          "read_bytes" as WorkspaceOpName,
          { path },
        );
        map.set(
          path,
          res.ok && typeof res.value === "string"
            ? await sha256HexFromBase64(res.value)
            : null,
        );
      } catch {
        map.set(path, null);
      }
    }),
  );
  return map;
}
