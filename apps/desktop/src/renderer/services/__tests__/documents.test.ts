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
  it("listUserRules keeps only user rule docs and partitions carry folderId (scope)", async () => {
    vi.mocked(api.get).mockResolvedValue([
      node({ id: "g", folder_id: null, name: "全局.md" }),
      node({ id: "p", folder_id: "F1", name: "项目.md" }),
      // AI memory: role=rule but ai_maintained → excluded (not user-settable here).
      node({ id: "m", ai_maintained: true, name: "画像.md" }),
      // The 记忆 root folder + plain docs are not user rules → excluded.
      node({ id: "root", kind: "folder", role: "general", name: "记忆" }),
      node({ id: "gen", role: "general", name: "note.md" }),
    ]);

    const rules = await listUserRules();
    expect(api.get).toHaveBeenCalledWith("/v1/documents");
    expect(rules.map((r) => r.id)).toEqual(["g", "p"]);
    expect(rules[0]).toMatchObject({ folderId: null, name: "全局.md" });
    expect(rules[1]).toMatchObject({ folderId: "F1", name: "项目.md" });
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
