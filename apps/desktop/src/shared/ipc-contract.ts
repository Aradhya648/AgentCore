/**
 * 本地文件系统 IPC 契约 —— 主进程 / preload / renderer 三端共享的单一真相源。
 *
 * 设计约束：
 * - renderer 仅以 `{ rootId, relPath }` 寻址，绝对路径只存在于主进程（不下发本机绝对路径）。
 * - 所有可能失败的操作统一返回 `FsResult`（判别结果），不向 renderer 抛异常。
 */

/** 一个已授权的本地根目录（对 renderer 只暴露 id 与显示名）。 */
export interface FsRoot {
  id: string;
  name: string;
  /** W3 session grant alias under ``external/<alias>/`` (omit for permanent roots). */
  alias?: string;
  /** Session access mode (readonly | organize). Prefer over ``readonly``. */
  mode?: "readonly" | "organize";
  /** @deprecated Prefer ``mode``. */
  readonly?: boolean;
  sessionOnly?: boolean;
}

/** 目录项（懒加载的单层子项）。 */
export interface FsEntry {
  name: string;
  /** 相对所属根目录的路径，统一用 "/" 分隔；根目录自身为 ""。 */
  relPath: string;
  kind: "file" | "dir";
  /** 文件字节数；目录为 null。 */
  size: number | null;
  /** 最近修改时间（毫秒时间戳）；不可得为 null。 */
  modifiedMs: number | null;
}

/** 文件预览结果：文本 / 图片（data URL）/ 二进制（仅元信息）。 */
export type FilePreview =
  | { kind: "text"; content: string; truncated: boolean }
  | { kind: "image"; dataUrl: string; mime: string; size: number }
  | { kind: "binary"; mime: string; size: number; reason: string };

/** 扁平文件条目（用于 @ 提及检索；只含文件，不含目录）。 */
export interface FsFileRef {
  /** 相对所属根目录的路径，统一用 "/" 分隔。 */
  relPath: string;
  /** 文件名（relPath 的最后一段）。 */
  name: string;
}

/**
 * Fs IPC 失败判别码——renderer 按码分支（如懒物化工作区对 `not_found`），
 * **禁止**匹配 `reason` 中文文案。
 */
export type FsErrorCode =
  | "not_found"
  | "out_of_root"
  | "unauthorized"
  | "invalid"
  | "exists"
  | "denied"
  | "busy"
  | "error";

/** 统一的判别式结果。 */
export type FsResult<T = void> =
  | { ok: true; data: T }
  | { ok: false; reason: string; code: FsErrorCode };

export type FsCreateKind = "file" | "dir";

/** 文本文件编码（读侧嗅探）；`gbk` 仅可读不可回写（未引入编码器）。 */
export type FsEncoding = "utf-8" | "utf-8-bom" | "gbk";
/** 换行风格——回写时按原文还原，避免整文换行 diff。 */
export type FsEol = "lf" | "crlf";

/**
 * 「读以编辑」结果：完整正文 + 写前 CAS 基线（mtime）+ 原文编码/换行。
 *
 * 与预览 `readFile` 分工：预览有 256KB 截断且判别图片/二进制；编辑必须拿到**完整**正文
 * （截断正文一旦保存会丢尾），故编辑走独立通道 `fs:readTextFile`。
 */
export interface FsTextFile {
  /** 完整正文，换行已统一为 `\n`（回写时按 `eol` 还原）。 */
  content: string;
  /** 写前 CAS 基线：保存时与磁盘 mtime 比对，不符即冲突。 */
  mtimeMs: number;
  encoding: FsEncoding;
  eol: FsEol;
}

/** 写文本文件的输入（带写前 CAS 基线）。 */
export interface FsWriteInput {
  /** 编辑器正文（`\n` 换行）；主进程按 `eol`/`encoding` 还原落盘。 */
  content: string;
  /** 来自读取基线；`gbk` 会被拒写。 */
  encoding: FsEncoding;
  eol: FsEol;
  /** 写前 CAS：与磁盘 mtime 不符即 `conflict`；`0` 视为新建。 */
  baselineMtimeMs: number;
}

