import type { FileSource } from "@/lib/fileSource";

const OFFLINE_WRITE_MSG = "离线只读：本地文件暂不可修改";

/**
 * N4-A: wrap a local FileSource so the file hub stays browseable offline but
 * refuses all mutations (caps.edit=false; FileTree hides mutate menus).
 */
export function asReadOnlyFileSource(source: FileSource): FileSource {
  return {
    id: source.id,
    label: source.label,
    caps: {
      ...source.caps,
      edit: false,
      transfer: false,
      // Keep watch so the tree can still refresh from OS changes while browsing.
      watch: source.caps.watch,
      snapshots: false,
    },
    listDir: (dir) => source.listDir(dir),
    listTree: source.listTree?.bind(source),
    listFileIndex: source.listFileIndex?.bind(source),
    read: (path) => source.read(path),
    readForEdit: (() => {
      const readForEdit = source.readForEdit;
      return readForEdit ? (path: string) => readForEdit(path) : undefined;
    })(),
    async createFile() {
      throw new Error(OFFLINE_WRITE_MSG);
    },
    async mkdir() {
      throw new Error(OFFLINE_WRITE_MSG);
    },
    async move() {
      throw new Error(OFFLINE_WRITE_MSG);
    },
    async delete() {
      throw new Error(OFFLINE_WRITE_MSG);
    },
    async writeText() {
      return { ok: false, reason: "denied", message: OFFLINE_WRITE_MSG };
    },
    watch: source.watch?.bind(source),
    revealInOsFileManager: source.revealInOsFileManager?.bind(source),
    openWithOsDefaultApp: source.openWithOsDefaultApp?.bind(source),
    openInAppPreview: source.openInAppPreview?.bind(source),
  };
}
