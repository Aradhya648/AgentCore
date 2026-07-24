// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useConversations", () => ({
  getConversations: vi.fn(),
}));
vi.mock("@/services/sidecarRouting", () => ({
  resolveConversationLocalTarget: vi.fn(),
}));

import { getConversations } from "@/hooks/useConversations";
import { resolveConversationLocalTarget } from "@/services/sidecarRouting";
import { trashBareConversationScratch } from "@/services/trashBareScratch";

const getConvs = getConversations as unknown as ReturnType<typeof vi.fn>;
const resolveTarget = resolveConversationLocalTarget as unknown as ReturnType<
  typeof vi.fn
>;

describe("trashBareConversationScratch", () => {
  beforeEach(() => {
    getConvs.mockReset();
    resolveTarget.mockReset();
    window.fsApi = {
      trashPath: vi.fn().mockResolvedValue({ ok: true, data: undefined }),
    } as unknown as typeof window.fsApi;
  });

  it("trashes bare-chat scratch subpath after resolve", async () => {
    getConvs.mockReturnValue([
      { id: "c1", folderId: null, localContainerRootId: "container" },
    ]);
    resolveTarget.mockResolvedValue({
      rootId: "container",
      subpath: "conversations/c1",
    });
    await trashBareConversationScratch("c1");
    expect(window.fsApi.trashPath).toHaveBeenCalledWith(
      "container",
      "conversations/c1",
    );
  });

  it("skips project chats (shared folder workspace)", async () => {
    getConvs.mockReturnValue([
      { id: "c1", folderId: "f1", localContainerRootId: null },
    ]);
    await trashBareConversationScratch("c1");
    expect(resolveTarget).not.toHaveBeenCalled();
    expect(window.fsApi.trashPath).not.toHaveBeenCalled();
  });

  it("never trashes an empty subpath (would hit the whole root)", async () => {
    getConvs.mockReturnValue([
      { id: "c1", folderId: null, localContainerRootId: "container" },
    ]);
    resolveTarget.mockResolvedValue({ rootId: "container", subpath: "" });
    await trashBareConversationScratch("c1");
    expect(window.fsApi.trashPath).not.toHaveBeenCalled();
  });
});
