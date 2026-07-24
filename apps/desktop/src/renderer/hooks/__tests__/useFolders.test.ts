import {
  addFolderCache,
  patchFolderCache,
  removeFolderFromCache,
} from "@/hooks/useFolders";
import { queryClient } from "@/lib/queryClient";
import { conversationKeys } from "@/lib/queryKeys";
import type { FolderMeta } from "@/services/folders";
import { beforeEach, describe, expect, it } from "vitest";

const mk = (id: string, name = id): FolderMeta => ({
  id,
  name,
  mode: "cloud",
  localRootId: null,
  localSubpath: null,
});

function readFolders(): FolderMeta[] {
  return (
    queryClient.getQueryData<{ folders: FolderMeta[] }>(
      conversationKeys.grouped,
    )?.folders ?? []
  );
}

function seed(folders: FolderMeta[], conversations: unknown[] = []): void {
  queryClient.setQueryData(conversationKeys.grouped, {
    folders,
    conversations,
  });
}

beforeEach(() => {
  queryClient.clear();
});

// The folder list shares the /grouped cache entry with conversations. These
// helpers (used by the folder mutations + the workspace-bind mirror) must touch
// only the folders half, leaving the conversations half intact.
describe("folder list cache helpers", () => {
  it("addFolderCache prepends onto a cold cache", () => {
    addFolderCache(mk("a"));
    expect(readFolders().map((f) => f.id)).toEqual(["a"]);
  });

  it("addFolderCache prepends newest-first and dedupes by id", () => {
    seed([mk("a"), mk("b")]);
    addFolderCache(mk("c"));
    expect(readFolders().map((f) => f.id)).toEqual(["c", "a", "b"]);

    addFolderCache(mk("b", "renamed"));
    expect(readFolders().map((f) => f.id)).toEqual(["b", "c", "a"]);
    expect(readFolders()[0].name).toBe("renamed");
  });

  it("patchFolderCache shallow-merges one folder", () => {
    seed([mk("a", "Work"), mk("b", "Notes")]);
    patchFolderCache("a", { name: "Renamed" });
    expect(readFolders().find((f) => f.id === "a")?.name).toBe("Renamed");
    expect(readFolders().find((f) => f.id === "b")?.name).toBe("Notes");
  });

  it("patchFolderCache is a no-op for an unknown id", () => {
    seed([mk("a", "Work")]);
    patchFolderCache("missing", { name: "x" });
    expect(readFolders()[0].name).toBe("Work");
  });

  it("removeFolderFromCache drops the matching folder", () => {
    seed([mk("a"), mk("b")]);
    removeFolderFromCache("a");
    expect(readFolders().map((f) => f.id)).toEqual(["b"]);
  });

  it("preserves the conversations half of the shared cache entry", () => {
    seed([mk("a")], [{ id: "c1" }]);
    addFolderCache(mk("b"));
    patchFolderCache("a", { name: "X" });
    removeFolderFromCache("b");
    const data = queryClient.getQueryData<{
      folders: FolderMeta[];
      conversations: { id: string }[];
    }>(conversationKeys.grouped);
    expect(data?.conversations).toEqual([{ id: "c1" }]);
    expect(data?.folders.map((f) => f.id)).toEqual(["a"]);
  });
});
