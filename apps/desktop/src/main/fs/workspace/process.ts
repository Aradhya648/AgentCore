/**
 * Workspace process_* ops —— 委托主进程 {@link processService}，并融合用户 pty 会话。
 *
 * `conversation_id` 由通道注入（`performWorkspaceOp` / 后端序列化），不在公开工具 schema 内。
 * M3：`process_list` / `process_read` 纳入用户终端；`process_stop` 对用户终端拒绝。
 */
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { processService, resolveProcessCwd } from "../../process-service";
import { ptyService } from "../../pty-service";
import type { StoredRoot } from "../roots";
import { opErr, opOk } from "./result";

function conversationIdOf(args: Record<string, unknown>): string {
  return String(args.conversation_id ?? "").trim();
}

export async function opProcessStart(
  root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const conversationId = conversationIdOf(args);
  const command = String(args.command ?? "");
  const cwdArg =
    args.cwd == null || args.cwd === "" ? undefined : String(args.cwd);
  const cwdRes = await resolveProcessCwd(root, cwdArg);
  if (!cwdRes.ok) return opErr("WorkspaceIOError", cwdRes.detail);

  const waitFor =
    args.wait_for == null || args.wait_for === ""
      ? undefined
      : String(args.wait_for);
  const waitTimeout =
    args.wait_timeout_seconds == null
      ? undefined
      : Number(args.wait_timeout_seconds);
  const name =
    args.name == null || args.name === "" ? undefined : String(args.name);

  const result = await processService.start({
    conversation_id: conversationId,
    command,
    cwd: cwdRes.cwd,
    name,
    wait_for: waitFor,
    wait_timeout_seconds: waitTimeout,
  });
  if (!result.ok) return opErr(result.error.kind, result.error.detail);
  return opOk(result.value);
}

export async function opProcessRead(
  _root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const processId = String(args.process_id ?? "").trim();
  if (!processId) return opErr("WorkspaceIOError", "缺少 process_id");

  const waitFor =
    args.wait_for == null || args.wait_for === ""
      ? undefined
      : String(args.wait_for);
  const waitTimeout =
    args.wait_timeout_seconds == null
      ? undefined
      : Number(args.wait_timeout_seconds);
  const tailLines =
    args.tail_lines == null ? undefined : Number(args.tail_lines);

  // 用户终端：可读（strip ANSI）；wait_for 对当前 buffer 立即匹配（不阻塞等用户输入）。
  const ptyValue = ptyService.readAsProcess(processId, tailLines);
  if (ptyValue) {
    if (waitFor) {
      let matched = false;
      try {
        matched = new RegExp(waitFor).test(ptyValue.output);
      } catch {
        return opErr("WorkspaceIOError", `非法 wait_for 正则：${waitFor}`);
      }
      return opOk({ ...ptyValue, matched });
    }
    return opOk(ptyValue);
  }

  const result = await processService.read({
    process_id: processId,
    wait_for: waitFor,
    wait_timeout_seconds: waitTimeout,
    tail_lines: tailLines,
  });
  if (!result.ok) return opErr(result.error.kind, result.error.detail);
  return opOk(result.value);
}

export async function opProcessStop(
  _root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const processId = String(args.process_id ?? "").trim();
  if (!processId) return opErr("WorkspaceIOError", "缺少 process_id");

  const rejected = ptyService.rejectStopIfUserTerminal(processId);
  if (rejected && !rejected.ok) {
    return opErr(rejected.error.kind, rejected.error.detail);
  }

  const value = processService.stop(processId);
  if (!value) return opErr("WorkspaceIOError", "进程不存在或已清理");
  return opOk(value);
}

export async function opProcessList(
  _root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const conversationId = conversationIdOf(args);
  if (!conversationId) {
    return opErr("WorkspaceIOError", "缺少 conversation_id");
  }
  const bg = processService.list(conversationId);
  const user = ptyService.listAsProcessItems(conversationId);
  const processes = [...bg.processes, ...user].sort((a, b) =>
    a.started_at.localeCompare(b.started_at),
  );
  return opOk({ processes });
}
