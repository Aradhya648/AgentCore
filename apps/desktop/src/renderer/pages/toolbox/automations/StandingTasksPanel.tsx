import { Button, Card } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api";
import { type FolderMeta, listFolders } from "@/services/folders";
import {
  type StandingTask,
  type StandingTaskTemplate,
  deleteStandingTask,
  ensureStandingTaskTemplate,
  listStandingTaskTemplates,
  listStandingTasks,
  localHmFromUtcCron,
  patchStandingTask,
  runStandingTaskNow,
  scheduleLabel,
} from "@/services/standingTasks";
import { useStandingInboxStore } from "@/stores/standingInbox";
import { Loader2, Pencil, Plus, Sparkles, Trash2, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  StandingTaskEditorDrawer,
  emptyStandingTaskForm,
  formFromStandingTask,
} from "./StandingTaskEditor";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
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

function taskScheduleText(task: StandingTask): string {
  if (task.templateKey) {
    const { hour, minute } = localHmFromUtcCron(task.cron);
    return `每天 ${pad2(hour)}:${pad2(minute)}`;
  }
  return scheduleLabel(task);
}

/**
 * 自动化 · 任务列表。创建/编辑走右侧抽屉，不在本页内联堆表单。
 */
export function StandingTasksPanel() {
  const [tasks, setTasks] = useState<StandingTask[] | null>(null);
  const [templates, setTemplates] = useState<StandingTaskTemplate[]>([]);
  const [cloudFolders, setCloudFolders] = useState<FolderMeta[]>([]);
  const [folderNames, setFolderNames] = useState<Record<string, string>>({});
  const [listError, setListError] = useState<string | null>(null);
  const [editor, setEditor] = useState<"create" | StandingTask | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [ensuringKey, setEnsuringKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setListError(null);
    try {
      const [taskList, folders, templateList] = await Promise.all([
        listStandingTasks(),
        listFolders().catch(() => [] as FolderMeta[]),
        listStandingTaskTemplates().catch(() => [] as StandingTaskTemplate[]),
      ]);
      const cloud = folders.filter((f) => f.mode === "cloud");
      setCloudFolders(cloud);
      setFolderNames(
        Object.fromEntries(folders.map((f) => [f.id, f.name] as const)),
      );
      setTasks(taskList);
      setTemplates(templateList);
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
      setTemplates((prev) =>
        prev.map((tpl) =>
          tpl.installedTaskId === task.id ? { ...tpl, enabled } : tpl,
        ),
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
      setTemplates((prev) =>
        prev.map((tpl) =>
          tpl.installedTaskId === task.id
            ? { ...tpl, installedTaskId: null, enabled: null }
            : tpl,
        ),
      );
      notifySuccess("已删除");
    } catch (e) {
      notifyError(e, "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  const openInstalledTemplate = (tpl: StandingTaskTemplate) => {
    const task = (tasks ?? []).find((t) => t.id === tpl.installedTaskId);
    if (task) {
      setEditor(task);
      return;
    }
    notifyError("未找到已安装任务，请刷新后重试");
  };

  const onEnsureTemplate = async (tpl: StandingTaskTemplate) => {
    if (tpl.installedTaskId) {
      openInstalledTemplate(tpl);
      return;
    }
    const folderId = cloudFolders[0]?.id;
    if (!folderId) {
      notifyError("请先创建一个云工作区，再开启系统模板");
      return;
    }
    setEnsuringKey(tpl.key);
    try {
      const task = await ensureStandingTaskTemplate(tpl.key, {
        folderId,
        enabled: false,
      });
      notifySuccess("已安装系统模板，请配置时间与作用域");
      setTasks((prev) => {
        const list = prev ?? [];
        if (list.some((t) => t.id === task.id)) {
          return list.map((t) => (t.id === task.id ? task : t));
        }
        return [task, ...list];
      });
      setTemplates((prev) =>
        prev.map((row) =>
          row.key === tpl.key
            ? {
                ...row,
                installedTaskId: task.id,
                enabled: task.enabled,
              }
            : row,
        ),
      );
      setEditor(task);
    } catch (e) {
      notifyError(e, "开启系统模板失败");
    } finally {
      setEnsuringKey(null);
    }
  };

  const editorOpen = editor !== null;

  const guideTemplates = templates.filter(
    (tpl) => !tpl.installedTaskId || tpl.enabled !== true,
  );

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

      {guideTemplates.length > 0 && (
        <section className="mt-4 space-y-3">
          <p className="text-xs font-medium text-muted-foreground">系统模板</p>
          {guideTemplates.map((tpl) => {
            const installed = !!tpl.installedTaskId;
            const ensuring = ensuringKey === tpl.key;
            return (
              <Card key={tpl.key} className="px-4 py-3">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Sparkles size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-foreground">
                        {tpl.title}
                      </p>
                      <span className="rounded-lg bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                        系统
                      </span>
                      {installed && (
                        <span className="rounded-lg bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                          已安装 · 未启用
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {tpl.description}
                    </p>
                    {installed && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        可在下方列表开启开关，或点「去配置」调整时间与作用域。
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col gap-1">
                    {installed ? (
                      <Button
                        size="md"
                        variant="neutral"
                        disabled={editorOpen}
                        icon={<Pencil size={14} />}
                        onClick={() => openInstalledTemplate(tpl)}
                      >
                        去配置
                      </Button>
                    ) : (
                      <Button
                        size="md"
                        disabled={editorOpen || ensuring}
                        icon={
                          ensuring ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <Sparkles size={14} />
                          )
                        }
                        onClick={() => void onEnsureTemplate(tpl)}
                      >
                        开启
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </section>
      )}

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
              还没有任务。可开启上方系统模板，或新建周期简报 / Webhook 入口。
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
              const isSystem = !!task.templateKey;
              return (
                <li key={task.id}>
                  <Card className="px-4 py-3">
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground">
                            {task.name}
                          </p>
                          {isSystem && (
                            <span className="rounded-lg bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                              系统
                            </span>
                          )}
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
                            {taskScheduleText(task)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                          {isSystem
                            ? "每日自动复盘近期对话，确认后才落盘记忆与文档。"
                            : task.goal}
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
