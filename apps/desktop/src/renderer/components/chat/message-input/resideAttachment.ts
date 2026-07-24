/**
 * 引用即驻留：把用户选中的文件落到对话工作区 ``attachments/``（本地直写 /
 * 云端 PUT），返回可塞进 PendingAttachment 的字段。绝对路径不进本模块状态。
 */

import { resolveConversationLocalTarget } from "@/services/sidecarRouting";
import { uploadWorkspaceFile } from "@/services/workspace";
import { getWorkspaceBinding } from "@/services/workspaceBinding";
import type {
  StageAttachmentDest,
  StagedAttachment,
} from "@shared/ipc-contract";

export type ResideResult =
  | {
      ok: true;
      name: string;
      /** 展示用相对路径（工作区 ``attachments/…`` 或文件名）。 */
      path: string;
      text: string;
      truncated: boolean;
      binary: boolean;
      workspacePath?: string;
      stagingId?: string;
    }
  | { ok: false; reason: string };

function destFromTarget(t: {
  rootId: string;
  subpath: string;
}): StageAttachmentDest {
  return { rootId: t.rootId, subpath: t.subpath || undefined };
}

/** 已有会话时解析本地落盘目标；云端 / 草稿 → null（走暂存）。 */
export async function resolveAttachDest(
  conversationId: string | null,
): Promise<StageAttachmentDest | null> {
  if (!conversationId || !window.fsApi) return null;
  try {
    const binding = await getWorkspaceBinding(conversationId);
    if (binding.mode !== "local") return null;
  } catch {
    return null;
  }
  const target = await resolveConversationLocalTarget(conversationId);
  if (!target) return null;
  return destFromTarget(target);
}

function fromStaged(s: StagedAttachment): ResideResult {
  return {
    ok: true,
    name: s.name,
    path: s.workspacePath ?? s.name,
    text: s.text,
    truncated: s.truncated,
    binary: s.binary,
    workspacePath: s.workspacePath,
    stagingId: s.stagingId,
  };
}

/** 回形针：系统文件选择器。取消 → null。 */
export async function pickLocalFileAttachment(
  conversationId: string | null,
): Promise<ResideResult | null> {
  if (!window.fsApi?.pickAndStageAttachment) {
    return { ok: false, reason: "当前环境无法附加本机文件" };
  }
  const dest = await resolveAttachDest(conversationId);
  const res = await window.fsApi.pickAndStageAttachment(dest ?? undefined);
  if (res === null) return null;
  if (!res.ok) return { ok: false, reason: res.reason };
  return fromStaged(res.data);
}

/** @ 菜单：已授权根内相对路径（含二进制）。 */
export async function stageRootFileAttachment(
  conversationId: string | null,
  rootId: string,
  relPath: string,
): Promise<ResideResult> {
  if (!window.fsApi?.stageFromRoot) {
    return { ok: false, reason: "当前环境无法附加本机文件" };
  }
  const dest = await resolveAttachDest(conversationId);
  const res = await window.fsApi.stageFromRoot(
    rootId,
    relPath,
    dest ?? undefined,
  );
  if (!res.ok) return { ok: false, reason: res.reason };
  return fromStaged(res.data);
}

/** 拖拽 / 粘贴。 */
export async function stageDroppedFileAttachment(
  conversationId: string | null,
  file: File,
): Promise<ResideResult> {
  if (!window.fsApi?.stageDroppedFile) {
    return { ok: false, reason: "当前环境无法附加本机文件" };
  }
  const dest = await resolveAttachDest(conversationId);
  const res = await window.fsApi.stageDroppedFile(file, dest ?? undefined);
  if (!res.ok) return { ok: false, reason: res.reason };
  return fromStaged(res.data);
}

/**
 * 发送前：暂存件写入本地工作区，或上传到云端工作区。
 * 已有 ``workspacePath`` 的跳过。失败返回 reason。
 */
export async function ensureAttachmentResident(
  conversationId: string,
  att: {
    name: string;
    stagingId?: string;
    workspacePath?: string;
    binary?: boolean;
    text: string;
    truncated: boolean;
  },
): Promise<
  | {
      ok: true;
      workspacePath: string;
      name: string;
      binary: boolean;
      text: string;
      truncated: boolean;
    }
  | { ok: false; reason: string }
> {
  if (att.workspacePath) {
    return {
      ok: true,
      workspacePath: att.workspacePath,
      name: att.name,
      binary: !!att.binary,
      text: att.text,
      truncated: att.truncated,
    };
  }
  if (!att.stagingId) {
    // 纯文本旧路径（对话引用等）：无驻留字节。
    return {
      ok: true,
      workspacePath: "",
      name: att.name,
      binary: false,
      text: att.text,
      truncated: att.truncated,
    };
  }

  const dest = await resolveAttachDest(conversationId);
  if (dest && window.fsApi?.finalizeStagedAttachment) {
    const res = await window.fsApi.finalizeStagedAttachment(
      att.stagingId,
      dest,
    );
    if (!res.ok) return { ok: false, reason: res.reason };
    const workspacePath = res.data.workspacePath;
    if (typeof workspacePath !== "string") {
      return { ok: false, reason: "附件落盘未返回工作区路径" };
    }
    return {
      ok: true,
      workspacePath,
      name: res.data.name,
      binary: res.data.binary,
      text: res.data.text,
      truncated: res.data.truncated,
    };
  }

  // 本地模式但本机根不可用：勿误走云端 PUT（会 409）。
  try {
    const binding = await getWorkspaceBinding(conversationId);
    if (binding.mode === "local") {
      return {
        ok: false,
        reason: "本地工作区目录不可用，请重新打开文件夹后再附加",
      };
    }
  } catch {
    /* binding unknown — try cloud upload */
  }

  // 云端工作区：取出字节 PUT。
  if (!window.fsApi?.consumeStagedBytes) {
    return { ok: false, reason: "无法将附件上传到云端工作区" };
  }
  const consumed = await window.fsApi.consumeStagedBytes(att.stagingId);
  if (!consumed.ok) return { ok: false, reason: consumed.reason };
  const workspacePath = `attachments/${consumed.data.name}`;
  try {
    await uploadWorkspaceFile(
      conversationId,
      workspacePath,
      new Blob([new Uint8Array(consumed.data.data)]),
    );
  } catch (e) {
    return {
      ok: false,
      reason: e instanceof Error ? e.message : "上传附件到云端工作区失败",
    };
  }
  return {
    ok: true,
    workspacePath,
    name: consumed.data.name,
    binary: consumed.data.binary,
    text: att.text,
    truncated: att.truncated,
  };
}
