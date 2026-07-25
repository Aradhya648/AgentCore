import { Button, SearchField } from "@/components/ui";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import { getFolders, useCreateFolder } from "@/hooks/useFolders";
import { pickLocalFolderRoot } from "@/lib/bindLocalFolder";
import { hasLocalFiles } from "@/lib/capabilities";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ensureDefaultContainerRoot } from "@/services/defaultWorkspace";
import {
  type FolderMeta,
  findLocalFolderByBinding,
  sanitizeProjectSubpath,
} from "@/services/folders";
import { useConversationStore } from "@/stores/conversation";
import { type CreateFolderAnchorRect, useFoldersStore } from "@/stores/folders";
import type { FsRoot } from "@shared/ipc-contract";
import { Cloud, FolderOpen, HardDrive, Loader2, Plus } from "lucide-react";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const isDesktop = () => hasLocalFiles();

type LeftPane = "local_folder" | "local_blank" | "cloud_blank";

/**
 * Cursor-style「新建项目」锚点级联：桌面左栏三行 + 右栏内容；Web 仅云端空白命名。
 * 入口（chip / 侧栏 + / 命令面板）共用；AppShell 挂载 {@link CreateFolderMenuHost}。
 */
export function CreateFolderMenuHost() {
  const open = useFoldersStore((s) => s.createFolderOpen);
  const anchor = useFoldersStore((s) => s.createFolderAnchor);
  const close = useFoldersStore((s) => s.closeCreateFolder);
  /** Swallow the outside-dismiss from the menu/dropdown that just opened us. */
  const ignoreOutsideUntil = useRef(0);

  useEffect(() => {
    if (open) ignoreOutsideUntil.current = Date.now() + 200;
  }, [open]);

  const guardOutside = (e: Event) => {
    if (Date.now() < ignoreOutsideUntil.current) e.preventDefault();
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <PopoverAnchor asChild>
        <VirtualAnchor rect={anchor} />
      </PopoverAnchor>
      <PopoverContent
        align={anchor ? "start" : "center"}
        side="bottom"
        sideOffset={anchor ? 6 : 0}
        avoidCollisions={false}
        className="w-auto p-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onPointerDownOutside={guardOutside}
        onInteractOutside={guardOutside}
      >
        {open ? <CreateFolderCascadePanel onClose={close} /> : null}
      </PopoverContent>
    </Popover>
  );
}

function VirtualAnchor({ rect }: { rect: CreateFolderAnchorRect | null }) {
  if (rect) {
    return (
      <div
        aria-hidden
        className="pointer-events-none fixed z-50"
        style={{
          top: rect.top,
          left: rect.left,
          width: Math.max(rect.width, 1),
          height: Math.max(rect.height, 1),
        }}
      />
    );
  }
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed left-1/2 top-[18%] z-50 h-0 w-0 -translate-x-1/2"
    />
  );
}

