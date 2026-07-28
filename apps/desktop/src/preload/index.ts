import {
  AGENTTOWN_CHANNELS,
  type AgentTownApi,
} from "@shared/agenttown-contract";
import {
  BROWSER_CHANNELS,
  type BrowserApi,
  type BrowserNavState,
} from "@shared/browser-contract";
import {
  FS_CHANNELS,
  type FsApi,
  type FsChangedEvent,
  type FsResult,
  type StageAttachmentDest,
  type StagedAttachment,
} from "@shared/ipc-contract";
import {
  LOCAL_STORE_CHANNELS,
  type LocalStoreApi,
  type LocalStoreConversationPayload,
  type LocalStorePutShellMeta,
} from "@shared/local-store-contract";
import { LOG_CHANNELS, type LogApi } from "@shared/log-contract";
import {
  NOTIFICATION_CHANNELS,
  type NotificationApi,
} from "@shared/notification-contract";
import {
  HOST_CHANNELS,
  type HostApi,
} from "@shared/host-contract";
import {
  OUTBOX_CHANNELS,
  type OutboxApi,
  type OutboxSyncedPayload,
} from "@shared/outbox-contract";
import {
  PREVIEW_CHANNELS,
  type PreviewApi,
  type PreviewNavState,
} from "@shared/preview-contract";
import {
  PROCESS_CHANNELS,
  type ProcessApi,
  type ProcessEventPush,
} from "@shared/process-contract";
import {
  PTY_CHANNELS,
  type PtyApi,
  type PtyEventPush,
} from "@shared/pty-contract";
import {
  SIDECAR_CHANNELS,
  type SidecarApi,
  type SidecarEventPush,
  type SidecarStatusPush,
} from "@shared/sidecar-contract";
import { TERMINAL_CHANNELS, type TerminalApi } from "@shared/terminal-contract";
import {
  UPDATER_CHANNELS,
  type UpdaterApi,
  type UpdaterStatus,
} from "@shared/updater-contract";
import {
  WINDOW_CHANNELS,
  type WindowApi,
  type WindowFramePreset,
} from "@shared/window-contract";
import { contextBridge, ipcRenderer, webUtils } from "electron";

const agentTownApi: AgentTownApi = {
  writeSession: (input) =>
    ipcRenderer.invoke(AGENTTOWN_CHANNELS.writeSession, input),
  clearSession: () => ipcRenderer.invoke(AGENTTOWN_CHANNELS.clearSession),
  launch: (opts) => ipcRenderer.invoke(AGENTTOWN_CHANNELS.launch, opts),
};

