import type { DesktopNotifyRequiredPayload } from "@/types/events";
import { beforeEach, describe, expect, it, vi } from "vitest";

const resolveInteraction = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/interaction", () => ({
  resolveInteraction: (...args: unknown[]) => resolveInteraction(...args),
}));

import { performDesktopNotify } from "../desktopNotify";

function payload(
  over: Partial<DesktopNotifyRequiredPayload> = {},
): DesktopNotifyRequiredPayload {
  return {
    request_id: "req-1",
    conversation_id: "conv-1",
    title: "任务完成",
    body: "请查看",
    ...over,
  };
}

describe("performDesktopNotify", () => {
  beforeEach(() => {
    resolveInteraction.mockClear();
    vi.stubGlobal("window", {
      notificationApi: {
        show: vi.fn().mockResolvedValue({ ok: true }),
      },
    });
  });

  it("shows notification and posts client_tool result", async () => {
    await performDesktopNotify(payload(), "conv-1");
    expect(window.notificationApi?.show).toHaveBeenCalledWith({
      title: "任务完成",
      body: "请查看",
      conversationId: "conv-1",
    });
    expect(resolveInteraction).toHaveBeenCalledWith(
      "conv-1",
      "req-1",
      expect.objectContaining({
        kind: "client_tool",
        ok: true,
        value: { shown: true },
      }),
    );
  });

  it("returns error envelope when notificationApi missing", async () => {
    vi.stubGlobal("window", {});
    await performDesktopNotify(payload(), "conv-1");
    expect(resolveInteraction).toHaveBeenCalledWith(
      "conv-1",
      "req-1",
      expect.objectContaining({ ok: false }),
    );
  });
});
