import { api } from "@/services/api";
import { DEFAULT_PERMISSION_AXES } from "@/services/permissionAxes";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  absoluteWebhookUrl,
  ackStandingTaskRun,
  countInboxBadge,
  createStandingTask,
  listStandingTaskRuns,
  listStandingTasks,
  patchStandingTask,
  rotateWebhookSecret,
  runStandingTaskNow,
  scheduleLabel,
  toStandingTask,
  toStandingTaskRun,
  triggerSourceLabel,
} from "../standingTasks";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});

const apiGet = vi.mocked(api.get);
const apiPost = vi.mocked(api.post);
const apiPatch = vi.mocked(api.patch);

const sampleTaskWire = {
  id: "st-1",
  name: "周一简报",
  trigger_kind: "schedule",
  schedule_preset: "weekly_mon",
  cron: null,
  folder_id: "fold-cloud",
  goal: "汇总竞品动态",
  permission_axes: DEFAULT_PERMISSION_AXES,
  enabled: true,
  next_run_at: "2026-08-04T01:00:00Z",
  conversation_id: null,
  created_at: "2026-07-28T00:00:00Z",
  updated_at: "2026-07-28T00:00:00Z",
};

const sampleWebhookWire = {
  id: "st-wh",
  name: "线索接入",
  trigger_kind: "webhook",
  schedule_preset: null,
  cron: null,
  folder_id: "fold-cloud",
  goal: "分诊新线索",
  permission_axes: DEFAULT_PERMISSION_AXES,
  enabled: true,
  next_run_at: null,
  conversation_id: null,
  webhook_id: "wh-uuid-1",
  webhook_url: "https://api.example.com/v1/hooks/standing/wh-uuid-1",
  webhook_secret: "sec_once_only",
  created_at: "2026-07-28T00:00:00Z",
  updated_at: "2026-07-28T00:00:00Z",
};

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPatch.mockReset();
});

describe("standingTasks mapping", () => {
  it("maps wire → domain", () => {
    const t = toStandingTask(sampleTaskWire);
    expect(t.folderId).toBe("fold-cloud");
    expect(t.triggerKind).toBe("schedule");
    expect(t.schedulePreset).toBe("weekly_mon");
    expect(t.nextRunAt).toBe("2026-08-04T01:00:00Z");
    expect(t.webhookSecret).toBeNull();
    expect(scheduleLabel(t)).toBe("每周一");
  });

  it("defaults missing trigger_kind to schedule", () => {
    const { trigger_kind: _, ...legacy } = sampleTaskWire;
    void _;
    const t = toStandingTask(legacy);
    expect(t.triggerKind).toBe("schedule");
  });

  it("maps webhook wire including one-shot secret", () => {
    const t = toStandingTask(sampleWebhookWire);
    expect(t.triggerKind).toBe("webhook");
    expect(t.webhookId).toBe("wh-uuid-1");
    expect(t.webhookUrl).toContain("/v1/hooks/standing/");
    expect(t.webhookSecret).toBe("sec_once_only");
    expect(scheduleLabel(t)).toBe("Webhook");
  });

  it("absolutizes relative webhook_url with API base", () => {
    expect(absoluteWebhookUrl("/v1/hooks/standing/wh-1")).toMatch(
      /^https?:\/\/.+\/v1\/hooks\/standing\/wh-1$/,
    );
    expect(absoluteWebhookUrl("https://x.test/v1/hooks/standing/wh-1")).toBe(
      "https://x.test/v1/hooks/standing/wh-1",
    );
    const t = toStandingTask({
      ...sampleWebhookWire,
      webhook_url: "/v1/hooks/standing/wh-uuid-1",
      webhook_secret: null,
    });
    expect(t.webhookUrl).toMatch(/^https?:\/\/.+\/v1\/hooks\/standing\/wh-uuid-1$/);
  });

  it("maps run wire and accepts read_at alias", () => {
    const r = toStandingTaskRun({
      id: "run-1",
      standing_task_id: "st-1",
      task_name: "周一简报",
      status: "failed",
      conversation_id: "c1",
      summary: null,
      error: "quota exceeded",
      read_at: "2026-07-28T02:00:00Z",
      created_at: "2026-07-28T01:00:00Z",
    });
    expect(r.ackedAt).toBe("2026-07-28T02:00:00Z");
    expect(r.status).toBe("failed");
    expect(r.triggerSource).toBeNull();
  });

  it("maps trigger_source when present", () => {
    const r = toStandingTaskRun({
      id: "run-2",
      standing_task_id: "st-wh",
      status: "succeeded",
      trigger_source: "webhook",
      created_at: "2026-07-28T01:00:00Z",
    });
    expect(r.triggerSource).toBe("webhook");
    expect(triggerSourceLabel("webhook")).toBe("Webhook");
    expect(triggerSourceLabel("manual")).toBe("手动");
  });
});

