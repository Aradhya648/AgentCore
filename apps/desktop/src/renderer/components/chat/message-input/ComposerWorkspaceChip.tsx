import { Button, SearchField } from "@/components/ui";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  WorkspaceModeMenu,
  WorkspaceModeTrigger,
  useWorkspaceModeState,
} from "@/components/workspace/WorkspaceModeControl";
import { useGroupedConversations } from "@/hooks/useConversations";
import { useCreateFolder } from "@/hooks/useFolders";
import { pickLocalFolderRoot } from "@/lib/bindLocalFolder";
import { hasLocalFiles } from "@/lib/capabilities";
import { notifyError, notifySuccess } from "@/lib/toast";
import { ensureDefaultContainerRoot } from "@/services/defaultWorkspace";
import type { FolderMeta } from "@/services/folders";
import { type DraftWorkspaceIntent, useFoldersStore } from "@/stores/folders";
import {
  Check,
  Cloud,
  FolderOpen,
  HardDrive,
  Loader2,
  Plus,
} from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

/**
 * Always-on「在哪工作」chip in the turn composer.
 * Draft: single menu (quick local / cloud / projects / create / open folder).
 * Bound conversation: read-only status (+ backup when local).
 */
export function ComposerWorkspaceChip({
  conversationId,
}: {
  conversationId: string | null;
}) {
  if (conversationId) {
    return <BoundChip conversationId={conversationId} />;
  }
  return <DraftChip />;
}

function BoundChip({ conversationId }: { conversationId: string }) {
  const state = useWorkspaceModeState(conversationId);
  const [pop, setPop] = useState(false);

  if (!state) {
    return (
      <span className="inline-flex h-7 items-center gap-1 px-1.5 text-xs text-muted-foreground">
        <Loader2 size={12} className="animate-spin" />
        工作区…
      </span>
    );
  }

  return (
    <Popover open={pop} onOpenChange={setPop}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          aria-label="工作区"
          title={state.effective.isLocal ? "本地工作区" : "云端工作区"}
          className="h-auto min-w-0 max-w-[200px] shrink gap-1 px-1.5 py-1 text-xs font-normal text-muted-foreground hover:text-foreground"
        >
          <WorkspaceModeTrigger
            effective={state.effective}
            className="text-xs"
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-0">
        <WorkspaceModeMenu state={state} onActionDone={() => setPop(false)} />
      </PopoverContent>
    </Popover>
  );
}

function draftLabel(
  intent: DraftWorkspaceIntent,
  folders: FolderMeta[],
): { icon: "local" | "cloud" | "project"; text: string } {
  if (intent.kind === "quick_cloud") {
    return { icon: "cloud", text: "快速对话" };
  }
  if (intent.kind === "quick_local") {
    return { icon: "local", text: "本机草稿" };
  }
  const folder = folders.find((f) => f.id === intent.folderId);
  if (!folder) return { icon: "project", text: "项目" };
  return {
    icon: folder.mode === "local" ? "local" : "cloud",
    text: `${folder.name} · ${folder.mode === "local" ? "本地" : "云端"}`,
  };
}

function folderLocationHint(f: FolderMeta): string {
  if (f.mode === "cloud") return "云端空间";
  if (f.localSubpath) return `本地 · ${f.localSubpath}`;
  return "本地文件夹";
}

