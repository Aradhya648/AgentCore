import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from "@/services/api";
import {
  createRuleDocument,
  deleteDocument,
  getDocument,
  listUserRules,
  renameDocument,
  writeDocument,
} from "@/services/documents";

const node = (over: Record<string, unknown> = {}) => ({
  id: "n",
  parent_id: null,
  folder_id: null,
  kind: "document",
  role: "rule",
  ai_maintained: false,
  apply_mode: "always",
  name: "r.md",
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("documents client", () => {
  it("listUserRules collects AgentCore/规则 leaves and leftover top-level rules", async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/v1/documents") {
        return [
          node({ id: "legacy", folder_id: null, name: "旧顶层.md" }),
          node({
            id: "ac-g",
            kind: "folder",
            role: "general",
            name: "AgentCore",
            folder_id: null,
          }),
          node({
            id: "ac-p",
            kind: "folder",
            role: "general",
            name: "AgentCore",
            folder_id: "F1",
          }),
          node({ id: "m", ai_maintained: true, name: "画像.md" }),
          node({ id: "gen", role: "general", name: "note.md" }),
        ];
      }
      if (url === "/v1/documents?parent_id=ac-g") {
        return [
          node({
            id: "rules-g",
            kind: "folder",
            role: "general",
            name: "规则",
            parent_id: "ac-g",
          }),
        ];
      }
      if (url === "/v1/documents?parent_id=rules-g") {
        return [node({ id: "g", folder_id: null, name: "全局.md", parent_id: "rules-g" })];
      }
      if (url === "/v1/documents?parent_id=ac-p") {
        return [
          node({
            id: "rules-p",
            kind: "folder",
            role: "general",
            name: "规则",
            parent_id: "ac-p",
            folder_id: "F1",
          }),
        ];
      }
      if (url === "/v1/documents?parent_id=rules-p") {
        return [
          node({
            id: "p",
            folder_id: "F1",
            name: "项目.md",
            parent_id: "rules-p",
          }),
        ];
      }
      return [];
    });

    const rules = await listUserRules();
    expect(rules.map((r) => r.id).sort()).toEqual(["g", "legacy", "p"]);
    expect(rules.find((r) => r.id === "g")).toMatchObject({
      folderId: null,
      name: "全局.md",
    });
    expect(rules.find((r) => r.id === "p")).toMatchObject({
      folderId: "F1",
      name: "项目.md",
    });
  });

  it("getDocument maps the wire body + CAS version", async () => {
    vi.mocked(api.get).mockResolvedValue(
      node({ id: "d1", content: "hello", version: "v9" }),
    );
    const doc = await getDocument("d1");
    expect(api.get).toHaveBeenCalledWith("/v1/documents/d1");
    expect(doc).toMatchObject({
      content: "hello",
      version: "v9",
      role: "rule",
    });
  });

  it("createRuleDocument posts a user rule pinned to a scope (folder_id)", async () => {
    vi.mocked(api.post).mockResolvedValue(node({ id: "new", content: "" }));
    await createRuleDocument("新规则.md", "F1");
    expect(api.post).toHaveBeenCalledWith("/v1/documents", {
      name: "新规则.md",
      kind: "document",
      role: "rule",
      content: "",
      parent_id: null,
      folder_id: "F1",
    });
  });

  it("createRuleDocument defaults to the GLOBAL layer (folder_id null)", async () => {
    vi.mocked(api.post).mockResolvedValue(node({ id: "new" }));
    await createRuleDocument("g.md");
    expect(api.post).toHaveBeenCalledWith(
      "/v1/documents",
      expect.objectContaining({ folder_id: null }),
    );
  });

  it("writeDocument sends the content + CAS baseline", async () => {
    vi.mocked(api.put).mockResolvedValue({
      ok: true,
      version: "v2",
      conflict: false,
    });
    await writeDocument("d1", "body", "v1");
    expect(api.put).toHaveBeenCalledWith("/v1/documents/d1", {
      content: "body",
      baseline: "v1",
    });
  });

  it("renameDocument patches the name", async () => {
    vi.mocked(api.patch).mockResolvedValue(node({ id: "d1", name: "改名.md" }));
    const r = await renameDocument("d1", "改名.md");
    expect(api.patch).toHaveBeenCalledWith("/v1/documents/d1", {
      name: "改名.md",
    });
    expect(r.name).toBe("改名.md");
  });

  it("deleteDocument hits the delete endpoint", async () => {
    vi.mocked(api.delete).mockResolvedValue({
      ok: true,
      version: "",
      conflict: false,
    });
    await deleteDocument("d1");
    expect(api.delete).toHaveBeenCalledWith("/v1/documents/d1");
  });
});