const fsApi: FsApi = {
  addRoot: () => ipcRenderer.invoke(FS_CHANNELS.addRoot),
  ensureDefaultRoot: () => ipcRenderer.invoke(FS_CHANNELS.ensureDefaultRoot),
  checkoutArchive: (archiveBase64) =>
    ipcRenderer.invoke(FS_CHANNELS.checkoutArchive, { archiveBase64 }),
  saveFile: (suggestedName, bytes) =>
    ipcRenderer.invoke(FS_CHANNELS.saveFile, { suggestedName, bytes }),
  previewArchive: (archiveBase64, openRelPath) =>
    ipcRenderer.invoke(FS_CHANNELS.previewArchive, {
      archiveBase64,
      openRelPath,
    }),
  listRoots: () => ipcRenderer.invoke(FS_CHANNELS.listRoots),
  removeRoot: (rootId) =>
    ipcRenderer.invoke(FS_CHANNELS.removeRoot, { rootId }),
  grantSessionReadonlyRoot: (conversationId, mode) =>
    ipcRenderer.invoke(FS_CHANNELS.grantSessionReadonlyRoot, {
      conversationId,
      mode: mode ?? "readonly",
    }),
  listSessionReadonlyRoots: (conversationId) =>
    ipcRenderer.invoke(FS_CHANNELS.listSessionReadonlyRoots, {
      conversationId,
    }),
  revokeSessionReadonlyRoot: (conversationId, rootId) =>
    ipcRenderer.invoke(FS_CHANNELS.revokeSessionReadonlyRoot, {
      conversationId,
      rootId,
    }),
  clearSessionReadonlyRoots: (conversationId) =>
    ipcRenderer.invoke(FS_CHANNELS.clearSessionReadonlyRoots, {
      conversationId,
    }),
  listDir: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.listDir, { rootId, relPath }),
  listFiles: (rootId) => ipcRenderer.invoke(FS_CHANNELS.listFiles, { rootId }),
  readFile: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.readFile, { rootId, relPath }),
  readTextFile: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.readTextFile, { rootId, relPath }),
  writeFile: (rootId, relPath, input) =>
    ipcRenderer.invoke(FS_CHANNELS.writeFile, { rootId, relPath, input }),
  rename: (rootId, relPath, newName) =>
    ipcRenderer.invoke(FS_CHANNELS.rename, { rootId, relPath, newName }),
  move: (rootId, srcRelPath, destRelPath) =>
    ipcRenderer.invoke(FS_CHANNELS.move, { rootId, srcRelPath, destRelPath }),
  copy: (rootId, srcRelPath, destRelPath) =>
    ipcRenderer.invoke(FS_CHANNELS.copy, { rootId, srcRelPath, destRelPath }),
  create: (rootId, relPath, kind) =>
    ipcRenderer.invoke(FS_CHANNELS.create, { rootId, relPath, kind }),
  delete: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.delete, { rootId, relPath }),
  watch: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.watch, { rootId, relPath }),
  unwatch: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.unwatch, { rootId, relPath }),
  onChanged: (cb) => {
    const listener = (_e: unknown, payload: FsChangedEvent) => cb(payload);
    ipcRenderer.on(FS_CHANNELS.changed, listener);
    return () => ipcRenderer.removeListener(FS_CHANNELS.changed, listener);
  },
  workspaceOp: (rootId, op, args) =>
    ipcRenderer.invoke(FS_CHANNELS.workspaceOp, { rootId, op, args }),
  grantSessionRun: () => ipcRenderer.invoke(FS_CHANNELS.grantSessionRun),
  reveal: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.reveal, { rootId, relPath }),
  openPath: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.openPath, { rootId, relPath }),
  copyPath: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.copyPath, { rootId, relPath }),
  trashPath: (rootId, relPath) =>
    ipcRenderer.invoke(FS_CHANNELS.trashPath, { rootId, relPath }),
  pickAndStageAttachment: (dest) =>
    ipcRenderer.invoke(FS_CHANNELS.pickAndStageAttachment, { dest }),
  stageFromRoot: (rootId, relPath, dest) =>
    ipcRenderer.invoke(FS_CHANNELS.stageFromRoot, { rootId, relPath, dest }),
  stageDroppedFile: (file, dest) => {
    let absPath: string;
    try {
      absPath = webUtils.getPathForFile(file);
    } catch {
      return Promise.resolve({
        ok: false as const,
        reason: "无法读取拖入的文件，请改用回形针选择",
        code: "invalid" as const,
      } satisfies FsResult<StagedAttachment>);
    }
    if (!absPath) {
      return Promise.resolve({
        ok: false as const,
        reason: "无法读取拖入的文件，请改用回形针选择",
        code: "invalid" as const,
      } satisfies FsResult<StagedAttachment>);
    }
    return ipcRenderer.invoke(FS_CHANNELS.stageFromAbsPath, {
      absPath,
      dest,
    }) as Promise<FsResult<StagedAttachment>>;
  },
  finalizeStagedAttachment: (stagingId, dest: StageAttachmentDest) =>
    ipcRenderer.invoke(FS_CHANNELS.finalizeStagedAttachment, {
      stagingId,
      dest,
    }),
  consumeStagedBytes: (stagingId) =>
    ipcRenderer.invoke(FS_CHANNELS.consumeStagedBytes, { stagingId }),
};

const sidecarApi: SidecarApi = {
  startTurn: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.startTurn, req),
  cancel: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.cancel, req),
  respond: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.respond, req),
  runRedirect: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.runRedirect, req),
  debateSteer: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.debateSteer, req),
  resume: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.resume, req),
  probe: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.probe, req),
  recovery: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.recovery, req),
  attach: (req) => ipcRenderer.invoke(SIDECAR_CHANNELS.attach, req),
  turnFilesDiff: (req) =>
    ipcRenderer.invoke(SIDECAR_CHANNELS.turnFilesDiff, req),
  restoreTurnBaseline: (req) =>
    ipcRenderer.invoke(SIDECAR_CHANNELS.restoreTurnBaseline, req),
  listBrowserSessions: (req) =>
    ipcRenderer.invoke(SIDECAR_CHANNELS.listBrowserSessions, req),
  onEvent: (cb) => {
    const listener = (_e: unknown, payload: SidecarEventPush) => cb(payload);
    ipcRenderer.on(SIDECAR_CHANNELS.event, listener);
    return () => ipcRenderer.removeListener(SIDECAR_CHANNELS.event, listener);
  },
  onStatus: (cb) => {
    const listener = (_e: unknown, payload: SidecarStatusPush) => cb(payload);
    ipcRenderer.on(SIDECAR_CHANNELS.status, listener);
    return () => ipcRenderer.removeListener(SIDECAR_CHANNELS.status, listener);
  },
};

