import { dispatchHandoffJob } from "@/services/handoff";
import { useBackgroundTasksStore } from "@/stores/backgroundTasks";

/** 把一条任务派发为后台云端任务（交接「方案 B」/ P2e e2）。 */
export function dispatchBackgroundTask(convId: string, task: string): void {
  const store = useBackgroundTasksStore.getState();
  const tempId = crypto.randomUUID();
  const now = new Date().toISOString();
  const base = {
    id: tempId,
    sourceConversationId: convId,
    jobConversationId: "",
    baseSnapshotId: "",
    resultSnapshotId: null as string | null,
    task,
    createdAt: now,
    finishedAt: null as string | null,
  };
  store.upsert(convId, {
    ...base,
    status: "pending",
    error: null,
    updatedAt: now,
  });
  void dispatchHandoffJob(convId, task)
    .then(() => store.load(convId))
    .catch((err) => {
      store.upsert(convId, {
        ...base,
        status: "failed",
        error: err instanceof Error ? err.message : "派发失败",
        updatedAt: new Date().toISOString(),
      });
    });
}