/**
 * 写盘结果（判别式）。`conflict` 带磁盘当前 `mtimeMs` 供「仍然覆盖」用其做基线再写；
 * 其余失败原因：`denied`（越权/未授权）/`locked`（被占用）/`unsupported`（GBK 回写未启用）/`error`。
 */
export type FsWriteResult =
  | { ok: true; mtimeMs: number }
  | { ok: false; reason: "conflict"; diskMtimeMs: number }
  | {
      ok: false;
      reason: "denied" | "locked" | "unsupported" | "error";
      message?: string;
    };

/**
 * 本地工作区 op 名（双模式工作区）—— 与服务端 ``WorkspaceOp`` 一一对应。
 *
 * 服务端 ``LocalWorkspace`` 把每个 backend 方法序列化成一条 op 经 SSE 下发，主进程
 * 在授权根上执行后回填。覆盖读 / 写 / 树 / grep / 执行 / 进程管理等全套 op（不再仅
 * P2a 只读三件套）。
 *
 * ``archive`` 不对应任何 backend 方法——它是本地→云交接（P2e / e1）专用 op：把整个绑定
 * 根打包成单个归档（套用忽略规则）交服务端暂存并快照，由 handoff 编排直接下发。
 * ``probe_exec`` 同样不是 backend 方法——回合准备时探测本机 code_execute 可用解释器，
 * 供服务端裁剪工具 schema（坏 WSL bash 等不进 enum）。
 */
export type WorkspaceOpName =
  | "read"
  | "write"
  | "append"
  | "read_bytes"
  | "write_bytes"
  | "list"
  | "read_lines"
  | "list_tree"
  | "index_files"
  | "mkdir"
  | "delete"
  | "copy"
  | "move"
  | "replace"
  | "grep"
  | "execute"
  | "probe_exec"
  | "archive"
  | "process_start"
  | "process_read"
  | "process_stop"
  | "process_list";

/**
 * 一次本地 op 的执行结果信封 —— 形状与服务端回填端点 `ResolveClientToolInteraction.result`
 * 对齐：成功带 `value`（op 相关）；失败带类型化 `error`，其 `kind` 直接映射回服务端
 * 的 `WorkspaceError` 子类（如 `PathNotFound`），从而工具层报错文案与云模式一致。
 */
export type WorkspaceOpResult =
  | { ok: true; value: unknown }
  | { ok: false; error: { kind: string; detail: string; count?: number } };

/** 主进程 → renderer 的目录变更事件（watch 命中后发出）。 */
export interface FsChangedEvent {
  rootId: string;
  relPath: string;
}