describe("standingTasks API", () => {
  it("lists tasks from array or wrapped payload", async () => {
    apiGet.mockResolvedValueOnce([sampleTaskWire]);
    expect((await listStandingTasks())[0]?.id).toBe("st-1");

    apiGet.mockResolvedValueOnce({ items: [sampleTaskWire] });
    expect((await listStandingTasks())[0]?.name).toBe("周一简报");
  });

  it("creates schedule with trigger_kind", async () => {
    apiPost.mockResolvedValueOnce(sampleTaskWire);
    await createStandingTask({
      name: "周一简报",
      triggerKind: "schedule",
      schedulePreset: "weekly_mon",
      folderId: "fold-cloud",
      goal: "汇总竞品动态",
      permissionAxes: DEFAULT_PERMISSION_AXES,
    });
    expect(apiPost).toHaveBeenCalledWith("/v1/standing-tasks", {
      name: "周一简报",
      trigger_kind: "schedule",
      schedule_preset: "weekly_mon",
      folder_id: "fold-cloud",
      goal: "汇总竞品动态",
      permission_axes: DEFAULT_PERMISSION_AXES,
      enabled: true,
    });
  });

  it("creates webhook without schedule fields", async () => {
    apiPost.mockResolvedValueOnce(sampleWebhookWire);
    const t = await createStandingTask({
      name: "线索接入",
      triggerKind: "webhook",
      folderId: "fold-cloud",
      goal: "分诊新线索",
      permissionAxes: DEFAULT_PERMISSION_AXES,
    });
    expect(apiPost).toHaveBeenCalledWith("/v1/standing-tasks", {
      name: "线索接入",
      trigger_kind: "webhook",
      folder_id: "fold-cloud",
      goal: "分诊新线索",
      permission_axes: DEFAULT_PERMISSION_AXES,
      enabled: true,
    });
    expect(t.webhookSecret).toBe("sec_once_only");
  });

  it("patches enabled", async () => {
    apiPatch.mockResolvedValueOnce({ ...sampleTaskWire, enabled: false });
    const t = await patchStandingTask("st-1", { enabled: false });
    expect(t.enabled).toBe(false);
    expect(apiPatch).toHaveBeenCalledWith("/v1/standing-tasks/st-1", {
      enabled: false,
    });
  });

  it("patches switch to webhook without schedule fields", async () => {
    apiPatch.mockResolvedValueOnce(sampleWebhookWire);
    await patchStandingTask("st-1", {
      triggerKind: "webhook",
      name: "线索接入",
    });
    expect(apiPatch).toHaveBeenCalledWith("/v1/standing-tasks/st-1", {
      trigger_kind: "webhook",
      name: "线索接入",
    });
  });

  it("rotates webhook secret", async () => {
    apiPost.mockResolvedValueOnce({
      webhook_secret: "sec_rotated",
      webhook_url: sampleWebhookWire.webhook_url,
      webhook_id: "wh-uuid-1",
    });
    const r = await rotateWebhookSecret("st-wh");
    expect(apiPost).toHaveBeenCalledWith(
      "/v1/standing-tasks/st-wh/rotate-webhook-secret",
      {},
    );
    expect(r.webhookSecret).toBe("sec_rotated");
    expect(r.task).toBeNull();
  });

  it("runs now and acks", async () => {
    apiPost.mockResolvedValueOnce({
      id: "run-1",
      standing_task_id: "st-1",
      status: "running",
      created_at: "2026-07-28T03:00:00Z",
    });
    const run = await runStandingTaskNow("st-1");
    expect(run?.status).toBe("running");
    expect(apiPost).toHaveBeenCalledWith("/v1/standing-tasks/st-1/run", {});

    apiPost.mockResolvedValueOnce({
      id: "run-1",
      standing_task_id: "st-1",
      status: "failed",
      acked_at: "2026-07-28T04:00:00Z",
      created_at: "2026-07-28T03:00:00Z",
    });
    const acked = await ackStandingTaskRun("run-1");
    expect(acked.ackedAt).toBe("2026-07-28T04:00:00Z");
  });

  it("counts inbox badge from server badge field", async () => {
    apiGet.mockResolvedValueOnce({ items: [], badge: 3 });
    expect(await countInboxBadge()).toBe(3);
    expect(apiGet).toHaveBeenCalledWith("/v1/standing-task-runs?limit=1");
  });

  it("counts inbox badge (awaiting + unacked failed) without badge field", async () => {
    apiGet.mockResolvedValueOnce({
      items: [
        {
          id: "r1",
          standing_task_id: "st-1",
          status: "awaiting_user",
          created_at: "2026-07-28T01:00:00Z",
        },
        {
          id: "r2",
          standing_task_id: "st-1",
          status: "failed",
          acked_at: null,
          created_at: "2026-07-28T01:00:00Z",
        },
        {
          id: "r3",
          standing_task_id: "st-1",
          status: "failed",
          acked_at: "2026-07-28T02:00:00Z",
          created_at: "2026-07-28T01:00:00Z",
        },
        {
          id: "r4",
          standing_task_id: "st-1",
          status: "succeeded",
          created_at: "2026-07-28T01:00:00Z",
        },
      ],
    });
    expect(await countInboxBadge()).toBe(2);
    expect(apiGet).toHaveBeenCalledWith("/v1/standing-task-runs?limit=1");
  });

  it("lists runs with status query", async () => {
    apiGet.mockResolvedValueOnce([]);
    await listStandingTaskRuns({ status: ["failed", "awaiting_user"] });
    const url = apiGet.mock.calls[0]?.[0] as string;
    expect(url).toContain("status=failed");
    expect(url).toContain("status=awaiting_user");
  });
});
