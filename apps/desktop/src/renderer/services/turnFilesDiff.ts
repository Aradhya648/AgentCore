/**
 * A1+ 回合文件真 diff —— 云端 REST / 本机 sidecar RPC。
 * 无基线 / 失败时 ``available=false``，桌面降级工具参数预览。
 */

import { api } from "@/services/api";

export type TurnChangeType = "added" | "modified" | "deleted";

export interface TurnFileChange {
  path: string;
  changeType: TurnChangeType;
  baseSha: string | null;
  resultSha: string | null;
  isBinary: boolean;
  content: string | null;
  sizeBytes: number;
  baseContent: string | null;
}

export interface TurnFilesDiff {
  messageId: string;
  baselineSnapshotId: string | null;
  available: boolean;
  changes: TurnFileChange[];
  total: number;
  added: number;
  modified: number;
  deleted: number;
}

export interface LocalTurnFilesTarget {
  rootId: string;
  subpath?: string;
}

interface WireChange {
  path: string;
  change_type: TurnChangeType;
  base_sha: string | null;
  result_sha: string | null;
  is_binary: boolean;
  content: string | null;
  size_bytes: number;
  base_content?: string | null;
}

interface WireDiff {
  message_id: string;
  baseline_snapshot_id: string | null;
  available: boolean;
  data: WireChange[];
  total: number;
  added: number;
  modified: number;
  deleted: number;
}

function mapChange(c: WireChange): TurnFileChange {
  return {
    path: c.path,
    changeType: c.change_type,
    baseSha: c.base_sha,
    resultSha: c.result_sha,
    isBinary: c.is_binary,
    content: c.content,
    sizeBytes: c.size_bytes,
    baseContent: c.base_content ?? null,
  };
}

function fromWire(raw: WireDiff): TurnFilesDiff {
  return {
    messageId: raw.message_id,
    baselineSnapshotId: raw.baseline_snapshot_id,
    available: raw.available,
    changes: (raw.data ?? []).map(mapChange),
    total: raw.total,
    added: raw.added,
    modified: raw.modified,
    deleted: raw.deleted,
  };
}

/** Cloud path: ``GET …/messages/{id}/files/diff``. */
export async function getTurnFilesDiff(
  conversationId: string,
  messageId: string,
): Promise<TurnFilesDiff> {
  const raw = await api.get<WireDiff>(
    `/v1/conversations/${conversationId}/messages/${messageId}/files/diff`,
  );
  return fromWire(raw);
}

/** Local path: sidecar RPC over `.agentcore/baselines/{messageId}.zip` (no cloud). */
export async function getLocalTurnFilesDiff(
  target: LocalTurnFilesTarget,
  messageId: string,
): Promise<TurnFilesDiff> {
  const raw = await window.sidecarApi.turnFilesDiff({
    rootId: target.rootId,
    subpath: target.subpath,
    messageId,
  });
  return fromWire(raw);
}

/** Local A2′ restore via sidecar unzip (never cloud restoreSnapshot). */
export async function restoreLocalTurnBaseline(
  target: LocalTurnFilesTarget,
  snapshotId: string,
): Promise<void> {
  await window.sidecarApi.restoreTurnBaseline({
    rootId: target.rootId,
    subpath: target.subpath,
    snapshotId,
  });
}
