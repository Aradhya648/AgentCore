import type { ExecutionStatus, RunStatus } from "./types";

/**
 * Single source for run / execution lifecycle copy (停止与中断呈现).
 * `cancelled` is always「已停止」— graph face, board overlay, and detail badges
 * must not drift to「已取消」.
 */
export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  pending: "排队中",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已停止",
  skipped: "未执行",
};

export function runStatusLabel(status: RunStatus): string {
  return RUN_STATUS_LABEL[status] ?? status;
}

export function executionStatusLabel(status: ExecutionStatus): string {
  switch (status) {
    case "running":
      return "进行中";
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    case "cancelled":
      return "已停止";
    case "paused":
      return "已暂停";
    default:
      return "准备中";
  }
}
