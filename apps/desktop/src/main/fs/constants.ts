export const TEXT_PREVIEW_CAP = 256 * 1024; // 文本预览最多读取/展示 256KB
export const IMAGE_PREVIEW_CAP = 10 * 1024 * 1024; // 图片超过 10MB 退化为元信息
export const EDIT_READ_MAX = 5 * 1024 * 1024; // 「读以编辑」整文入内存上限 5 MiB（超出不在面板内编辑）

export const LIST_FILES_CAP = 5000; // @ 提及检索：单根最多返回文件数
export const LIST_FILES_MAX_DEPTH = 12; // 递归最大深度，防极深目录
// 递归列举跳过集：权威定义在 workspaceIgnore.ts（与服务端 IGNORED_DIRS 对齐）。
export { LIST_FILES_SKIP_DIRS } from "./workspaceIgnore";

// --- 本地工作区 op（双模式工作区 P2）执行边界 ---
// 整文读取上限：服务端 ServerWorkspace.read 不设上限（随后由工具层截断模型可见输出），
// 但桌面在用户机器上整文读入内存，故加一道防 OOM 上限，超出按 IO 错误处理（已记差异）。
export const WORKSPACE_READ_MAX = 5 * 1024 * 1024; // 5 MiB
export const WORKSPACE_LIST_MAX = 100; // 与 ServerWorkspace.list 的 _MAX_LIST_ENTRIES 对齐
export const GREP_MAX_LINE = 300; // 截断超长命中行（如压缩产物），与服务端对齐
export const GREP_MAX_FILES = 5000; // 单次 grep 最多打开文件数
export const GREP_MAX_RESULTS_CAP = 200; // 结果硬上限
/** grep 单文件大小帽（与服务端 rg_grep.GREP_MAX_FILE_BYTES 对齐，2 MiB） */
export const GREP_MAX_FILE_BYTES = 2 * 1024 * 1024;

// 本地→云交接打包（双模式工作区 P2e / e1）上限：防超大仓把整树读入内存/撑爆通道回填。
export const ARCHIVE_MAX_FILES = 20000; // 最多打包文件数
export const ARCHIVE_MAX_BYTES = 100 * 1024 * 1024; // 原始字节上限（zip 前）100 MiB

// 本地代码执行（P2c）：镜像服务端 SubprocessSandbox。命令/扩展名/超时上限一一对齐；
// 进程 cwd = 绑定的本地根（让代码与文件工具同目录，呼应服务端 cwd=workspace）。
export const EXEC_LANGS: Record<string, { cmd: string[]; ext: string }> = {
  python: { cmd: ["python", "-u"], ext: ".py" },
  javascript: { cmd: ["node"], ext: ".js" },
  bash: { cmd: ["bash"], ext: ".sh" },
};
export const EXEC_TIMEOUT_CAP_S = 60; // 与 code_execute 工具 60s 上限对齐（双保险）
// 单流捕获硬上限：防失控输出占内存/撑大通道回填；模型可见截断（8000）由服务端
// ExecutionResult.__post_init__ 统一处理，故此处留足余量、不抢那层语义。
export const EXEC_CAPTURE_CAP = 100_000;

export const IMAGE_MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".bmp": "image/bmp",
  ".ico": "image/x-icon",
  ".avif": "image/avif",
};
