/**
 * 统一文件源抽象（文件中枢统一 §二）。
 *
 * 文件页（本地 OS 根，经 `window.fsApi`）与对话工作区面板（服务端 REST，经
 * `services/workspace`）本质都是「一棵带预览 + 增删改的文件树」。`FileSource`
 * 是让**同一套树/预览组件**渲染任意一种的接缝：源暴露 read/list/CRUD 核心 +
 * 能力位（watch / transfer / edit / snapshots），UI 据能力位决定挂哪些可选
 * 面，而非在组件里按源分支。
 *
 * 寻址一律**源内相对**：每个 path 都是相对源根的 POSIX（"/" 分隔）路径，根本身
 * 为 ""。具体源（WorkspaceSource / LocalRootSource）各自负责映射到其后端。
 */

/** 一次列举里的一个条目（树的某一层）。 */
export interface FileNode {
  /** 源内相对 POSIX 路径；根本身为 ""。 */
  path: string;
  /** 显示名 = path 的最后一段。 */
  name: string;
  isDir: boolean;
}

/** 一次「读以预览」的结果——两种后端能返回的并集（superset）。 */
export type FilePreviewResult =
  | { kind: "text"; text: string; truncated: boolean }
  | { kind: "image"; dataUrl: string; mime: string; size: number }
  | { kind: "binary"; mime?: string; size?: number; reason?: string }
  | { kind: "too-large" };

/** 目录变更回调（仅当 `caps.watch` 为真时有意义）。 */
export type FileChangeHandler = (dir: string) => void;

/** 文件版本（写前 CAS 基线）：本地用 mtime，云端用 etag/updatedAt（P4）。 */
export type FileVersion = { mtimeMs?: number; etag?: string };
/** 编辑用编码；`gbk` 仅可读不可回写。 */
export type EditEncoding = "utf-8" | "utf-8-bom" | "gbk";
export type EditEol = "lf" | "crlf";

/** 「读以编辑」结果（源无关）：完整正文（`\n` 换行）+ 版本基线 + 原文编码/换行。 */
export interface FileEditDoc {
  text: string;
  version: FileVersion;
  encoding: EditEncoding;
  eol: EditEol;
}

/** 写文本结果（源无关）。`conflict` 携磁盘/远端当前版本，供「仍然覆盖」用其做基线再写。 */
export type WriteTextResult =
  | { ok: true; version: FileVersion }
  | { ok: false; reason: "conflict"; version: FileVersion }
  | {
      ok: false;
      reason: "denied" | "locked" | "unsupported" | "error";
      message?: string;
    };

/**
 * 核心之外的可选能力。共用 UI 读这些决定挂哪些操作面（组件内不按源分支）。
 */
export interface FileSourceCaps {
  /** 推送目录变更事件（本地 FS watch）；否则 UI 走手动刷新。 */
  watch: boolean;
  /** 字节跨边界传输，故上传/下载有意义（云端工作区）。 */
  transfer: boolean;
  /** 面板内文本编辑经 `writeBytes` 回写。 */
  edit: boolean;
  /**
   * 轴3 快照（备份 / 版本 / 恢复）对该源可用（云端工作区为真，本地源为假）。对话工作区
   * 面板据此门控快照入口（见 WorkspacePanel）；文件中枢暂不挂快照面。
   */
  snapshots: boolean;
}

export interface FileSource {
  /** 稳定标识（拖拽载荷限定 + 每源折叠态持久化键）。 */
  readonly id: string;
  /** 人类可读的根标签（项目 / 文件夹名）。 */
  readonly label: string;
  readonly caps: FileSourceCaps;

  /** 列举一个目录的直接子项（`dir` 为 "" 即根）。 */
  listDir(dir: string): Promise<FileNode[]>;
  /**
   * 把整棵子树作为扁平数组列出（递归）。仅「能廉价枚举全部」的源提供（服务端
   * 工作区）；用于一次性建树 + 全部展开/折叠。懒加载源省略它（UI 回退到展开时
   * 逐目录 `listDir`）。
   */
  listTree?(): Promise<FileNode[]>;
  /**
   * 扁平**文件**路径列表，喂给 @ 提及索引（文件中枢统一 F4）。只含文件（不含目录）、
   * 剪掉忽略目录（node_modules/.git…）、有上限——本地根经 `fsApi.listFiles`、云端
   * 工作区经 `/file-index`，二者语义对齐，故 @ 无论源是本地还是云端表现一致。能
   * 廉价枚举的源才提供；缺省即不参与 @ 索引。
   */
  listFileIndex?(): Promise<string[]>;

  /** 读一个文件用于面板内预览（传输失败抛异常）。 */
  read(path: string): Promise<FilePreviewResult>;

  /** 在 `path` 建一个空文件。 */
  createFile(path: string): Promise<void>;
  /** 在 `path` 建目录（按需建父级）。 */
  mkdir(path: string): Promise<void>;
  /** 把 `src` 移动/改名到完整目标路径 `dst`。 */
  move(src: string, dst: string): Promise<void>;
  /**
   * 把 `src`（文件或目录，目录递归）复制到完整目标路径 `dst`（含最终名）。失败抛异常。
   *
   * 可选能力：本地源经 IPC 实现；云端源暂无（服务端尚无 copy 端点）。共用 UI 据
   * 「方法是否存在」门控「复制」入口与复制-粘贴——剪切-粘贴走必备的 `move`，故云端仍可用。
   * 调用方传**完整目标路径**（去重后的新名由 UI 在粘贴前算好），以表达「同目录另存为副本」。
   */
  copy?(src: string, dst: string): Promise<void>;
  /** 删除文件或目录（目录递归）。 */
  delete(path: string): Promise<void>;

