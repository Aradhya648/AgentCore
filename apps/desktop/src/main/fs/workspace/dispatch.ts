import type { WorkspaceOpName, WorkspaceOpResult } from "@shared/ipc-contract";
import { toReason } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { ensureReady, getRoot } from "../roots";
import { opArchive } from "./archive";
import { opExecute } from "./exec";
import { opGrep } from "./grep";
import {
  opProcessList,
  opProcessRead,
  opProcessStart,
  opProcessStop,
} from "./process";
import { opIndexFiles, opList, opListTree, opRead, opReadLines } from "./read";
import { opErr } from "./result";
import {
  opAppend,
  opCopy,
  opDelete,
  opMkdir,
  opMove,
  opReadBytes,
  opReplace,
  opWrite,
  opWriteBytes,
} from "./write";

/** Session-root access mode (W3 readonly / organize). Permanent roots have neither. */
export type SessionRootMode = "readonly" | "organize";

const ORGANIZE_ALLOWED_OPS = new Set<WorkspaceOpName>([
  "read",
  "read_bytes",
  "read_lines",
  "list",
  "list_tree",
  "index_files",
  "grep",
  "process_read",
  "process_list",
  "process_stop",
  "move",
  "copy",
  "mkdir",
  "delete",
]);

const ORGANIZE_DENIED_OPS = new Set<WorkspaceOpName>([
  "write",
  "append",
  "write_bytes",
  "replace",
  "execute",
  "process_start",
  "archive",
]);

const READONLY_MSG = "会话授权目录为只读，不能写入；请把产出写到对话工作区";
const ORGANIZE_DENY_MSG =
  "整理授权不允许此操作（仅 list/read/grep/stat + move/copy/mkdir + 回收站删除）";
const PERMANENT_EXTERNAL_MSG =
  "区外目录禁止永久删除；请使用可逆删除（进回收站）";

/** Resolve explicit mode; fall back to legacy ``readonly`` boolean for old session roots. */
export function resolveSessionMode(root: StoredRoot): SessionRootMode | null {
  if (root.mode === "organize" || root.mode === "readonly") return root.mode;
  if (root.sessionOnly || root.readonly) return "readonly";
  return null;
}

/**
 * Mode + op whitelist for session external roots.
 * Returns an error envelope when denied; ``null`` when allowed (or not a session root).
 */
export function sessionRootAccessError(
  root: StoredRoot,
  op: WorkspaceOpName,
  args: Record<string, unknown>,
): WorkspaceOpResult | null {
  const mode = resolveSessionMode(root);
  if (mode === null) return null;

  if (mode === "readonly") {
    if (
      ORGANIZE_DENIED_OPS.has(op) ||
      op === "move" ||
      op === "copy" ||
      op === "mkdir" ||
      op === "delete"
    ) {
      return opErr("OutsideWorkspace", READONLY_MSG);
    }
    return null;
  }

  // organize
  if (op === "delete" && Boolean(args.permanent)) {
    return opErr("OutsideWorkspace", PERMANENT_EXTERNAL_MSG);
  }
  if (ORGANIZE_DENIED_OPS.has(op) || !ORGANIZE_ALLOWED_OPS.has(op)) {
    return opErr("OutsideWorkspace", ORGANIZE_DENY_MSG);
  }
  return null;
}

async function workspaceOp(req: {
  rootId: string;
  op: WorkspaceOpName;
  args: Record<string, unknown>;
}): Promise<WorkspaceOpResult> {
  await ensureReady();
  const root = getRoot(req.rootId);
  if (!root) return opErr("WorkspaceIOError", "本地目录未授权或已移除");
  return executeWorkspaceOp(root, req.op, req.args);
}

/**
 * 在给定授权根上执行一次本地工作区 op。
 *
 * 与 electron / 根注册表解耦（只收一个 `StoredRoot`），故可脱离 Electron 直接单测。
 * 顶层 try 把任何 op 内未预期的异常兜底为 `WorkspaceIOError`，保证通道永远收到一个
 * 信封而非悬挂。
 */
export async function executeWorkspaceOp(
  root: StoredRoot,
  op: WorkspaceOpName,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  try {
    const denied = sessionRootAccessError(root, op, args);
    if (denied) return denied;
    switch (op) {
      case "read":
        return await opRead(root, String(args.path ?? ""));
      case "read_bytes":
        return await opReadBytes(root, String(args.path ?? ""));
      case "write":
        return await opWrite(
          root,
          String(args.path ?? ""),
          String(args.content ?? ""),
        );
      case "append":
        return await opAppend(
          root,
          String(args.path ?? ""),
          String(args.content ?? ""),
        );
      case "write_bytes":
        return await opWriteBytes(
          root,
          String(args.path ?? ""),
          String(args.data ?? ""),
        );
      case "list":
        return await opList(
          root,
          String(args.directory ?? "."),
          String(args.pattern ?? "*"),
        );
      case "read_lines":
        return await opReadLines(
          root,
          String(args.path ?? ""),
          Number(args.offset ?? 1),
          args.limit == null ? null : Number(args.limit),
        );
      case "list_tree":
        return await opListTree(
          root,
          String(args.directory ?? "."),
          String(args.pattern ?? "*"),
          Number(args.max_depth ?? 3),
          Number(args.max_entries ?? 200),
        );
      case "index_files":
        return await opIndexFiles(
          root,
          args.order === "recent" ? "recent" : "path",
          String(args.base ?? ""),
        );
      case "mkdir":
        return await opMkdir(root, String(args.path ?? ""));
      case "delete":
        return await opDelete(
          root,
          String(args.path ?? ""),
          Boolean(args.permanent),
        );
      case "copy":
        return await opCopy(
          root,
          String(args.src ?? ""),
          String(args.dst ?? ""),
        );
      case "move":
        return await opMove(
          root,
          String(args.src ?? ""),
          String(args.dst ?? ""),
        );
      case "replace":
        return await opReplace(
          root,
          String(args.path ?? ""),
          String(args.old ?? ""),
          String(args.new ?? ""),
          Boolean(args.all),
        );
      case "grep":
        return await opGrep(root, args);
      case "execute":
        return await opExecute(root, args);
      case "archive":
        return await opArchive(root, args);
      case "process_start":
        return await opProcessStart(root, args);
      case "process_read":
        return await opProcessRead(root, args);
      case "process_stop":
        return await opProcessStop(root, args);
      case "process_list":
        return await opProcessList(root, args);
      default:
        return opErr("WorkspaceIOError", `本地工作区未知的操作：${op}`);
    }
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
}

export { workspaceOp };