const localStoreApi: LocalStoreApi = {
  hasCache: () => ipcRenderer.invoke(LOCAL_STORE_CHANNELS.hasCache),
  getSnapshot: () => ipcRenderer.invoke(LOCAL_STORE_CHANNELS.getSnapshot),
  getConversation: (id: string) =>
    ipcRenderer.invoke(LOCAL_STORE_CHANNELS.getConversation, id),
  putOpenedConversation: (payload: LocalStoreConversationPayload) =>
    ipcRenderer.invoke(LOCAL_STORE_CHANNELS.putOpenedConversation, payload),
  putShellMeta: (meta: LocalStorePutShellMeta) =>
    ipcRenderer.invoke(LOCAL_STORE_CHANNELS.putShellMeta, meta),
  clear: () => ipcRenderer.invoke(LOCAL_STORE_CHANNELS.clear),
};

const outboxApi: OutboxApi = {
  flush: () => ipcRenderer.invoke(OUTBOX_CHANNELS.flush),
  flushTurn: (req) => ipcRenderer.invoke(OUTBOX_CHANNELS.flushTurn, req),
  status: () => ipcRenderer.invoke(OUTBOX_CHANNELS.status),
  onSynced: (cb) => {
    const listener = (_e: unknown, payload: OutboxSyncedPayload) => cb(payload);
    ipcRenderer.on(OUTBOX_CHANNELS.synced, listener);
    return () => ipcRenderer.removeListener(OUTBOX_CHANNELS.synced, listener);
  },
  authRefresh: () => ipcRenderer.invoke(OUTBOX_CHANNELS.authRefresh),
};

const updaterApi: UpdaterApi = {
  configure: (apiBaseUrl) =>
    ipcRenderer.invoke(UPDATER_CHANNELS.configure, apiBaseUrl),
  check: () => ipcRenderer.invoke(UPDATER_CHANNELS.check),
  quitAndInstall: () => ipcRenderer.invoke(UPDATER_CHANNELS.quitAndInstall),
  getStatus: () => ipcRenderer.invoke(UPDATER_CHANNELS.getStatus),
  onStatus: (cb) => {
    const listener = (_e: unknown, payload: UpdaterStatus) => cb(payload);
    ipcRenderer.on(UPDATER_CHANNELS.status, listener);
    return () => ipcRenderer.removeListener(UPDATER_CHANNELS.status, listener);
  },
};

const logApi: LogApi = {
  write: (entry) => ipcRenderer.send(LOG_CHANNELS.write, entry),
};

const terminalApi: TerminalApi = {
  runBash: (input) => ipcRenderer.invoke(TERMINAL_CHANNELS.runBash, input),
  openShellAtRoot: (rootId, subpath) =>
    ipcRenderer.invoke(TERMINAL_CHANNELS.openShellAtRoot, rootId, subpath),
};

const processApi: ProcessApi = {
  list: (req) => ipcRenderer.invoke(PROCESS_CHANNELS.list, req),
  stop: (req) => ipcRenderer.invoke(PROCESS_CHANNELS.stop, req),
  read: (req) => ipcRenderer.invoke(PROCESS_CHANNELS.read, req),
  killConversation: (req) =>
    ipcRenderer.invoke(PROCESS_CHANNELS.killConversation, req),
  onEvent: (cb) => {
    const listener = (_e: unknown, payload: ProcessEventPush) => cb(payload);
    ipcRenderer.on(PROCESS_CHANNELS.event, listener);
    return () => ipcRenderer.removeListener(PROCESS_CHANNELS.event, listener);
  },
};

const ptyApi: PtyApi = {
  spawn: (req) => ipcRenderer.invoke(PTY_CHANNELS.spawn, req),
  input: (req) => ipcRenderer.invoke(PTY_CHANNELS.input, req),
  resize: (req) => ipcRenderer.invoke(PTY_CHANNELS.resize, req),
  kill: (req) => ipcRenderer.invoke(PTY_CHANNELS.kill, req),
  list: (req) => ipcRenderer.invoke(PTY_CHANNELS.list, req),
  read: (req) => ipcRenderer.invoke(PTY_CHANNELS.read, req),
  killConversation: (req) =>
    ipcRenderer.invoke(PTY_CHANNELS.killConversation, req),
  onEvent: (cb) => {
    const listener = (_e: unknown, payload: PtyEventPush) => cb(payload);
    ipcRenderer.on(PTY_CHANNELS.event, listener);
    return () => ipcRenderer.removeListener(PTY_CHANNELS.event, listener);
  },
};

const notificationApi: NotificationApi = {
  show: (input) => ipcRenderer.invoke(NOTIFICATION_CHANNELS.show, input),
  onClicked: (cb) => {
    const listener = (_e: unknown, payload: { conversationId?: string }) =>
      cb(payload);
    ipcRenderer.on(NOTIFICATION_CHANNELS.clicked, listener);
    return () =>
      ipcRenderer.removeListener(NOTIFICATION_CHANNELS.clicked, listener);
  },
};