/** IPC 通道名 —— 主进程与 preload 共用，避免硬编码漂移。 */
export const FS_CHANNELS = {
  addRoot: "fs:addRoot",
  ensureDefaultRoot: "fs:ensureDefaultRoot",
  listRoots: "fs:listRoots",
  removeRoot: "fs:removeRoot",
  /** W3: session-scoped read-only root for one conversation. */
  grantSessionReadonlyRoot: "fs:grantSessionReadonlyRoot",
  listSessionReadonlyRoots: "fs:listSessionReadonlyRoots",
  revokeSessionReadonlyRoot: "fs:revokeSessionReadonlyRoot",
  clearSessionReadonlyRoots: "fs:clearSessionReadonlyRoots",
  listDir: "fs:listDir",
  listFiles: "fs:listFiles",
  readFile: "fs:readFile",
  readTextFile: "fs:readTextFile",
  writeFile: "fs:writeFile",
  rename: "fs:rename",
  move: "fs:move",
  copy: "fs:copy",
  create: "fs:create",
  delete: "fs:delete",
  watch: "fs:watch",
  unwatch: "fs:unwatch",
  changed: "fs:changed",
  workspaceOp: "fs:workspaceOp",
  grantSessionRun: "fs:grantSessionRun",
  reveal: "fs:reveal",
  openPath: "fs:openPath",
  copyPath: "fs:copyPath",
  /** 将根内相对路径移入系统回收站（软删）。 */
  trashPath: "fs:trashPath",
  /** 引用即驻留：系统文件选择器 → 写入工作区 attachments/ 或暂存。 */
  pickAndStageAttachment: "fs:pickAndStageAttachment",
  /** 从已授权根相对路径驻留。 */
  stageFromRoot: "fs:stageFromRoot",
  /** 拖拽绝对路径驻留（仅 preload 调用，不下发 renderer）。 */
  stageFromAbsPath: "fs:stageFromAbsPath",
  /** 草稿暂存 → 本地工作区 attachments/。 */
  finalizeStagedAttachment: "fs:finalizeStagedAttachment",
  /** 云端：取出暂存字节后清除。 */
  consumeStagedBytes: "fs:consumeStagedBytes",
  /**
   * 云 scratch 产物单向导出：弹目录选择器，把 zip（base64）解压落地。
   * 不登记授权根、不改工作区绑定（双模式工作区 §八.7）。
   */
  checkoutArchive: "fs:checkoutArchive",
  /**
   * 云 scratch 产物「在浏览器打开」：把 zip（base64）解压到临时目录，再用系统默认
   * 程序打开指定文件（HTML → 系统浏览器，得到完整 JS + 多文件相对资源的真实效果）。
   * 落临时目录、不弹目录、不登记根（与 checkoutArchive 的「导出落地」区分）。
   */
  previewArchive: "fs:previewArchive",
  /**
   * 单文件「另存为」：renderer 把已取到的字节交主进程，弹系统保存对话框后原子落盘。
   * Electron 不支持 `<a download>` + blob:（不触发 will-download，且 blob: 导航被
   * will-navigate 安全守卫拦截），故桌面端所有下载（云工作区文件 / 快照 zip / 对话
   * 导出 / IM 附件 / 图表·白板导出）统一走本通道；web 端保留 anchor 方案。
   */
  saveFile: "fs:saveFile",
} as const;

/** {@link FsApi.checkoutArchive} 结果。 */
export type CheckoutArchiveResult =
  | { ok: true; destName: string; fileCount: number }
  | { ok: false; reason: "cancelled" }
  | { ok: false; reason: "error"; message: string };

/** {@link FsApi.saveFile} 结果。`cancelled` = 用户在保存对话框里放弃（非错误）。 */
export type SaveFileResult =
  | { ok: true; fileName: string }
  | { ok: false; reason: "cancelled" }
  | { ok: false; reason: "error"; message: string };

/** {@link FsApi.previewArchive} 结果（落临时目录、无「取消」态）。 */
export type PreviewArchiveResult =
  | { ok: true; fileCount: number }
  | { ok: false; reason: "error"; message: string };

/** 引用即驻留：落盘到对话工作区 attachments/ 的目标。 */
export interface StageAttachmentDest {
  rootId: string;
  subpath?: string;
}

/**
 * 引用即驻留结果。``workspacePath`` 已写入对话工作区；``stagingId`` 仍在主进程暂存
 * （草稿尚无会话 / 云端待上传）。绝对路径永不出现在此结构中。
 */
export interface StagedAttachment {
  name: string;
  workspacePath?: string;
  stagingId?: string;
  binary: boolean;
  text: string;
  truncated: boolean;
  sizeBytes: number;
}

/**
 * 暴露在 `window.fsApi` 上的 renderer 端 API 面。
 *
 * `move` 的 `destRelPath` 语义为「目标目录」，源对象将被移动进该目录。
 */
