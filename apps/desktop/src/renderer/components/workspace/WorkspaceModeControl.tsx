import { Button } from "@/components/ui";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { getConversations } from "@/hooks/useConversations";
import { getFolders } from "@/hooks/useFolders";
import { WORKSPACE_BINDING_CHANGED } from "@/lib/bindLocalFolder";
import {
  type EffectiveWorkspace,
  formatWorkspaceChipLabel,
  resolveEffectiveWorkspace,
} from "@/lib/workspaceEffectiveMode";
import { runHandoff } from "@/services/handoff";
import {
  type WorkspaceBinding,
  getWorkspaceBinding,
} from "@/services/workspaceBinding";
import type { FsRoot } from "@shared/ipc-contract";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Cloud,
  HardDrive,
  Loader2,
  UploadCloud,
} from "lucide-react";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * Shared workspace mode control — read-only status for established chats
 * (project inherit / bare scratch). Bind/unbind UI removed (出生定终身);
 * backup/export-style actions remain for local workspaces.
 */

export interface WorkspaceModeState {
  binding: WorkspaceBinding;
  roots: FsRoot[];
  effective: EffectiveWorkspace;
  busy: boolean;
  error: string | null;
  backingUp: boolean;
  backupDone: boolean;
  backup: () => Promise<void>;
  refresh: () => Promise<void>;
}

export function useWorkspaceModeState(
  conversationId: string | null,
): WorkspaceModeState | null {
  const [binding, setBinding] = useState<WorkspaceBinding | null>(null);
  const [roots, setRoots] = useState<FsRoot[]>([]);
  const [containerRootId, setContainerRootId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backingUp, setBackingUp] = useState(false);
  const [backupDone, setBackupDone] = useState(false);

  const fsApi = typeof window !== "undefined" ? window.fsApi : undefined;

  const loadRoots = useCallback(
    (): Promise<FsRoot[]> => fsApi?.listRoots() ?? Promise.resolve([]),
    [fsApi],
  );

  const refresh = useCallback(async () => {
    if (!conversationId) return;
    const conv =
      getConversations().find((c) => c.id === conversationId) ?? null;
    setContainerRootId(conv?.localContainerRootId ?? null);
    const folder = conv?.folderId
      ? (getFolders().find((f) => f.id === conv.folderId) ?? null)
      : null;
    setProjectName(folder?.name ?? null);
    try {
      const [b, r] = await Promise.all([
        getWorkspaceBinding(conversationId),
        loadRoots(),
      ]);
      setBinding(b);
      setRoots(r);
    } catch {
      setBinding(null);
    }
  }, [conversationId, loadRoots]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!conversationId) return;
    const onChanged = (e: Event) => {
      const detail = (e as CustomEvent<{ conversationId?: string }>).detail;
      if (detail?.conversationId === conversationId) void refresh();
    };
    window.addEventListener(WORKSPACE_BINDING_CHANGED, onChanged);
    return () =>
      window.removeEventListener(WORKSPACE_BINDING_CHANGED, onChanged);
  }, [conversationId, refresh]);

  const backup = async () => {
    if (!conversationId) return;
    setBackingUp(true);
    setError(null);
    setBackupDone(false);
    setBusy(true);
    try {
      await runHandoff(conversationId);
      setBackupDone(true);
      setTimeout(() => setBackupDone(false), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "备份失败，请重试");
    } finally {
      setBackingUp(false);
      setBusy(false);
    }
  };

  const effective = useMemo(
    () =>
      resolveEffectiveWorkspace({
        binding,
        localContainerRootId: containerRootId,
        roots,
        projectName,
      }),
    [binding, containerRootId, roots, projectName],
  );

  if (!conversationId || !binding) return null;

  return {
    binding,
    roots,
    effective,
    busy,
    error,
    backingUp,
    backupDone,
    backup,
    refresh,
  };
}

/** Compact trigger used by the dock bar and composer chip. */
export function WorkspaceModeTrigger({
  effective,
  className = "",
  chevron = true,
}: {
  effective: EffectiveWorkspace;
  className?: string;
  chevron?: boolean;
}) {
  const { isLocal, rootMissing } = effective;
  const label = formatWorkspaceChipLabel(effective);
  return (
    <span
      className={`inline-flex min-w-0 items-center gap-1.5 overflow-hidden ${className}`}
    >
      {isLocal && rootMissing ? (
        <AlertTriangle size={13} className="shrink-0 text-muted-foreground" />
      ) : isLocal ? (
        <HardDrive size={13} className="shrink-0 text-primary" />
      ) : (
        <Cloud size={13} className="shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 truncate">{label}</span>
      {chevron && (
        <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
      )}
    </span>
  );
}

/** Read-only status + optional backup for local workspaces. */
export function WorkspaceModeMenu({
  state,
  onActionDone: _onActionDone,
}: {
  state: WorkspaceModeState;
  onActionDone?: () => void;
}) {
  const { effective, busy, error, backingUp, backupDone, backup } = state;
  const { isLocal, rootMissing, rootName, viaProject, projectName } = effective;

  const title = viaProject
    ? projectName
      ? `项目 · ${projectName}`
      : "项目工作区"
    : isLocal
      ? "本机草稿"
      : "云端草稿";

  const subtitle = isLocal
    ? rootMissing
      ? "目录在本机不可用"
      : rootName
        ? viaProject
          ? `本地 · ${rootName}`
          : `默认容器 · ${rootName}`
        : "本机草稿"
    : viaProject
      ? "云端共享空间"
      : "快速对话 · 文件随对话保存在云端";

  return (
    <>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <span
          className={`flex size-7 shrink-0 items-center justify-center rounded-lg ${
            isLocal
              ? "bg-primary/10 text-primary"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {isLocal ? <HardDrive size={15} /> : <Cloud size={15} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-foreground">
            {title}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {subtitle}
          </div>
        </div>
      </div>

      <div className="p-1.5">
        {isLocal && !rootMissing ? (
          backingUp ? (
            <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              备份中…
            </div>
          ) : backupDone ? (
            <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-success">
              <Check size={14} />
              已备份
            </div>
          ) : (
            <ModeAction
              icon={<UploadCloud size={14} />}
              label="备份到云"
              onClick={() => void backup()}
              disabled={busy}
            />
          )
        ) : (
          <p className="px-2.5 py-1.5 text-xs text-muted-foreground">
            工作区在创建时已确定，会话期间不可改绑。
          </p>
        )}

        {busy && !backingUp && (
          <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            处理中…
          </div>
        )}
        {error && (
          <p className="px-2.5 py-1.5 text-xs text-destructive">{error}</p>
        )}
      </div>
    </>
  );
}

function ModeAction({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: ReactNode;
  label: string;
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
      {label}
    </Button>
  );
}

/** Full control: trigger + shared popover (dock mode bar). */
export function WorkspaceModeControl({
  conversationId,
  triggerClassName,
}: {
  conversationId: string;
  triggerClassName?: string;
}) {
  const state = useWorkspaceModeState(conversationId);
  const [pop, setPop] = useState(false);

  if (!state) return null;

  return (
    <Popover open={pop} onOpenChange={setPop}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          className={
            triggerClassName ??
            `h-auto min-w-0 shrink gap-1.5 overflow-hidden px-2 py-1 text-xs font-medium ${
              state.effective.isLocal && state.effective.rootMissing
                ? "text-muted-foreground"
                : "text-foreground"
            }`
          }
        >
          <WorkspaceModeTrigger effective={state.effective} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-0">
        <WorkspaceModeMenu state={state} />
      </PopoverContent>
    </Popover>
  );
}
