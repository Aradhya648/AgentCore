/**
 * L3「团队浏览器」M2 接管留档 store (stores/browserTakeover.ts) 单测：
 * - load：服务端权威列表覆盖，并保留尚未被收录的本地乐观项（去重按 id，防慢速 GET 抹掉刚记的接管）。
 * - addLocal：乐观并入本场接管（自铸 `local:` id + 起止时刻）。
 * - clearConversation：丢分桶。
 * mock `@/services/browserTakeover` 的 listBrowserTakeovers。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/browserTakeover", () => ({
  listBrowserTakeovers: vi.fn(),
}));

import { listBrowserTakeovers } from "@/services/browserTakeover";
import { useBrowserTakeoverStore } from "../browserTakeover";

const store = () => useBrowserTakeoverStore.getState();
const mockList = vi.mocked(listBrowserTakeovers);

beforeEach(() => {
  useBrowserTakeoverStore.setState({ byConversation: {} });
  mockList.mockReset();
});

describe("load", () => {
  it("adopts the server list for the conversation", async () => {
    mockList.mockResolvedValue([
      {
        id: "s1",
        startedAt: "2026-07-20T00:00:00Z",
        endedAt: "2026-07-20T00:01:00Z",
      },
    ]);
    await store().load("c1");
    expect(store().byConversation.c1).toEqual([
      {
        id: "s1",
        startedAt: "2026-07-20T00:00:00Z",
        endedAt: "2026-07-20T00:01:00Z",
      },
    ]);
  });

  it("preserves local-only optimistic records not yet on the server", async () => {
    store().addLocal("c1", "2026-07-20T00:00:00Z", "2026-07-20T00:00:30Z");
    const localId = store().byConversation.c1[0].id;
    mockList.mockResolvedValue([
      {
        id: "s1",
        startedAt: "2026-07-20T01:00:00Z",
        endedAt: "2026-07-20T01:01:00Z",
      },
    ]);
    await store().load("c1");
    const ids = store().byConversation.c1.map((t) => t.id);
    expect(ids).toContain("s1");
    expect(ids).toContain(localId);
  });
});

describe("addLocal", () => {
  it("appends a record with a local: id and the given start/end", () => {
    store().addLocal("c1", "2026-07-20T00:00:00Z", "2026-07-20T00:00:05Z");
    const rec = store().byConversation.c1[0];
    expect(rec.startedAt).toBe("2026-07-20T00:00:00Z");
    expect(rec.endedAt).toBe("2026-07-20T00:00:05Z");
    expect(rec.id).toMatch(/^local:/);
  });
});

describe("clearConversation", () => {
  it("drops the conversation's bucket", () => {
    store().addLocal("c1", "a", "b");
    store().clearConversation("c1");
    expect(store().byConversation.c1).toBeUndefined();
  });

  it("is a no-op for an unknown conversation", () => {
    store().clearConversation("nope");
    expect(store().byConversation).toEqual({});
  });
});