const hostApi: HostApi = {
  runOp: (input) => ipcRenderer.invoke(HOST_CHANNELS.runOp, input),
};

const previewApi: PreviewApi = {
  open: (input) => ipcRenderer.invoke(PREVIEW_CHANNELS.open, input),
  embedShow: (input) => ipcRenderer.invoke(PREVIEW_CHANNELS.embedShow, input),
  embedSetBounds: (bounds) =>
    ipcRenderer.send(PREVIEW_CHANNELS.embedSetBounds, bounds),
  embedHide: () => ipcRenderer.send(PREVIEW_CHANNELS.embedHide),
  embedReload: () => ipcRenderer.send(PREVIEW_CHANNELS.embedReload),
  embedBack: () => ipcRenderer.send(PREVIEW_CHANNELS.embedBack),
  embedClose: () => ipcRenderer.send(PREVIEW_CHANNELS.embedClose),
  onNavState: (cb) => {
    const listener = (_e: unknown, payload: PreviewNavState) => cb(payload);
    ipcRenderer.on(PREVIEW_CHANNELS.embedNavState, listener);
    return () =>
      ipcRenderer.removeListener(PREVIEW_CHANNELS.embedNavState, listener);
  },
};

const browserApi: BrowserApi = {
  show: (input) => ipcRenderer.invoke(BROWSER_CHANNELS.show, input),
  setBounds: (bounds) => ipcRenderer.send(BROWSER_CHANNELS.setBounds, bounds),
  hide: () => ipcRenderer.invoke(BROWSER_CHANNELS.hide),
  navigate: (input) => ipcRenderer.invoke(BROWSER_CHANNELS.navigate, input),
  openWorkspaceHtml: (input) =>
    ipcRenderer.invoke(BROWSER_CHANNELS.openWorkspaceHtml, input),
  reload: (pageId) => ipcRenderer.send(BROWSER_CHANNELS.reload, { pageId }),
  back: (pageId) => ipcRenderer.send(BROWSER_CHANNELS.back, { pageId }),
  close: (pageId) => ipcRenderer.send(BROWSER_CHANNELS.close, { pageId }),
  closeConversation: (input) =>
    ipcRenderer.invoke(BROWSER_CHANNELS.closeConversation, input),
  onNavState: (cb) => {
    const listener = (_e: unknown, payload: BrowserNavState) => cb(payload);
    ipcRenderer.on(BROWSER_CHANNELS.navState, listener);
    return () =>
      ipcRenderer.removeListener(BROWSER_CHANNELS.navState, listener);
  },
};

const windowApi: WindowApi = {
  minimize: () => ipcRenderer.send(WINDOW_CHANNELS.minimize),
  maximize: () => ipcRenderer.send(WINDOW_CHANNELS.maximize),
  close: () => ipcRenderer.send(WINDOW_CHANNELS.close),
  applyFramePreset: (preset: WindowFramePreset) =>
    ipcRenderer.invoke(WINDOW_CHANNELS.applyFramePreset, preset),
  getFramePreset: () => ipcRenderer.invoke(WINDOW_CHANNELS.getFramePreset),
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("agentTownApi", agentTownApi);
    contextBridge.exposeInMainWorld("fsApi", fsApi);
    contextBridge.exposeInMainWorld("sidecarApi", sidecarApi);
    contextBridge.exposeInMainWorld("outboxApi", outboxApi);
    contextBridge.exposeInMainWorld("localStoreApi", localStoreApi);
    contextBridge.exposeInMainWorld("updaterApi", updaterApi);
    contextBridge.exposeInMainWorld("logApi", logApi);
    contextBridge.exposeInMainWorld("terminalApi", terminalApi);
    contextBridge.exposeInMainWorld("processApi", processApi);
    contextBridge.exposeInMainWorld("ptyApi", ptyApi);
    contextBridge.exposeInMainWorld("notificationApi", notificationApi);
    contextBridge.exposeInMainWorld("hostApi", hostApi);
    contextBridge.exposeInMainWorld("previewApi", previewApi);
    contextBridge.exposeInMainWorld("browserApi", browserApi);
    contextBridge.exposeInMainWorld("windowApi", windowApi);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-ignore - 非隔离环境下直接挂载
  window.agentTownApi = agentTownApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.fsApi = fsApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.sidecarApi = sidecarApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.outboxApi = outboxApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.localStoreApi = localStoreApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.updaterApi = updaterApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.logApi = logApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.terminalApi = terminalApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.processApi = processApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.ptyApi = ptyApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.notificationApi = notificationApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.hostApi = hostApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.previewApi = previewApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.browserApi = browserApi;
  // @ts-ignore - 非隔离环境下直接挂载
  window.windowApi = windowApi;
}
