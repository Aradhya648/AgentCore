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
import { TEXT_PREVIEW_CAP } from "./composerAttachments";

/** Align with main-process ``ATTACH_MAX_BYTES`` / IM ChatComposer. */
export const ATTACH_MAX_BYTES = 25 * 1024 * 1024;

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
      /** 浏览器草稿：无会话时持 File，发送时再 PUT。 */
      fileBlob?: File;
    }
  | { ok: false; reason: string };

/** Align with main-process ``safeName`` (basename + strip leading dots). */
export function safeBrowserFileName(name: string): string {
  const base = (name || "")
    .replace(/\\/g, "/")
    .trim()
    .split("/")
    .pop()!
    .replace(/^\.+/, "");
  return base || "attachment";
}

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
 * 浏览器：回形针 / 拖贴共用。校验图片与大小；有会话则立即云端 PUT，
 * 无会话则持 ``fileBlob`` 到发送。允许二进制（docx/pdf 等）。
 */
export async function prepareBrowserFileAttachment(
  conversationId: string | null,
  file: File,
): Promise<ResideResult> {
  if (file.type.startsWith("image/")) {
    return { ok: false, reason: "暂不支持图片附件（模型尚无视觉能力）" };
  }
  if (file.size > ATTACH_MAX_BYTES) {
    return {
      ok: false,
      reason: `文件超过 ${Math.round(ATTACH_MAX_BYTES / (1024 * 1024))}MB 上限`,
    };
  }

  const name = safeBrowserFileName(file.name);
  const head = await file.slice(0, TEXT_PREVIEW_CAP + 1).arrayBuffer();
  const bytes = new Uint8Array(head);
  const binary = bytes.includes(0);
  const truncated = !binary && file.size > TEXT_PREVIEW_CAP;
  const text = binary
    ? ""
    : new TextDecoder("utf-8").decode(
        bytes.subarray(0, Math.min(bytes.length, TEXT_PREVIEW_CAP)),
      );

  if (!conversationId) {
    return {
      ok: true,
      name,
      path: name,
      text,
      truncated,
      binary,
      fileBlob: file,
    };
  }

  // 有会话：立即 PUT（引用即驻留）。本地 binding 在无本机根时不可用。
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

  const workspacePath = `attachments/${name}`;
  try {
    await uploadWorkspaceFile(conversationId, workspacePath, file);
  } catch (e) {
    return {
      ok: false,
      reason: e instanceof Error ? e.message : "上传附件到云端工作区失败",
    };
  }
  return {
    ok: true,
    name,
    path: workspacePath,
    text,
    truncated,
    binary,
    workspacePath,
  };
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
    fileBlob?: File;
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

  // 浏览器草稿 File → 云端 PUT。
  if (att.fileBlob) {
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
    const name = safeBrowserFileName(att.name);
    const workspacePath = `attachments/${name}`;
    try {
      await uploadWorkspaceFile(conversationId, workspacePath, att.fileBlob);
    } catch (e) {
      return {
        ok: false,
        reason: e instanceof Error ? e.message : "上传附件到云端工作区失败",
      };
    }
    return {
      ok: true,
      workspacePath,
      name,
      binary: !!att.binary,
      text: att.text,
      truncated: att.truncated,
    };
  }

  if (!att.stagingId) {
    if (att.binary) {
      return { ok: false, reason: "附件数据已失效，请重新附加" };
    }
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
