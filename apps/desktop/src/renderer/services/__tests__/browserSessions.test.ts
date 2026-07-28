import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  api: {
    get: vi.fn(),
    delete: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import { api } from "@/services/api";
import {
  closeBrowserSession,
  createBrowserSession,
  listBrowserSessions,
  navigateBrowserSession,
} from "../browserSessions";

const getMock = vi.mocked(api.get);
const deleteMock = vi.mocked(api.delete);
const postMock = vi.mocked(api.post);

beforeEach(() => {
  getMock.mockReset();
  deleteMock.mockReset();
  postMock.mockReset();
});

describe("browserSessions service", () => {
  it("listBrowserSessions maps snake_case wire to camelCase", async () => {
    getMock.mockResolvedValue({
      data: [
        {
          session_id: "s1",
          conversation_id: "c1",
          host_kind: "sandbox",
          control: "agent",
          run_id: null,
          created_at: 10,
          last_used: 20,
        },
      ],
      active_session_id: "s1",
    });

    const result = await listBrowserSessions("c1");
    expect(getMock).toHaveBeenCalledWith(
      "/v1/conversations/c1/browser/sessions",
    );
    expect(result).toEqual({
      sessions: [
        {
          sessionId: "s1",
          conversationId: "c1",
          hostKind: "sandbox",
          control: "agent",
          runId: null,
          createdAt: 10,
          lastUsed: 20,
          url: null,
          title: null,
        },
      ],
      activeSessionId: "s1",
    });
  });

  it("createBrowserSession POSTs host_kind sandbox by default", async () => {
    postMock.mockResolvedValue({
      session_id: "s-new",
      conversation_id: "c1",
      host_kind: "sandbox",
      control: "agent",
      run_id: null,
      created_at: 1,
      last_used: 1,
    });
    const info = await createBrowserSession("c1", {
      hostKind: "sandbox",
      activate: true,
    });
    expect(postMock).toHaveBeenCalledWith(
      "/v1/conversations/c1/browser/sessions",
      { host_kind: "sandbox", activate: true },
    );
    expect(info.sessionId).toBe("s-new");
    expect(info.hostKind).toBe("sandbox");
  });

  it("navigateBrowserSession POSTs url to …/navigate", async () => {
    postMock.mockResolvedValue({
      session_id: "s1",
      conversation_id: "c1",
      host_kind: "sandbox",
      control: "agent",
      run_id: null,
      created_at: 1,
      last_used: 2,
      url: "https://example.com/",
    });
    const info = await navigateBrowserSession(
      "c1",
      "s1",
      "https://example.com/",
    );
    expect(postMock).toHaveBeenCalledWith(
      "/v1/conversations/c1/browser/sessions/s1/navigate",
      { url: "https://example.com/" },
    );
    expect(info.url).toBe("https://example.com/");
  });

  it("closeBrowserSession DELETEs the session path", async () => {
    deleteMock.mockResolvedValue({});
    await closeBrowserSession("c1", "s1");
    expect(deleteMock).toHaveBeenCalledWith(
      "/v1/conversations/c1/browser/sessions/s1",
    );
  });
});