  /**
   * 读一个文本文件用于**编辑**（完整正文 + 版本基线 + 编码/换行）。仅当 `caps.edit`
   * 且源支持源码编辑（本地 IPC；云端 P4）。与 `read`（预览，可能截断）分工——宿主
   * 编辑器只认这层接口，不分支本地/云端。
   */
  readForEdit?(path: string): Promise<FileEditDoc>;
  /**
   * 把编辑器正文写回 `path`，带写前 CAS（`baseline` 版本，`null` 视为新建）。仅当
   * `caps.edit`。失败以判别式 `reason` 返回（`conflict` 携当前版本），不抛异常。
   */
  writeText?(
    path: string,
    input: {
      content: string;
      encoding: EditEncoding;
      eol: EditEol;
      baseline: FileVersion | null;
    },
  ): Promise<WriteTextResult>;

  /** 写原始字节到 `path`（建/覆盖）。仅当 `caps.edit || caps.transfer`。 */
  writeBytes?(path: string, body: Blob): Promise<void>;
  /** 经浏览器把 `path` 存到用户磁盘。仅当 `caps.transfer`。 */
  download?(path: string, filename: string): Promise<void>;
  /** 订阅 `dir` 下变更；返回退订函数。仅当 `caps.watch`。 */
  watch?(dir: string, onChange: FileChangeHandler): () => void;

  /**
   * 把工作区内 Markdown 导出为同目录同名 ``.docx``（调服务端确定性转换器）。
   * 仅当源支持时存在（云端 REST / 本地经 convert + write_bytes）。失败抛异常。
   */
  exportMdToDocx?(path: string): Promise<{ path: string; warnings: string[] }>;

  /**
   * 系统集成（桌面本地源专属，云端源不实现 → UI 据「方法是否存在」门控菜单，组件内不按源分支）。
   *
   * 仅本地源有意义：文件在用户机器上、有真实 OS 路径；云端工作区文件在服务器上，故这三者一律省略。
   * 绝对路径全程只在主进程出现（reveal/copy 在主进程完成），不下发 renderer——沿用 IPC 契约的安全约束。
   */
  /** 在系统文件管理器中定位该路径（资源管理器 / 访达）。`""` = 工作区根本身。失败抛异常。 */
  revealInOsFileManager?(path: string): Promise<void>;
  /** 用系统默认程序打开该文件（PDF/Office/压缩包等 in-app 打不开的类型）。失败抛异常。 */
  openWithOsDefaultApp?(path: string): Promise<void>;
  /**
   * 「在浏览器打开」该文件的真实效果（主给 HTML：完整 JS + 多文件相对资源）。本地源
   * 直接用系统默认程序打开磁盘文件；云端源先把工作区快照解压到临时目录再打开。桌面
   * 专属（依赖系统浏览器 + 本机文件）；web 端不实现（HTML 在面板内为源码视图，web
   * 的完整效果出口退化为下载）。失败抛异常，调用方 toast。
   */
  openInBrowser?(path: string): Promise<void>;
  /**
   * 应用内「完整预览」：主进程经 `workspace://` 协议以 Bearer 代理会话工作区字节，在
   * Local Browser **第二非持久 partition** + sandbox 的隔离 WebContents 里完整跑 JS + 多文件
   * 相对路径引用。主入口 = 右坞 BrowserPanel（对话侧栏 `useConversationFileSource` 绑定
   * conversationId 挂上；不再走已拆除的 `openPreview` / PREVIEW_TAB）。仅桌面**云端会话工作区**
   * 源；本地源 / web 均不实现（web 无 browserApi.openWorkspaceHtml）。
   */
  openInAppPreview?(path: string): Promise<void>;
  /**
   * 在绑定工作区的目录打开交互式终端（仅本地源；经 `terminalApi.openShellAtRoot`）。
   * `""` / `"."` = 工作区根。
   */
  openShellAtPath?(path: string): Promise<void>;
  /** 把该路径的绝对路径写入系统剪贴板（写入在主进程完成）。失败抛异常。 */
  copyOsPath?(path: string): Promise<void>;
}

/** 是否 HTML 文件路径（.html/.htm）。文件视图的「网页源码」横幅与产物卡「直达完整预览」共用判定。 */
export function isHtmlPath(path: string): boolean {
  return /\.html?$/i.test(path);
}

/** 是否 Markdown 文件路径（.md/.markdown）。编辑器分发与只读预览的「默认渲染」共用判定（阅读优先）。 */
export function isMarkdownPath(path: string): boolean {
  return /\.(md|markdown)$/i.test(path);
}

/** POSIX 源路径的最后一段（显示名）。 */
export function baseName(path: string): string {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(i + 1) : path;
}

/** POSIX 源路径的父目录（顶层条目为 ""）。 */
export function parentDir(path: string): string {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(0, i) : "";
}

/** 把父目录与子名拼成源路径（dir 为 "" → 裸名）。 */
export function joinPath(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name;
}
