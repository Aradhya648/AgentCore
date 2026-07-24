import { beforeEach, describe, expect, it, vi } from "vitest";

// The document FileSource is a thin path-aware dispatcher over the REST client: the tab path
// IS the document id, so readForEdit/writeText must call the matching service with that id and
// forward the CAS baseline. Mock the service so the test pins the dispatch (the only logic).
vi.mock("@/services/documents", () => ({
  getDocument: vi.fn(() =>
    Promise.resolve({
      id: "d1",
      parentId: null,
      folderId: null,
      kind: "document",
      role: "rule",
      aiMaintained: false,
      applyMode: "always",
      name: "用户规则.md",
      content: "body",
      version: "v1",
    }),
  ),
  writeDocument: vi.fn(() =>
    Promise.resolve({ ok: true, version: "v2", conflict: false }),
  ),
}));

import { getDocument, writeDocument } from "@/services/documents";
import { createDocumentSource } from "@/services/sources/documentSource";

const src = createDocumentSource();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("documentSource", () => {
  it("advertises an editable, non-transfer source", () => {
    expect(src.caps.edit).toBe(true);
    expect(src.caps.transfer).toBe(false);
    expect(src.readForEdit).toBeDefined();
    expect(src.writeText).toBeDefined();
  });

  it("readForEdit loads the doc by its id (= the tab path) and carries the CAS etag", async () => {
    const doc = await src.readForEdit?.("d1");
    expect(getDocument).toHaveBeenCalledWith("d1");
    expect(doc).toEqual({
      text: "body",
      version: { etag: "v1" },
      encoding: "utf-8",
      eol: "lf",
    });
  });

  it("writeText forwards the id + content + baseline etag", async () => {
    const r = await src.writeText?.("d1", {
      content: "next",
      encoding: "utf-8",
      eol: "lf",
      baseline: { etag: "v1" },
    });
    expect(writeDocument).toHaveBeenCalledWith("d1", "next", "v1");
    expect(r).toEqual({ ok: true, version: { etag: "v2" } });
  });

  it("writeText treats a missing baseline as an unconditional write (null)", async () => {
    await src.writeText?.("d1", {
      content: "x",
      encoding: "utf-8",
      eol: "lf",
      baseline: null,
    });
    expect(writeDocument).toHaveBeenCalledWith("d1", "x", null);
  });

  it("maps a write conflict into the source-agnostic conflict result", async () => {
    vi.mocked(writeDocument).mockResolvedValueOnce({
      ok: false,
      version: "live",
      conflict: true,
    });
    const r = await src.writeText?.("d1", {
      content: "y",
      encoding: "utf-8",
      eol: "lf",
      baseline: { etag: "stale" },
    });
    expect(r).toEqual({
      ok: false,
      reason: "conflict",
      version: { etag: "live" },
    });
  });

  it("rejects tree / CRUD ops the editor never uses (listed directly by the rail instead)", async () => {
    await expect(src.createFile("x")).rejects.toThrow();
    await expect(src.mkdir("x")).rejects.toThrow();
    await expect(src.move("a", "b")).rejects.toThrow();
    await expect(src.delete("x")).rejects.toThrow();
    await expect(src.listDir("")).resolves.toEqual([]);
  });
});