export interface FsApi {
  addRoot(): Promise<FsRoot | null>;
  /**
   * 取得（必要时自动创建 + 授权）默认本地容器根（`~/Documents/AgentCore`）。
   *
   * 供显式「本机草稿」裸聊与本地项目创建复用；桌面裸聊默认已切云（§八.7），
   * 新建裸聊不再自动调用。幂等——已存在同路径的授权根则原样复用。
   */
  ensureDefaultRoot(): Promise<FsRoot>;
  /**
   * 云 scratch → 本地单向 checkout：选目录并解压 zip。取消 → `{ reason:"cancelled" }`。
   */
  checkoutArchive(archiveBase64: string): Promise<CheckoutArchiveResult>;
  /**
   * 「在浏览器打开」：把 zip（base64）解压到临时目录，再用系统默认程序打开
   * `openRelPath`（HTML → 系统浏览器）。与 {@link checkoutArchive} 不同：不弹目录、
   * 落临时目录、打开指定文件而非整个目录。
   */
  previewArchive?(
    archiveBase64: string,
    openRelPath: string,
  ): Promise<PreviewArchiveResult>;
  /**
   * 单文件「另存为」：弹系统保存对话框（以净化后的 `suggestedName` 预填、默认落
   * 下载目录），把 `bytes` 原子写入用户所选路径（同目录临时文件 + rename）。
   * 保存路径完全由用户经对话框选定，绝对路径不回传 renderer（只回文件名供提示）。
   * 桌面端 `saveBlob` 的落盘后端——见 {@link FS_CHANNELS.saveFile} 的为什么。
   */
  saveFile(suggestedName: string, bytes: Uint8Array): Promise<SaveFileResult>;
  listRoots(): Promise<FsRoot[]>;
  removeRoot(rootId: string): Promise<void>;
  /** W3/P1: folder picker → session root (readonly | organize) bound to conversation. */
  grantSessionReadonlyRoot(
    conversationId: string,
    mode?: "readonly" | "organize",
  ): Promise<FsRoot | null>;
  listSessionReadonlyRoots(conversationId: string): Promise<FsRoot[]>;
  revokeSessionReadonlyRoot(
    conversationId: string,
    rootId: string,
  ): Promise<boolean>;
  clearSessionReadonlyRoots(conversationId: string): Promise<void>;
  listDir(rootId: string, relPath: string): Promise<FsResult<FsEntry[]>>;
  /** 递归列出根内的全部文件（用于 @ 提及检索；忽略常见无关目录，有数量上限）。 */
  listFiles(rootId: string): Promise<FsResult<FsFileRef[]>>;
  readFile(rootId: string, relPath: string): Promise<FsResult<FilePreview>>;
  /**
   * 读完整文本文件用于**编辑**（正文 + 基线 mtime/编码/换行）。与预览 `readFile` 分工：
   * 不截断、不判别图片，二进制 / 过大 / 越界以 `FsResult` 失败返回。
   */
  readTextFile(rootId: string, relPath: string): Promise<FsResult<FsTextFile>>;
  /**
   * 写文本文件，带写前 CAS（`baselineMtimeMs`）。原子写（临时文件 + rename）；
   * 失败以判别式 `FsWriteResult` 返回（`conflict` 携磁盘当前 mtime），不抛异常。
   */
  writeFile(
    rootId: string,
    relPath: string,
    input: FsWriteInput,
  ): Promise<FsWriteResult>;
  rename(rootId: string, relPath: string, newName: string): Promise<FsResult>;
  move(
    rootId: string,
    srcRelPath: string,
    destRelPath: string,
  ): Promise<FsResult>;
  /**
   * 复制文件/目录（目录递归）到**完整目标路径** `destRelPath`（含最终名）。
   *
   * 与 `move` 的语义差异：`move` 的目标是「目录」（保名移入）；`copy` 收完整目标路径，
   * 故能表达「同目录内另存为新名」（如 `a.txt` → `a 副本.txt`）——这是去重粘贴所必需。
   * 主进程经 `fs.cp(recursive)` 实现，拒绝覆盖已存在目标与「复制进自身子树」。失败以
   * `FsResult` 返回。
   */
  copy(
    rootId: string,
    srcRelPath: string,
    destRelPath: string,
  ): Promise<FsResult>;
  create(
    rootId: string,
    relPath: string,
    kind: FsCreateKind,
  ): Promise<FsResult>;
  delete(rootId: string, relPath: string): Promise<FsResult>;
  watch(rootId: string, relPath: string): Promise<void>;
  unwatch(rootId: string, relPath: string): Promise<void>;
  /** 订阅目录变更；返回取消订阅函数。 */
  onChanged(cb: (e: FsChangedEvent) => void): () => void;
  /**
   * 在某授权根上执行一次本地工作区 op（供本地模式下 AI 工具调用回填）。
   *
   * `args` 为该 op 的相对路径载荷（如 `{ path }` / `{ directory, pattern }`）；
   * 失败不抛异常，统一以 `WorkspaceOpResult` 的类型化 `error` 返回。
   */
  workspaceOp(
    rootId: string,
    op: WorkspaceOpName,
    args: Record<string, unknown>,
  ): Promise<WorkspaceOpResult>;
  /**
   * 聊天内 RunConfirm「本会话都允许」→ 主进程置 session run flag（进程重启清零）。
   * 不引入永久跨天 allowlist。
   */
  grantSessionRun(): Promise<void>;
  /**
   * 在系统文件管理器中定位该路径（Windows 资源管理器 / macOS 访达 / Linux 文件管理器）。
   *
   * 主进程把 `{rootId, relPath}` 解析为绝对路径并 realpath 校验在根内后调
   * `shell.showItemInFolder`——**绝对路径不下发 renderer**，沿用本契约的安全不变量。
   * 仅本地源有意义（云端工作区文件在服务器上，无本机路径）。失败以 `FsResult` 返回。
   */
  reveal(rootId: string, relPath: string): Promise<FsResult>;
  /**
   * 用系统默认程序打开该文件（PDF / Office / 压缩包等 in-app 预览打不开的类型）。
   * 经 `shell.openPath`；同样在主进程解析 + 校验在根内。仅本地源有意义。
   */
  openPath(rootId: string, relPath: string): Promise<FsResult>;
  /**
   * 把该路径的**绝对路径**写入系统剪贴板。写入在主进程完成（`clipboard.writeText`），
   * 故绝对路径不进 renderer。仅本地源有意义。
   */
  copyPath(rootId: string, relPath: string): Promise<FsResult>;
  /**
   * 将根内相对路径移入系统回收站（`shell.trashItem`，软删）。空 `relPath`（根自身）拒绝。
   * 路径尚不存在（懒建 scratch 未物化）视为成功。仅本地源有意义。
   */
  trashPath(rootId: string, relPath: string): Promise<FsResult>;
  /**
   * 引用即驻留：打开系统文件选择器，复制进对话工作区 ``attachments/``（有 dest）
   * 或主进程暂存（无 dest）。取消选择返回 ``null``。
   */
  pickAndStageAttachment(
    dest?: StageAttachmentDest,
  ): Promise<FsResult<StagedAttachment> | null>;
  /** 从已授权根内相对路径驻留（@ 菜单选中的文件，含二进制）。 */
  stageFromRoot(
    rootId: string,
    relPath: string,
    dest?: StageAttachmentDest,
  ): Promise<FsResult<StagedAttachment>>;
  /**
   * 拖拽/粘贴文件：preload 用 ``webUtils.getPathForFile`` 取绝对路径后调用。
   * 绝对路径不进入 renderer 业务状态。
   */
  stageDroppedFile(
    file: File,
    dest?: StageAttachmentDest,
  ): Promise<FsResult<StagedAttachment>>;
  /** 把暂存附件写入本地工作区 ``attachments/``。 */
  finalizeStagedAttachment(
    stagingId: string,
    dest: StageAttachmentDest,
  ): Promise<FsResult<StagedAttachment>>;
  /** 取出暂存字节供云端 ``PUT …/workspace/files``（取出后清除暂存）。 */
  consumeStagedBytes(
    stagingId: string,
  ): Promise<FsResult<{ name: string; data: Uint8Array; binary: boolean }>>;
}
