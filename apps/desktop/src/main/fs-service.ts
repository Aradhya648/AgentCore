/**
 * 本地文件系统服务（主进程）— 薄 facade，公共 API 由 `./fs` 包提供。
 */
export type { StoredRoot } from "./fs";
export { executeWorkspaceOp, getStoredRoot, registerFsIpc } from "./fs";
