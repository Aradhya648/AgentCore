import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import { basename, join } from "node:path";
import {
  FS_CHANNELS,
  type FsResult,
  type FsRoot,
  type FsWriteInput,
  type FsWriteResult,
  type WorkspaceOpName,
} from "@shared/ipc-contract";
import { BrowserWindow, app, dialog, ipcMain } from "electron";
import { isRecord, requireStringFields } from "../ipc-validate";
import { checkoutArchive, previewArchive } from "./checkout";
import {
  confirmOpenPath,
  grantSessionRun,
  requiresOpenConfirm,
} from "./execGate";
import { coerceIpcBytes } from "./ipcBytes";
import { readFile, readTextFile, writeTextFile } from "./preview";
import {
  clearSessionRoots,
  deleteRoot,
  ensureReady,
  findRootByAbsPath,
  getAllRoots,
  initRoots,
  listSessionRoots,
  revokeSessionRoot,
  saveRoots,
  setRoot,
} from "./roots";
import { saveBytesToDisk } from "./save";
import { copyPath, openWithDefaultApp, reveal, trashPath } from "./shell";
import {
  type StageDest,
  consumeStagedBytes,
  finalizeStagedAttachment,
  pickAndStageAttachment,
  stageFromAbsPath,
  stageFromRoot,
} from "./stageAttachment";
import { copy, create, listDir, listFiles, move, remove, rename } from "./tree";
import { closeWatchersForRoot, unwatchDir, watchDir } from "./watch";
import { workspaceOp } from "./workspace/dispatch";
import { opErr } from "./workspace/result";

function parseStageDest(p: unknown): StageDest | undefined {
  if (!isRecord(p)) return undefined;
  const dest = p.dest;
  if (!isRecord(dest) || typeof dest.rootId !== "string" || !dest.rootId) {
    return undefined;
  }
  return {
    rootId: dest.rootId,
    subpath: typeof dest.subpath === "string" ? dest.subpath : undefined,
  };
}

// IPC-004（第五轮 IPC 权限面审计）：边界结构校验失败时回给 renderer 的统一信封。畸形入参
// 仅可能来自被攻破的 renderer——正常 renderer 由共享 TS 契约保证形状。各句柄按其契约回应：
// 判别式 `FsResult`/`FsWriteResult` 句柄返回 `{ok:false}`，workspaceOp 返回 `opErr`。
const INVALID_ARGS = "无效的请求参数";
const invalidFsResult = (): FsResult<never> => ({
  ok: false,
  reason: INVALID_ARGS,
  code: "invalid",
});
const invalidWriteResult = (): FsWriteResult => ({
  ok: false,
  reason: "error",
  message: INVALID_ARGS,
});

