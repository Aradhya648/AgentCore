// 回合产物盘点 —— 聊天内联「本回合产出文件」卡的纯数据源（手机端全新实现，对标桌面
// lib/fileArtifacts.ts 语义；cross-platform-frontend.mdc：各端自建实现，仅共享契约类型）。
//
// 主清单（块 1）：只认 ``delivery_status.artifacts``（accepted+rejected 验收态）。
// 无该字段 / 空数组 → 空清单（不 silent 降级扫工具列表）。
//
// 工具列表（process / events）仍供旁路盘点：写/改/删/移经 builtin file_ops。
//   - 单聊（含历史 runs.process）从已折好的 process 时间线读 tool 步；
//   - 实时回合 / 多 Agent（含历史 runs.events 日志）从原始 tool_use_start↔tool_use_end 事件
//     按 tool_call_id 配对读 —— captain 与 worker 的工具都走这两类事件。
// 主清单不把工具名当交付成功。
//
// 手机 parity=simplified：无「查看改动」完整面；清单 + 深链文件页即可。
//
// 纯函数、只读运行时态/事件，不碰协议 fold（故不触发 conformance、零持久化）。卡片只把
// 「文件去哪了」可视化，真相仍以工作区文件树为准。

import type {
  DeliveryStatusPayload,
  ProcessStep,
  SSEEvent,
  ToolUseEndPayload,
  ToolUseStartPayload,
} from "@agentcore/contract-types";

/** 文件变更类型 —— 决定图标 / 文案 / 是否可预览（删除态无文件可看）。 */
export type FileOp = "write" | "edit" | "delete" | "move";

/** 路径级验收态（delivery_status.artifacts）。 */
export type ArtifactAcceptance = "accepted" | "rejected";

export interface FileArtifact {
  /** 变更后的路径（move 取目的地，其余取 path）；同时作为回合内去重键。 */
  path: string;
  /** 展示用文件名（path 的 basename）。 */
  name: string;
  /** 工具源才有；验收源可缺（主清单不再用写入/编辑标签）。 */
  op?: FileOp;
  /** 仅 move：源路径，用于「源 → 目的」展示。 */
  fromPath?: string;
  /** 路径验收态（有则主清单显示已验收/未通过，不显示写入/编辑）。 */
  acceptance?: ArtifactAcceptance;
  acceptanceReason?: string;
  acceptanceDetail?: string;
}

/**
 * 写文件的 builtin 工具名 → 变更类型。只读工具（file_read / list 等）与未知/外部工具不在
 * 表内 —— 它们不产出文件，不进卡。
 */
const OP_BY_TOOL: Record<string, FileOp> = {
  file_write: "write",
  file_append: "write",
  str_replace: "edit",
  file_delete: "delete",
  file_move: "move",
};

function basename(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

function asStr(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** 把一次工具调用映射成文件产物；非文件工具 / 未成功 / 缺路径 → null（不进卡）。 */
function artifactFromTool(
  toolName: string,
  args: Record<string, unknown>,
  succeeded: boolean,
): FileArtifact | null {
  if (!succeeded) return null;
  const op = OP_BY_TOOL[toolName];
  if (!op) return null;
  if (op === "move") {
    const to = asStr(args.destination);
    if (!to) return null;
    const from = asStr(args.source);
    return { path: to, name: basename(to), op, fromPath: from || undefined };
  }
  const path = asStr(args.path);
  if (!path) return null;
  return { path, name: basename(path), op };
}

/**
 * 按最终路径折叠：同一文件回合内多次改只留最后一次动作（= 回合终态），保留首见顺序。
 * 幂等，故可对已去重的列表再 merge 而不出错。
 */
function dedupe(ordered: FileArtifact[]): FileArtifact[] {
  const byPath = new Map<string, FileArtifact>();
  const order: string[] = [];
  for (const a of ordered) {
    if (!byPath.has(a.path)) order.push(a.path);
    byPath.set(a.path, a);
  }
  return order.map((p) => byPath.get(p) as FileArtifact);
}

/**
 * 主清单：有 ``deliveryStatus.artifacts`` 字段时用之（含空数组）；
 * 缺字段 → null（调用方应视为空，勿再扫工具列表）。draft 不进卡。
 */
export function fileArtifactsFromDeliveryStatus(
  deliveryStatus: DeliveryStatusPayload | null | undefined,
): FileArtifact[] | null {
  if (!deliveryStatus || !Array.isArray(deliveryStatus.artifacts)) return null;
  const out: FileArtifact[] = [];
  for (const row of deliveryStatus.artifacts) {
    const path = asStr(row.path).trim();
    if (!path) continue;
    const status = row.status;
    if (status !== "accepted" && status !== "rejected") continue;
    out.push({
      path,
      name: basename(path),
      acceptance: status,
      acceptanceReason: row.reason,
      acceptanceDetail: row.detail,
    });
  }
  return dedupe(out);
}

/** 单聊：从内联过程时间线（fold 的 process / 历史 runs.process）抽成功的文件变更。 */
export function fileArtifactsFromProcess(
  process: ProcessStep[] | undefined,
): FileArtifact[] {
  if (!process?.length) return [];
  const out: FileArtifact[] = [];
  for (const step of process) {
    if (step.kind !== "tool") continue;
    const a = artifactFromTool(
      step.tool_name,
      step.arguments,
      step.status === "success",
    );
    if (a) out.push(a);
  }
  return dedupe(out);
}

/**
 * 实时回合 / 多 Agent：从原始事件按 tool_call_id 配对 tool_use_start（带 arguments）→
 * tool_use_end（带 status）抽成功的文件变更。captain 与 worker 的工具都走这两类事件，故
 * 一次扫描即覆盖全部调用方。
 */
export function fileArtifactsFromEvents(events: SSEEvent[]): FileArtifact[] {
  const startById = new Map<
    string,
    { toolName: string; args: Record<string, unknown> }
  >();
  const out: FileArtifact[] = [];
  for (const ev of events) {
    if (ev.type === "tool_use_start") {
      const p = ev.payload as ToolUseStartPayload;
      startById.set(p.tool_call_id, {
        toolName: p.tool_name,
        args: p.arguments,
      });
    } else if (ev.type === "tool_use_end") {
      const p = ev.payload as ToolUseEndPayload;
      const start = startById.get(p.tool_call_id);
      if (!start) continue;
      const a = artifactFromTool(
        start.toolName,
        start.args,
        p.status === "success",
      );
      if (a) out.push(a);
    }
  }
  return dedupe(out);
}

/** 合并多个来源（如历史回合的 process + events）后统一去重。 */
export function mergeArtifacts(...lists: FileArtifact[][]): FileArtifact[] {
  return dedupe(lists.flat());
}

/** 主清单解析：只认验收 artifacts；缺字段 / 空 → []（不降级工具列表）。 */
export function resolveFileArtifactsForCard(
  deliveryStatus: DeliveryStatusPayload | null | undefined,
): FileArtifact[] {
  return fileArtifactsFromDeliveryStatus(deliveryStatus) ?? [];
}
