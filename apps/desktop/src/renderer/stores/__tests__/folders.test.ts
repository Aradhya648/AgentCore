import { beforeEach, describe, expect, it } from "vitest";
import { defaultDraftWorkspaceIntent, useFoldersStore } from "../folders";

const store = () => useFoldersStore.getState();

beforeEach(() => {
  useFoldersStore.setState({
    pendingRenameId: null,
    draftWorkspaceIntent: defaultDraftWorkspaceIntent(),
  });
});

describe("pending markers", () => {
  it("tracks pending rename independently of draft intent", () => {
    store().setPendingRename("a");
    store().setDraftWorkspaceIntent({ kind: "project", folderId: "b" });
    expect(store().pendingRenameId).toBe("a");
    expect(store().draftWorkspaceIntent).toEqual({
      kind: "project",
      folderId: "b",
    });

    store().setPendingRename(null);
    expect(store().pendingRenameId).toBeNull();
    expect(store().draftWorkspaceIntent).toEqual({
      kind: "project",
      folderId: "b",
    });
  });

  it("switches among quick local / cloud / project intents", () => {
    store().setDraftWorkspaceIntent({ kind: "quick_cloud" });
    expect(store().draftWorkspaceIntent).toEqual({ kind: "quick_cloud" });

    store().setDraftWorkspaceIntent({ kind: "project", folderId: "f1" });
    expect(store().draftWorkspaceIntent).toEqual({
      kind: "project",
      folderId: "f1",
    });

    store().resetDraftWorkspaceIntent();
    expect(store().draftWorkspaceIntent).toEqual({ kind: "quick_cloud" });
  });
});

describe("defaultDraftWorkspaceIntent", () => {
  it("defaults to quick_cloud (桌面裸聊默认切云)", () => {
    expect(defaultDraftWorkspaceIntent()).toEqual({ kind: "quick_cloud" });
  });
});