export function CreateFolderCascadePanel({
  onClose,
}: {
  onClose: () => void;
}) {
  const createFolder = useCreateFolder();
  const desktop = isDesktop();
  const [pane, setPane] = useState<LeftPane>(
    desktop ? "local_folder" : "cloud_blank",
  );
  const [name, setName] = useState("");
  const [roots, setRoots] = useState<FsRoot[]>([]);
  const [rootsLoading, setRootsLoading] = useState(desktop);
  const [rootQuery, setRootQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  const loadRoots = useCallback(async () => {
    if (!desktop || !window.fsApi?.listRoots) {
      setRoots([]);
      setRootsLoading(false);
      return;
    }
    setRootsLoading(true);
    try {
      const list = await window.fsApi.listRoots();
      setRoots(list.filter((r) => !r.sessionOnly));
    } catch {
      setRoots([]);
    } finally {
      setRootsLoading(false);
    }
  }, [desktop]);

  useEffect(() => {
    if (desktop) {
      void loadRoots();
      void ensureDefaultContainerRoot();
    }
  }, [desktop, loadRoots]);

  useEffect(() => {
    if (pane === "local_blank" || pane === "cloud_blank") {
      nameRef.current?.focus();
    }
  }, [pane]);

  const filteredRoots = useMemo(() => {
    const q = rootQuery.trim().toLowerCase();
    if (!q) return roots;
    return roots.filter((r) => r.name.toLowerCase().includes(q));
  }, [roots, rootQuery]);

  const applyDraftProjectIntent = (folderId: string) => {
    const draft =
      useConversationStore.getState().currentConversationId === null;
    if (draft) {
      useFoldersStore.getState().setDraftWorkspaceIntent({
        kind: "project",
        folderId,
      });
    }
  };

  const finishCreated = (folder: FolderMeta) => {
    applyDraftProjectIntent(folder.id);
    useFoldersStore.getState().setPendingRename(folder.id);
    notifySuccess(`已创建项目「${folder.name}」`);
    onClose();
  };

  /** Same local binding already in cache → open (VS Code / Cursor reuse). */
  const finishOpened = (folder: FolderMeta) => {
    applyDraftProjectIntent(folder.id);
    notifySuccess(`已打开项目「${folder.name}」`);
    onClose();
  };

  const createOrOpenLocal = async (input: {
    name: string;
    localRootId: string;
    localSubpath: string | null;
  }) => {
    const existing = findLocalFolderByBinding(
      getFolders(),
      input.localRootId,
      input.localSubpath,
    );
    if (existing) {
      finishOpened(existing);
      return;
    }
    const { folder, created } = await createFolder.mutateAsync({
      name: input.name,
      mode: "local",
      localRootId: input.localRootId,
      localSubpath: input.localSubpath,
    });
    if (created) finishCreated(folder);
    else finishOpened(folder);
  };

  const createFromRoot = async (root: FsRoot) => {
    if (busy || createFolder.isPending) return;
    setBusy(true);
    try {
      await createOrOpenLocal({
        name: root.name,
        localRootId: root.id,
        localSubpath: null,
      });
    } catch (e) {
      notifyError(e, "创建项目失败");
    } finally {
      setBusy(false);
    }
  };

  const handlePickOther = async () => {
    if (busy || createFolder.isPending) return;
    setBusy(true);
    try {
      const result = await pickLocalFolderRoot();
      if (!result.ok) return;
      await createOrOpenLocal({
        name: result.root.name,
        localRootId: result.root.id,
        localSubpath: null,
      });
    } catch (e) {
      notifyError(e, "创建项目失败");
    } finally {
      setBusy(false);
      void loadRoots();
    }
  };

  const handleSubmitBlank = async (mode: "local" | "cloud") => {
    const trimmed = name.trim();
    if (!trimmed || busy || createFolder.isPending) return;
    setBusy(true);
    try {
      if (mode === "cloud") {
        const { folder } = await createFolder.mutateAsync({
          name: trimmed,
          mode: "cloud",
        });
        finishCreated(folder);
      } else {
        const rootId = await ensureDefaultContainerRoot();
        if (!rootId) {
          notifyError(new Error("无法初始化默认本地目录"), "创建项目失败");
          return;
        }
        await createOrOpenLocal({
          name: trimmed,
          localRootId: rootId,
          localSubpath: sanitizeProjectSubpath(trimmed),
        });
      }
    } catch (e) {
      notifyError(e, "创建项目失败");
    } finally {
      setBusy(false);
    }
  };

  const pending = busy || createFolder.isPending;

  if (!desktop) {
    return (
      <div className="w-72 p-3">
        <div className="mb-2 text-xs font-medium text-foreground">新建项目</div>
        <NamePane
          inputRef={nameRef}
          name={name}
          setName={setName}
          pending={pending}
          hint="云端空间 · 团队共享"
          onSubmit={() => void handleSubmitBlank("cloud")}
        />
      </div>
    );
  }

  return (
    <div className="flex max-h-[min(320px,50vh)]">
      <div className="flex w-40 shrink-0 flex-col border-r border-border py-1">
        <LeftRow
          icon={<FolderOpen size={14} />}
          label="本机文件夹"
          active={pane === "local_folder"}
          disabled={pending}
          onClick={() => setPane("local_folder")}
        />
        <LeftRow
          icon={<HardDrive size={14} />}
          label="本机空白"
          active={pane === "local_blank"}
          disabled={pending}
          onClick={() => setPane("local_blank")}
        />
        <LeftRow
          icon={<Cloud size={14} />}
          label="云端空白"
          active={pane === "cloud_blank"}
          disabled={pending}
          onClick={() => setPane("cloud_blank")}
        />
      </div>
      <div className="flex w-72 min-w-0 flex-col">
        {pane === "local_folder" ? (
          <LocalFolderPane
            query={rootQuery}
            onQueryChange={setRootQuery}
            roots={filteredRoots}
            loading={rootsLoading}
            pending={pending}
            onPickRoot={(r) => void createFromRoot(r)}
            onPickOther={() => void handlePickOther()}
          />
        ) : pane === "local_blank" ? (
          <div className="p-3">
            <NamePane
              inputRef={nameRef}
              name={name}
              setName={setName}
              pending={pending}
              hint={`~/Documents/AgentCore/${sanitizeProjectSubpath(name || "项目名")}`}
              onSubmit={() => void handleSubmitBlank("local")}
            />
          </div>
        ) : (
          <div className="p-3">
            <NamePane
              inputRef={nameRef}
              name={name}
              setName={setName}
              pending={pending}
              hint="云端空间 · 团队共享"
              onSubmit={() => void handleSubmitBlank("cloud")}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function LeftRow({
  icon,
  label,
  active,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm outline-none transition-colors",
        "disabled:pointer-events-none disabled:opacity-50",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}

function LocalFolderPane({
  query,
  onQueryChange,
  roots,
  loading,
  pending,
  onPickRoot,
  onPickOther,
}: {
  query: string;
  onQueryChange: (v: string) => void;
  roots: FsRoot[];
  loading: boolean;
  pending: boolean;
  onPickRoot: (root: FsRoot) => void;
  onPickOther: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-2.5 py-2">
        <SearchField
          value={query}
          onValueChange={onQueryChange}
          placeholder="筛选文件夹…"
          aria-label="筛选本机文件夹"
          inputClassName="text-xs"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {loading ? (
          <div className="flex items-center gap-2 px-2.5 py-2 text-xs text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            加载中…
          </div>
        ) : roots.length === 0 ? (
          <p className="px-2.5 py-2 text-xs text-muted-foreground">
            {query.trim() ? "没有匹配的文件夹" : "还没有已授权的文件夹"}
          </p>
        ) : (
          roots.map((r) => (
            <button
              key={r.id}
              type="button"
              disabled={pending}
              onClick={() => onPickRoot(r)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm text-foreground transition-colors hover:bg-accent disabled:opacity-50"
            >
              <FolderOpen
                size={14}
                className="shrink-0 text-muted-foreground"
              />
              <span className="min-w-0 flex-1 truncate">{r.name}</span>
            </button>
          ))
        )}
        {pending && (
          <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            创建中…
          </div>
        )}
      </div>
      <div className="border-t border-border p-1">
        <button
          type="button"
          disabled={pending}
          onClick={onPickOther}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
        >
          <Plus size={14} className="shrink-0" />
          <span className="min-w-0 flex-1 truncate">打开其他文件夹…</span>
        </button>
      </div>
    </div>
  );
}

function NamePane({
  inputRef,
  name,
  setName,
  pending,
  hint,
  onSubmit,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  name: string;
  setName: (v: string) => void;
  pending: boolean;
  hint: string;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-2">
      <input
        ref={inputRef}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter" && name.trim()) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder="项目名称"
        aria-label="项目名称"
        disabled={pending}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
      />
      <p className="truncate text-xs text-muted-foreground">{hint}</p>
      <div className="flex justify-end">
        <Button
          variant="primary"
          size="sm"
          disabled={!name.trim() || pending}
          onClick={onSubmit}
        >
          {pending ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              创建中…
            </>
          ) : (
            "创建"
          )}
        </Button>
      </div>
    </div>
  );
}
