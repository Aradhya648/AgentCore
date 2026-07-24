import { Button } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateFolder } from "@/hooks/useFolders";
import { hasLocalFiles } from "@/lib/capabilities";
import { notifyError, notifySuccess } from "@/lib/toast";
import { ensureDefaultContainerRoot } from "@/services/defaultWorkspace";
import { type FolderMeta, sanitizeProjectSubpath } from "@/services/folders";
import { useConversationStore } from "@/stores/conversation";
import { useFoldersStore } from "@/stores/folders";
import { Cloud, FolderOpen, HardDrive, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const isDesktop = hasLocalFiles();

type LocationChoice =
  | { kind: "pick_local"; rootId: string; rootName: string }
  | { kind: "default_container" }
  | { kind: "cloud" };

/**
 * Canonical「新建项目」dialog — location is required (local folder / default
 * container subpath / cloud). Draft composer auto-selects the new project.
 */
export function CreateFolderDialog() {
  const open = useFoldersStore((s) => s.createFolderOpen);
  const close = useFoldersStore((s) => s.closeCreateFolder);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      {open && <CreateFolderDialogBody onClose={close} />}
    </Dialog>
  );
}

function CreateFolderDialogBody({ onClose }: { onClose: () => void }) {
  const createFolder = useCreateFolder();
  const [name, setName] = useState("");
  const [location, setLocation] = useState<LocationChoice | null>(
    isDesktop ? { kind: "default_container" } : { kind: "cloud" },
  );
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    if (isDesktop) void ensureDefaultContainerRoot();
  }, []);

  const handlePickLocalDir = async () => {
    if (!window.fsApi) return;
    const root = await window.fsApi.addRoot();
    if (!root) return;
    // P2 trust-on-first-use: FsRoot 不下发绝对路径，以 root id 作用户级信任键。
    const { confirmTrustLocalDirectory } = await import(
      "@/services/workspaceTrust"
    );
    confirmTrustLocalDirectory(root.id);
    setLocation({ kind: "pick_local", rootId: root.id, rootName: root.name });
  };

  const handleSubmit = async () => {
    const trimmed = name.trim();
    if (!trimmed || !location || createFolder.isPending) return;
    try {
      let folder: FolderMeta;
      if (location.kind === "cloud") {
        folder = await createFolder.mutateAsync({
          name: trimmed,
          mode: "cloud",
        });
      } else if (location.kind === "pick_local") {
        folder = await createFolder.mutateAsync({
          name: trimmed,
          mode: "local",
          localRootId: location.rootId,
          localSubpath: null,
        });
      } else {
        const rootId = await ensureDefaultContainerRoot();
        if (!rootId) {
          notifyError(new Error("无法初始化默认本地目录"), "创建项目失败");
          return;
        }
        folder = await createFolder.mutateAsync({
          name: trimmed,
          mode: "local",
          localRootId: rootId,
          localSubpath: sanitizeProjectSubpath(trimmed),
        });
      }
      const draft =
        useConversationStore.getState().currentConversationId === null;
      if (draft) {
        useFoldersStore.getState().setDraftWorkspaceIntent({
          kind: "project",
          folderId: folder.id,
        });
      }
      useFoldersStore.getState().setPendingRename(folder.id);
      notifySuccess(`已创建项目「${folder.name}」`);
      onClose();
    } catch (e) {
      notifyError(e, "创建项目失败");
    }
  };

  const locationReady = location != null;
  const suggestedSubpath = sanitizeProjectSubpath(name || "项目名");

  return (
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>新建项目</DialogTitle>
        <DialogDescription>
          项目即工作区：创建时选定位置，之后会话继承该空间。
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-3 py-1">
        <input
          ref={inputRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim() && locationReady) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder="项目名称"
          aria-label="项目名称"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
        />

        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">位置（必选）</p>
          {isDesktop && (
            <>
              <LocationOption
                selected={location?.kind === "default_container"}
                icon={<HardDrive size={14} />}
                label="本机默认目录"
                hint={`~/Documents/AgentCore/${suggestedSubpath}`}
                onClick={() => setLocation({ kind: "default_container" })}
              />
              <LocationOption
                selected={location?.kind === "pick_local"}
                icon={<FolderOpen size={14} />}
                label={
                  location?.kind === "pick_local"
                    ? `已选：${location.rootName}`
                    : "选择本地文件夹…"
                }
                hint="以该文件夹为项目根"
                onClick={() => void handlePickLocalDir()}
              />
            </>
          )}
          <LocationOption
            selected={location?.kind === "cloud"}
            icon={<Cloud size={14} />}
            label="云端空间"
            hint="团队共享，不落本机"
            onClick={() => setLocation({ kind: "cloud" })}
          />
        </div>
      </div>

      <DialogFooter>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={createFolder.isPending}
        >
          取消
        </Button>
        <Button
          variant="primary"
          onClick={() => void handleSubmit()}
          disabled={!name.trim() || !locationReady || createFolder.isPending}
        >
          {createFolder.isPending ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              创建中…
            </>
          ) : (
            "创建"
          )}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function LocationOption({
  selected,
  icon,
  label,
  hint,
  onClick,
}: {
  selected: boolean;
  icon: React.ReactNode;
  label: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-start gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
        selected
          ? "border-primary bg-primary/5 text-foreground"
          : "border-border text-muted-foreground hover:border-border hover:bg-accent hover:text-foreground"
      }`}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-foreground">{label}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {hint}
        </span>
      </span>
    </button>
  );
}
