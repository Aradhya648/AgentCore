// @vitest-environment jsdom
import { dispatchBackgroundTask } from "@/components/chat/message-input/dispatchBackgroundTask";
import type { HandoffJob } from "@/services/handoff";
import { dispatchHandoffJob, listHandoffJobs } from "@/services/handoff";
import { getWorkspaceBinding } from "@/services/workspaceBinding";
import {
  useBackgroundTasksStore,
  useBackgroundTasksSync,
} from "@/stores/backgroundTasks";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/handoff", () => ({
  listHandoffJobs: vi.fn(),
  dispatchHandoffJob: vi.fn(),
}));
vi.mock("@/services/workspaceBinding", () => ({
  getWorkspaceBinding: vi.fn(),
}));

const listJobs = vi.mocked(listHandoffJobs);
const dispatchJob = vi.mocked(dispatchHandoffJob);
const getBinding = vi.mocked(getWorkspaceBinding);

const store = () => useBackgroundTasksStore.getState();

const job = (over: Partial<HandoffJob> = {}): HandoffJob => ({
  id: "job-1",
  sourceConversationId: "c1",
  jobConversationId: "job-conv-1",
  baseSnapshotId: "snap-base",
  resultSnapshotId: null,
  task: "调研竞品",
  status: "running",
  error: null,
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-10T00:00:00Z",
  finishedAt: null,
  ...over,
});

beforeEach(() => {
  useBackgroundTasksStore.setState({
    byConversation: {},
    modeByConversation: {},
    rootIdByConversation: {},
  });
  listJobs.mockReset();
  dispatchJob.mockReset();
  getBinding.mockReset();
  getBinding.mockResolvedValue({
    mode: "local",
    scope: "conversation",
    rootId: "root-1",
    source: "explicit",
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("backgroundTasks store", () => {
  it("load overlays the authoritative job list for a conversation", async () => {
    listJobs.mockResolvedValueOnce([job({ status: "succeeded" })]);
    await store().load("c1");
    expect(listJobs).toHaveBeenCalledWith("c1");
    expect(store().byConversation.c1).toEqual([job({ status: "succeeded" })]);
  });

  it("upsert inserts then replaces by id (optimistic → poll refresh)", () => {
    store().upsert("c1", job({ id: "temp", status: "pending" }));
    expect(store().byConversation.c1).toHaveLength(1);
    store().upsert("c1", job({ id: "temp", status: "failed", error: "x" }));
    expect(store().byConversation.c1).toEqual([
      job({ id: "temp", status: "failed", error: "x" }),
    ]);
    store().upsert("c1", job({ id: "job-2", status: "running" }));
    expect(store().byConversation.c1.map((j) => j.id)).toEqual([
      "job-2",
      "temp",
    ]);
  });

  it("ensureMode caches local binding + rootId; cloud on failure", async () => {
    const mode = await store().ensureMode("c1");
    expect(mode).toBe("local");
    expect(store().modeByConversation.c1).toBe("local");
    expect(store().rootIdByConversation.c1).toBe("root-1");
    expect(getBinding).toHaveBeenCalledTimes(1);

    // Cached — no second binding fetch.
    await store().ensureMode("c1");
    expect(getBinding).toHaveBeenCalledTimes(1);

    getBinding.mockRejectedValueOnce(new Error("draft"));
    const cloud = await store().ensureMode("c2");
    expect(cloud).toBe("cloud");
    expect(store().rootIdByConversation.c2).toBeNull();
  });
});

describe("dispatch → poll (dispatchBackgroundTask)", () => {
  it("optimistic pending, then load replaces with server jobs on success", async () => {
    let resolveDispatch!: () => void;
    dispatchJob.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDispatch = () =>
          resolve({ jobId: "job-1", jobConversationId: "job-conv-1" });
      }),
    );
    listJobs.mockResolvedValueOnce([job({ status: "running" })]);

    dispatchBackgroundTask("c1", "调研竞品");

    const pending = store().byConversation.c1;
    expect(pending).toHaveLength(1);
    expect(pending[0].status).toBe("pending");
    expect(pending[0].task).toBe("调研竞品");
    expect(dispatchJob).toHaveBeenCalledWith("c1", "调研竞品");

    await act(async () => {
      resolveDispatch();
    });
    await waitFor(() => {
      expect(listJobs).toHaveBeenCalledWith("c1");
      expect(store().byConversation.c1[0].id).toBe("job-1");
      expect(store().byConversation.c1[0].status).toBe("running");
    });
  });

  it("marks the optimistic card failed when dispatch rejects", async () => {
    dispatchJob.mockRejectedValueOnce(new Error("网络异常"));
    dispatchBackgroundTask("c1", "失败任务");
    await waitFor(() => {
      const card = store().byConversation.c1[0];
      expect(card.status).toBe("failed");
      expect(card.error).toBe("网络异常");
    });
  });
});

describe("useBackgroundTasksSync 轮询", () => {
  it("polls listHandoffJobs every 4s while a local job is in flight", async () => {
    // Seed mode + in-flight job so the interval effect arms without waiting on
    // ensureMode (avoids fake-timer + waitFor deadlock).
    useBackgroundTasksStore.setState({
      byConversation: { c1: [job({ status: "running" })] },
      modeByConversation: { c1: "local" },
      rootIdByConversation: { c1: "root-1" },
    });
    listJobs.mockResolvedValue([job({ status: "running" })]);
    vi.useFakeTimers();

    const { unmount, rerender } = renderHook(() =>
      useBackgroundTasksSync("c1"),
    );

    // mode===local effect fires an immediate load.
    await act(async () => {
      await Promise.resolve();
    });
    expect(listJobs.mock.calls.length).toBeGreaterThanOrEqual(1);
    const afterInitial = listJobs.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(listJobs.mock.calls.length).toBeGreaterThan(afterInitial);

    // Authoritative success clears inFlight → interval tears down.
    listJobs.mockResolvedValue([job({ status: "succeeded" })]);
    await act(async () => {
      await store().load("c1");
    });
    rerender();
    const afterSuccess = listJobs.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(listJobs.mock.calls.length).toBe(afterSuccess);

    unmount();
  });

  it("skips load/poll for cloud conversations", async () => {
    getBinding.mockResolvedValueOnce({
      mode: "cloud",
      scope: "conversation",
      rootId: null,
      source: null,
    });
    renderHook(() => useBackgroundTasksSync("c-cloud"));
    await waitFor(() => {
      expect(store().modeByConversation["c-cloud"]).toBe("cloud");
    });
    expect(listJobs).not.toHaveBeenCalled();
  });
});
