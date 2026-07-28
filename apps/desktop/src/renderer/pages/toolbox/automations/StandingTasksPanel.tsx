import { Button, Card } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api";
import { type FolderMeta, listFolders } from "@/services/folders";
import {
  type StandingTask,
  deleteStandingTask,
  listStandingTasks,
  patchStandingTask,
  runStandingTaskNow,
  scheduleLabel,
} from "@/services/standingTasks";
import { useStandingInboxStore } from "@/stores/standingInbox";
import { Loader2, Pencil, Plus, Trash2, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  StandingTaskEditorDrawer,
  emptyStandingTaskForm,
  formFromStandingTask,
} from "./StandingTaskEditor";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

function formatNextRun(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      weekday: "short",
    });
  } catch {
    return iso;
  }
}

/**
 * 自动化 · 任务列表。创建/编辑走右侧抽屉，不在本页内联堆表单。
 */
export function StandingTasksPanel() {
  const [tasks, setTasks] = useState<StandingTask[] | null>(null);
  const [cloudFolders, setCloudFolders] = useState<FolderMeta[]>([]);
  const [folderNames, setFolderNames] = useState<Record<string, string>>({});
  const [listError, setListError] = useState<string | null>(null);
  const [editor, setEditor] = useState<"create" | StandingTask | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setListError(null);
    try {
      const [taskList, folders] = await Promise.all([
        listStandingTasks(),
        listFolders().catch(() => [] as FolderMeta[]),
      ]);
      const cloud = folders.filter((f) => f.mode === "cloud");
      setCloudFolders(cloud);
      setFolderNames(
        Object.fromEntries(folders.map((f) => [f.id, f.name] as const)),
      );
      setTasks(taskList);
    } catch (e) {
      setListError(errMsg(e, "加载任务失败（后端可能尚未就绪）"));
      setTasks([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onToggle = async (task: StandingTask, enabled: boolean) => {
    setBusyId(task.id);
    try {
      const next = await patchStandingTask(task.id, { enabled });
      setTasks((prev) =>
        (prev ?? []).map((t) => (t.id === task.id ? next : t)),
      );
      notifySuccess(enabled ? "已启用" : "已暂停");
    } catch (e) {
      notifyError(e, "更新失败");
    } finally {
      setBusyId(null);
    }
  };

  const onRunNow = async (task: StandingTask) => {
    setBusyId(task.id);
    try {
      const { runId } = await runStandingTaskNow(task.id);
      notifySuccess(`已触发运行（${runId.slice(0, 8)}…）`);
      void useStandingInboxStore.getState().refresh();
    } catch (e) {
      notifyError(e, "触发失败");
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (task: StandingTask) => {
    if (!window.confirm(`确定删除「${task.name}」？删除后不再触发。`)) return;
    setBusyId(task.id);
    try {
      await deleteStandingTask(task.id);
      setTasks((prev) => (prev ?? []).filter((t) => t.id !== task.id));
      notifySuccess("已删除");
    } catch (e) {
      notifyError(e, "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  const editorOpen = editor !== null;

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          到点或外部 Webhook 由 CEO 开一轮协作；结果在「收件箱」审阅。
        </p>
        <Button
          size="md"
          icon={<Plus size={14} />}
          disabled={editorOpen}
          onClick={() => setEditor("create")}
        >
          新建
        </Button>
      </div>

      <StandingTaskEditorDrawer
        open={editorOpen}
        mode={editor === "create" || editor === null ? "create" : "edit"}
        initial={
          editor === "create" || editor === null
            ? emptyStandingTaskForm(cloudFolders)
            : formFromStandingTask(editor)
        }
        taskId={editor === "create" || editor === null ? null : editor.id}
        cloudFolders={cloudFolders}
        onClose={() => setEditor(null)}
        onSaved={async () => {
          setEditor(null);
          await load();
        }}
      />

      <section className="mt-6">
        {tasks === null ? (
          <Loader2
            size={16}
            className="animate-spin text-muted-foreground/50"
          />
        ) : listError ? (
          <p className="text-sm text-destructive">{listError}</p>
        ) : tasks.length === 0 ? (
          <Card className="px-4 py-6 text-center">
            <p className="text-sm text-muted-foreground">
              还没有任务。创建一个周期简报或 Webhook 入口，自动开跑。
            </p>
            <Button
              className="mt-3"
              size="md"
              icon={<Plus size={14} />}
              onClick={() => setEditor("create")}
            >
              新建任务
            </Button>
          </Card>
        ) : (
          <ul className="space-y-3">
            {tasks.map((task) => {
              const busy = busyId === task.id;
              return (
                <li key={task.id}>
                  <Card className="px-4 py-3">
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground">
                            {task.name}
                          </p>
                          <span
                            className={cn(
                              "rounded-lg px-2 py-0.5 text-xs font-medium",
                              task.enabled
                                ? "bg-success/10 text-success"
                                : "bg-muted text-muted-foreground",
                            )}
                          >
                            {task.enabled ? "运行中" : "已暂停"}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {scheduleLabel(task)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                          {task.goal}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          工作区：{folderNames[task.folderId] ?? task.folderId}
                          {task.triggerKind === "schedule" && (
                            <>
                              {" · "}下次：{formatNextRun(task.nextRunAt)}
                            </>
                          )}
                          {task.triggerKind === "webhook" &&
                            task.webhookUrl && <>{" · "}Webhook 已就绪</>}
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
                        <Switch
                          checked={task.enabled}
                          disabled={busy}
                          onCheckedChange={(v) => void onToggle(task, v)}
                          label={task.enabled ? "启用" : "暂停"}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy || !task.enabled}
                          icon={<Zap size={14} />}
                          onClick={() => void onRunNow(task)}
                          title="立即跑一次"
                        >
                          跑一次
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          icon={<Pencil size={14} />}
                          onClick={() => setEditor(task)}
                        >
                          编辑
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={busy}
                          icon={<Trash2 size={14} />}
                          onClick={() => void onDelete(task)}
                        >
                          删除
                        </Button>
                      </div>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
