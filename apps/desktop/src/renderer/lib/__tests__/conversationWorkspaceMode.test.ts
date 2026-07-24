import { describe, expect, it } from "vitest";
import {
  deriveGroupWorkspaceIsLocal,
  isConversationLocal,
  shouldShowConversationCloudIcon,
} from "../conversationWorkspaceMode";

describe("conversationWorkspaceMode", () => {
  it("isConversationLocal follows container for bare chats and folder.mode for projects", () => {
    expect(isConversationLocal({ localContainerRootId: null })).toBe(false);
    expect(isConversationLocal({ localContainerRootId: "root-1" })).toBe(true);
    expect(
      isConversationLocal(
        { localContainerRootId: null, folderId: "f1" },
        { mode: "local" },
      ),
    ).toBe(true);
    expect(
      isConversationLocal(
        { localContainerRootId: null, folderId: "f1" },
        { mode: "cloud" },
      ),
    ).toBe(false);
  });

  it("deriveGroupWorkspaceIsLocal reads folder.mode", () => {
    expect(deriveGroupWorkspaceIsLocal({ mode: "local" })).toBe(true);
    expect(deriveGroupWorkspaceIsLocal({ mode: "cloud" })).toBe(false);
  });

  it("shouldShowConversationCloudIcon for bare and grouped rows", () => {
    const cloud = { localContainerRootId: null };
    const local = { localContainerRootId: "root" };

    expect(shouldShowConversationCloudIcon(cloud)).toBe(true);
    expect(shouldShowConversationCloudIcon(local)).toBe(false);

    expect(shouldShowConversationCloudIcon(local, true)).toBe(false);
    expect(shouldShowConversationCloudIcon(cloud, true)).toBe(true);
    expect(shouldShowConversationCloudIcon(local, false)).toBe(false);
    expect(shouldShowConversationCloudIcon(cloud, false)).toBe(false);
  });
});