function DraftChip() {
  const [pop, setPop] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const intent = useFoldersStore((s) => s.draftWorkspaceIntent);
  const setIntent = useFoldersStore((s) => s.setDraftWorkspaceIntent);
  const openCreate = useFoldersStore((s) => s.openCreateFolder);
  const createFolder = useCreateFolder();
  const isDesktop = hasLocalFiles();

  const grouped = useGroupedConversations().data;
  const folders = useMemo(() => {
    const list = grouped?.folders ?? [];
    return isDesktop ? list : list.filter((f) => f.mode === "cloud");
  }, [grouped?.folders, isDesktop]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return folders;
    return folders.filter((f) => f.name.toLowerCase().includes(q));
  }, [folders, query]);

  const { icon, text } = draftLabel(intent, folders);

  const pickQuickLocal = () => {
    setIntent({ kind: "quick_local" });
    void ensureDefaultContainerRoot();
    setPop(false);
  };

  const pickQuickCloud = () => {
    setIntent({ kind: "quick_cloud" });
    setPop(false);
  };

  const pickProject = (id: string) => {
    setIntent({ kind: "project", folderId: id });
    setPop(false);
  };

  const openLocalAsProject = async () => {
    setBusy(true);
    try {
      const result = await pickLocalFolderRoot();
      if (!result.ok) return;
      const folder = await createFolder.mutateAsync({
        name: result.root.name,
        mode: "local",
        localRootId: result.root.id,
        localSubpath: null,
      });
      setIntent({ kind: "project", folderId: folder.id });
      notifySuccess(`已创建项目「${folder.name}」`);
      setPop(false);
    } catch (e) {
      notifyError(e, "创建项目失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Popover
      open={pop}
      onOpenChange={(o) => {
        setPop(o);
        if (!o) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          aria-label="在哪工作"
          title={text}
          className="h-auto min-w-0 max-w-[200px] shrink gap-1 px-1.5 py-1 text-xs font-normal text-muted-foreground hover:text-foreground"
        >
          {icon === "cloud" ? (
            <Cloud size={13} className="shrink-0" />
          ) : icon === "local" ? (
            <HardDrive size={13} className="shrink-0" />
          ) : (
            <FolderOpen size={13} className="shrink-0" />
          )}
          <span className="min-w-0 truncate">{text}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <div className="border-b border-border px-3 py-2.5">
          <div className="text-xs font-medium text-foreground">在哪工作</div>
          <div className="text-xs text-muted-foreground">
            {isDesktop
              ? "你的文件在哪，AI 就在哪干活；没给文件，就在云上干"
              : "Web 默认云端草稿；仅云项目可选"}
          </div>
        </div>
        <div className="max-h-[360px] overflow-y-auto p-1.5">
          <DraftRow
            icon={<Cloud size={14} />}
            label="快速对话"
            hint="云端草稿（默认）"
            selected={intent.kind === "quick_cloud"}
            onClick={pickQuickCloud}
            disabled={busy}
          />
          {isDesktop ? (
            <DraftRow
              icon={<HardDrive size={14} />}
              label="本机草稿"
              hint="落本机容器，走本地引擎"
              selected={intent.kind === "quick_local"}
              onClick={pickQuickLocal}
              disabled={busy}
            />
          ) : null}

          <div className="my-1 border-t border-border" />
          <div className="px-2.5 pt-1 pb-1 text-xs text-muted-foreground">
            项目
          </div>
          <div className="mx-2.5 mb-1">
            <SearchField
              value={query}
              onValueChange={setQuery}
              placeholder="筛选项目…"
              aria-label="筛选项目"
              inputClassName="text-xs"
            />
          </div>
          {filtered.map((f) => (
            <DraftRow
              key={f.id}
              icon={<FolderOpen size={14} />}
              label={f.name}
              hint={folderLocationHint(f)}
              selected={intent.kind === "project" && intent.folderId === f.id}
              onClick={() => pickProject(f.id)}
              disabled={busy}
            />
          ))}
          {filtered.length === 0 && (
            <p className="px-2.5 py-2 text-xs text-muted-foreground">
              {query.trim() ? "没有匹配的项目" : "还没有项目"}
            </p>
          )}

          <div className="my-1 border-t border-border" />
          <DraftRow
            icon={<Plus size={14} />}
            label="新建项目…"
            onClick={() => {
              openCreate();
              setPop(false);
            }}
            disabled={busy}
          />
          {isDesktop && (
            <DraftRow
              icon={<FolderOpen size={14} />}
              label="打开本地文件夹…"
              hint="以该文件夹创建项目"
              onClick={() => void openLocalAsProject()}
              disabled={busy}
            />
          )}
          {busy && (
            <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              处理中…
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function DraftRow({
  icon,
  label,
  hint,
  selected,
  onClick,
  disabled,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  selected?: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      disabled={disabled}
      className="h-auto w-full justify-start gap-2 px-2.5 py-1.5 text-left text-xs font-medium"
      icon={<span className="shrink-0 text-muted-foreground">{icon}</span>}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate">{label}</span>
        {hint && (
          <span className="block truncate text-xs font-normal text-muted-foreground">
            {hint}
          </span>
        )}
      </span>
      {selected && <Check size={14} className="shrink-0 text-primary" />}
    </Button>
  );
}
