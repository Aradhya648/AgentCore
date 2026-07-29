import { fulfillClientToolOnce } from "@/services/clientToolFulfill";
import { resolveConversationLocalTarget } from "@/services/sidecarRouting";
import type { WorkspaceOpRequiredPayload } from "@/types/events";
import type { WorkspaceOpName, WorkspaceOpResult } from "@shared/ipc-contract";

/** 后台进程 op：通道注入 conversation_id（公开工具 schema 不含此字段）。 */
const PROCESS_OPS = new Set<string>([
  "process_start",
  "process_read",
  "process_stop",
  "process_list",
]);

/**
 * Desktop half of the local-workspace op channel (双模式工作区 P2a).
 *
 * When the server-side `LocalWorkspace` needs to touch the user's disk it streams
 * a `workspace_op_required` event; this runs the op against the bound FS root (via
 * the main process) and settles the paused op over the unified interaction bridge
 * (kind `client_tool`), so the live SSE turn resumes. The result envelope matches
 * `ResolveClientToolInteraction` (sans `kind`), so it is posted with `kind` added.
 *
 * Failure policy: the channel must always answer (or the server-side op only ends
 * on its timeout). A stale request (404) is a no-op; any other POST failure is
 * logged and left to the server timeout. A non-desktop runtime (no `fsApi`) or a
 * thrown IPC error becomes a typed error envelope, so the tool reports a clean
 * failure instead of the turn hanging.
 *
 * Same ``request_id`` is de-duplicated in-process so attach rehang does not
 * re-run write / execute side effects.
 */
export async function performWorkspaceOp(
  payload: WorkspaceOpRequiredPayload,
  conversationId: string,
): Promise<void> {
  await fulfillClientToolOnce({
    requestId: payload.request_id,
    conversationId,
    logLabel: "workspaceOps",
    perform: () => runLocalOp(payload, conversationId),
  });
}

async function runLocalOp(
  payload: WorkspaceOpRequiredPayload,
  conversationId: string,
): Promise<WorkspaceOpResult> {
  const fsApi = typeof window !== "undefined" ? window.fsApi : undefined;
  if (!fsApi?.workspaceOp) {
    return ioError("本地工作区不可用（非桌面环境）");
  }
  let rootId = payload.root_id;
  let args = payload.args;
  if (PROCESS_OPS.has(payload.op)) {
    args = {
      ...payload.args,
      conversation_id: payload.conversation_id || conversationId,
    };
    // 进程 op 直发通道、绕过 LocalWorkspace 的 subpath 前缀（工具不感知 scratch），
    // 且 sidecar 通道不知道桌面根注册表（root_id 恒空）。按会话绑定统一补齐：
    // root_id 缺失用绑定容器根（与 sidecar respond 寻址同构）；process_start 的
    // cwd 前缀 scratch 子路径（绑定无 subpath 时为无操作）。read / stop / list
    // 按 process_id / conversation_id 寻址，root 存在即可。
    if (!rootId || payload.op === "process_start") {
      const target = await resolveConversationLocalTarget(conversationId);
      if (!rootId) {
        if (!target) {
          return ioError("会话未绑定本地工作区，无法执行后台进程操作");
        }
        rootId = target.rootId;
      }
      if (payload.op === "process_start" && target?.subpath) {
        const cwd = String(args.cwd ?? "").trim();
        args.cwd =
          cwd && cwd !== "." ? `${target.subpath}/${cwd}` : target.subpath;
      }
    }
  }
  try {
    return await fsApi.workspaceOp(rootId, payload.op as WorkspaceOpName, args);
  } catch (e) {
    return ioError(e instanceof Error ? e.message : String(e));
  }
}

function ioError(detail: string): WorkspaceOpResult {
  return { ok: false, error: { kind: "WorkspaceIOError", detail } };
}