/** 注册全部 fs IPC handler。须在 app ready 后调用。 */
export function registerFsIpc(): void {
  initRoots();

  ipcMain.handle(FS_CHANNELS.addRoot, async (): Promise<FsRoot | null> => {
    await ensureReady();
    const win =
      BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
    const result = win
      ? await dialog.showOpenDialog(win, { properties: ["openDirectory"] })
      : await dialog.showOpenDialog({ properties: ["openDirectory"] });
    if (result.canceled || result.filePaths.length === 0) return null;

    let absPath: string;
    try {
      absPath = await fs.realpath(result.filePaths[0]);
    } catch {
      absPath = result.filePaths[0];
    }

    const existing = findRootByAbsPath(absPath);
    if (existing && !existing.sessionOnly)
      return { id: existing.id, name: existing.name };

    const id = randomUUID();
    const name = basename(absPath) || absPath;
    setRoot({ id, name, absPath });
    await saveRoots();
    return { id, name };
  });

  // 桌面默认本地容器根（双模式工作区 §八.7）：显式「本机草稿」裸聊与本地项目创建
  // 复用；新建裸聊默认已切云，不再自动调用。幂等：已存在同路径的根则复用。
  ipcMain.handle(FS_CHANNELS.ensureDefaultRoot, async (): Promise<FsRoot> => {
    await ensureReady();
    const base = join(app.getPath("documents"), "AgentCore");
    await fs.mkdir(base, { recursive: true });
    let absPath: string;
    try {
      absPath = await fs.realpath(base);
    } catch {
      absPath = base;
    }
    const existing = findRootByAbsPath(absPath);
    if (existing && !existing.sessionOnly)
      return { id: existing.id, name: existing.name };

    const id = randomUUID();
    const name = basename(absPath) || absPath;
    setRoot({ id, name, absPath });
    await saveRoots();
    return { id, name };
  });

  // 云 scratch → 本地单向 checkout（§八.7）：弹目录 + 解压 zip，不登记根。
  ipcMain.handle(FS_CHANNELS.checkoutArchive, async (_e, p: unknown) => {
    if (!isRecord(p) || typeof p.archiveBase64 !== "string") {
      return {
        ok: false as const,
        reason: "error" as const,
        message: INVALID_ARGS,
      };
    }
    return checkoutArchive(p.archiveBase64);
  });

  // 单文件「另存为」：弹保存对话框 + 原子落盘（桌面端 saveBlob 的落盘后端）。
  // IPC 结构化克隆可能把 Uint8Array 还原成 ArrayBuffer / TypedArray view。
  ipcMain.handle(FS_CHANNELS.saveFile, async (e, p: unknown) => {
    const bytes = isRecord(p) ? coerceIpcBytes(p.bytes) : null;
    if (!isRecord(p) || typeof p.suggestedName !== "string" || !bytes) {
      return {
        ok: false as const,
        reason: "error" as const,
        message: INVALID_ARGS,
      };
    }
    return saveBytesToDisk(
      p.suggestedName,
      bytes,
      BrowserWindow.fromWebContents(e.sender),
    );
  });

  // 「在浏览器打开」：解压 zip 到临时目录并用系统默认程序打开指定文件（§八.7 预览侧）。
  ipcMain.handle(FS_CHANNELS.previewArchive, async (_e, p: unknown) => {
    if (
      !isRecord(p) ||
      typeof p.archiveBase64 !== "string" ||
      typeof p.openRelPath !== "string"
    ) {
      return {
        ok: false as const,
        reason: "error" as const,
        message: INVALID_ARGS,
      };
    }
    return previewArchive(p.archiveBase64, p.openRelPath);
  });

  ipcMain.handle(FS_CHANNELS.listRoots, async (): Promise<FsRoot[]> => {
    await ensureReady();
    return getAllRoots().map((r) => ({ id: r.id, name: r.name }));
  });

  ipcMain.handle(FS_CHANNELS.removeRoot, async (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId"]);
    if (!args) return;
    await ensureReady();
    closeWatchersForRoot(args.rootId);
    deleteRoot(args.rootId);
    await saveRoots();
  });

  // W3/P1: session-scoped root (readonly | organize) — not persisted; bound to conversationId.
  ipcMain.handle(
    FS_CHANNELS.grantSessionReadonlyRoot,
    async (_e, p: unknown): Promise<FsRoot | null> => {
      const args = requireStringFields(p, ["conversationId"]);
      if (!args) return null;
      const modeRaw =
        p && typeof p === "object" && "mode" in p
          ? String((p as { mode?: unknown }).mode ?? "readonly")
          : "readonly";
      const mode: "readonly" | "organize" =
        modeRaw === "organize" ? "organize" : "readonly";
      await ensureReady();
      const win =
        BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
      const result = win
        ? await dialog.showOpenDialog(win, { properties: ["openDirectory"] })
        : await dialog.showOpenDialog({ properties: ["openDirectory"] });
      if (result.canceled || result.filePaths.length === 0) return null;

      let absPath: string;
      try {
        absPath = await fs.realpath(result.filePaths[0]);
      } catch {
        absPath = result.filePaths[0];
      }

      const name = basename(absPath) || absPath;
      const aliasBase =
        name.replace(/[^\w.-]+/g, "_").replace(/^[^A-Za-z]/, "d_") || "folder";
      const taken = new Set(
        listSessionRoots(args.conversationId)
          .map((r) => r.alias)
          .filter(Boolean) as string[],
      );
      let alias = aliasBase.slice(0, 64);
      let n = 2;
      while (taken.has(alias)) {
        alias = `${aliasBase.slice(0, 60)}_${n}`;
        n += 1;
      }

      // Same abs path: upgrade/downgrade mode (re-auth card already shown by client).
      const same = listSessionRoots(args.conversationId).find(
        (r) => r.absPath === absPath,
      );
      if (same) {
        setRoot({
          ...same,
          mode,
          readonly: mode === "readonly",
        });
        return {
          id: same.id,
          name: same.name,
          alias: same.alias,
          mode,
          readonly: mode === "readonly",
          sessionOnly: true,
        };
      }

      const id = randomUUID();
      setRoot({
        id,
        name,
        absPath,
        sessionOnly: true,
        conversationId: args.conversationId,
        mode,
        readonly: mode === "readonly",
        alias,
      });
      // Not persisted — sessionOnly filtered out of saveRoots.
      return {
        id,
        name,
        alias,
        mode,
        readonly: mode === "readonly",
        sessionOnly: true,
      };
    },
  );

  ipcMain.handle(
    FS_CHANNELS.listSessionReadonlyRoots,
    async (_e, p: unknown): Promise<FsRoot[]> => {
      const args = requireStringFields(p, ["conversationId"]);
      if (!args) return [];
      await ensureReady();
      return listSessionRoots(args.conversationId).map((r) => ({
        id: r.id,
        name: r.name,
        alias: r.alias,
        mode: r.mode ?? (r.readonly ? "readonly" : undefined),
        readonly: r.readonly ?? r.mode === "readonly",
        sessionOnly: true,
      }));
    },
  );

  ipcMain.handle(
    FS_CHANNELS.revokeSessionReadonlyRoot,
    async (_e, p: unknown): Promise<boolean> => {
      const args = requireStringFields(p, ["conversationId", "rootId"]);
      if (!args) return false;
      await ensureReady();
      closeWatchersForRoot(args.rootId);
      return revokeSessionRoot(args.conversationId, args.rootId);
    },
  );

  ipcMain.handle(
    FS_CHANNELS.clearSessionReadonlyRoots,
    async (_e, p: unknown): Promise<void> => {
      const args = requireStringFields(p, ["conversationId"]);
      if (!args) return;
      await ensureReady();
      for (const id of clearSessionRoots(args.conversationId)) {
        closeWatchersForRoot(id);
      }
    },
  );

  ipcMain.handle(FS_CHANNELS.listDir, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return listDir(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.listFiles, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId"]);
    if (!args) return invalidFsResult();
    return listFiles(args.rootId);
  });

  ipcMain.handle(FS_CHANNELS.readFile, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return readFile(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.readTextFile, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return readTextFile(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.writeFile, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidWriteResult();
    // 只在边界校验 input 为对象（薄层）；content/encoding/eol/baselineMtimeMs 的取值语义
    // 仍由下游 writeTextFile 负责，故此处经 unknown 双断言到契约类型。
    const input = isRecord(p) ? p.input : undefined;
    if (!isRecord(input)) return invalidWriteResult();
    return writeTextFile(
      args.rootId,
      args.relPath,
      input as unknown as FsWriteInput,
    );
  });

  ipcMain.handle(FS_CHANNELS.rename, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath", "newName"]);
    if (!args) return invalidFsResult();
    return rename(args.rootId, args.relPath, args.newName);
  });

  ipcMain.handle(FS_CHANNELS.move, (_e, p: unknown) => {
    const args = requireStringFields(p, [
      "rootId",
      "srcRelPath",
      "destRelPath",
    ]);
    if (!args) return invalidFsResult();
    return move(args.rootId, args.srcRelPath, args.destRelPath);
  });

  ipcMain.handle(FS_CHANNELS.copy, (_e, p: unknown) => {
    const args = requireStringFields(p, [
      "rootId",
      "srcRelPath",
      "destRelPath",
    ]);
    if (!args) return invalidFsResult();
    return copy(args.rootId, args.srcRelPath, args.destRelPath);
  });

  ipcMain.handle(FS_CHANNELS.create, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    const kind = isRecord(p) ? p.kind : undefined;
    if (kind !== "file" && kind !== "dir") return invalidFsResult();
    return create(args.rootId, args.relPath, kind);
  });

  ipcMain.handle(FS_CHANNELS.delete, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return remove(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.watch, (e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return;
    watchDir(e.sender, args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.unwatch, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return;
    unwatchDir(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.workspaceOp, async (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "op"]);
    if (!args) return opErr("WorkspaceIOError", INVALID_ARGS);
    const opArgs = isRecord(p) ? p.args : undefined;
    if (!isRecord(opArgs)) return opErr("WorkspaceIOError", INVALID_ARGS);
    // execute：聊天审批卡是唯一人门（`workspace_op_required` 仅在后端 ApprovalGate 放行后
    // 触发）。不再叠主侧 native「即将运行 python」框——对标 Cursor 单一确认面。
    // native 门仅保留 openPath + 未带 rendererConfirmed 的 bash 兜底（见 terminal-service）。
    return workspaceOp({
      rootId: args.rootId,
      op: args.op as WorkspaceOpName,
      args: opArgs,
    });
  });

  // 聊天内 RunConfirm「本会话都允许」→ 主进程 session flag（进程重启清零）。
  ipcMain.handle(FS_CHANNELS.grantSessionRun, () => {
    grantSessionRun();
  });

  ipcMain.handle(FS_CHANNELS.reveal, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return reveal(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.openPath, async (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    // IPC-002（第五轮 IPC 权限面审计 + 红队 2026-06-30）：用 OS 关联打开 = 经文件关联执行，是第二
    // 个 RCE 头（write→openPath 可绕过 execute 的审批）。改用**白名单姿态**：仅「已知安全类型」（文档
    // / 媒体 / 图片 / 文本 / 压缩包）直开零打扰，其余一律弹主侧确认——黑名单永远列不全、且 Windows 会
    // 抹掉文件名末尾点 / 空格使「假装无害」的名字仍被执行（E1/E2），白名单默认拒才治本。relPath 即分类
    // 依据（workspace ops 无建符号链接原语，被攻破的 renderer 无法造「安全扩展名→可执行」的链接错位）。
    if (
      requiresOpenConfirm(args.relPath) &&
      !(await confirmOpenPath(args.relPath))
    ) {
      return {
        ok: false,
        reason: "已取消（未确认打开该文件）",
        code: "invalid",
      };
    }
    return openWithDefaultApp(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.copyPath, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return copyPath(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.trashPath, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return trashPath(args.rootId, args.relPath);
  });

  ipcMain.handle(FS_CHANNELS.pickAndStageAttachment, (_e, p: unknown) => {
    return pickAndStageAttachment(parseStageDest(p));
  });

  ipcMain.handle(FS_CHANNELS.stageFromRoot, (_e, p: unknown) => {
    const args = requireStringFields(p, ["rootId", "relPath"]);
    if (!args) return invalidFsResult();
    return stageFromRoot(args.rootId, args.relPath, parseStageDest(p));
  });

  ipcMain.handle(FS_CHANNELS.stageFromAbsPath, (_e, p: unknown) => {
    const args = requireStringFields(p, ["absPath"]);
    if (!args) return invalidFsResult();
    return stageFromAbsPath(args.absPath, parseStageDest(p));
  });

  ipcMain.handle(FS_CHANNELS.finalizeStagedAttachment, (_e, p: unknown) => {
    const args = requireStringFields(p, ["stagingId"]);
    if (!args) return invalidFsResult();
    const dest = parseStageDest(p);
    if (!dest) return invalidFsResult();
    return finalizeStagedAttachment(args.stagingId, dest);
  });

  ipcMain.handle(FS_CHANNELS.consumeStagedBytes, async (_e, p: unknown) => {
    const args = requireStringFields(p, ["stagingId"]);
    if (!args) return invalidFsResult();
    return consumeStagedBytes(args.stagingId);
  });
}
