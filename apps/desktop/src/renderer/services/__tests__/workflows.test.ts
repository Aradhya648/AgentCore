import { ApiError, api } from "@/services/api";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createAgentStepNode,
  createHumanGateNode,
  emptyWorkflowDefinition,
  parseWorkflowDefinition,
  validateWorkflowDefinition,
} from "../workflowDefinition";
import {
  __resetWorkflowClientForTests,
  createWorkflow,
  createWorkflowFromPlaybook,
  listWorkflowTemplates,
  listWorkflows,
  patchWorkflow,
  toUserWorkflow,
  toWorkflowTemplate,
} from "../workflows";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});

const apiGet = vi.mocked(api.get);
const apiPost = vi.mocked(api.post);
const apiPatch = vi.mocked(api.patch);

function stubLocalStorage() {
  const store: Record<string, string> = {};
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
    clear: () => {
      for (const k of Object.keys(store)) delete store[k];
    },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() {
      return Object.keys(store).length;
    },
  } as Storage;
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPatch.mockReset();
  __resetWorkflowClientForTests();
  stubLocalStorage();
});

afterEach(() => {
  (globalThis as { localStorage?: Storage }).localStorage = undefined;
});

describe("workflowDefinition", () => {
  it("accepts a simple linear graph", () => {
    const a = createAgentStepNode({
      id: "n1",
      role: "调研员",
      task: "收集竞品",
    });
    const g = createHumanGateNode({ id: "n2", label: "审初稿" });
    const issues = validateWorkflowDefinition({
      nodes: [a, g],
      edges: [{ from: "n1", to: "n2" }],
    });
    expect(issues).toEqual([]);
  });

  it("rejects cycles and empty agent fields", () => {
    const a = createAgentStepNode({ id: "n1", role: "", task: "" });
    const b = createAgentStepNode({
      id: "n2",
      role: "写手",
      task: "写稿",
    });
    const issues = validateWorkflowDefinition({
      nodes: [a, b],
      edges: [
        { from: "n1", to: "n2" },
        { from: "n2", to: "n1" },
      ],
    });
    const codes = issues.map((i) => i.code);
    expect(codes).toContain("empty_role");
    expect(codes).toContain("empty_task");
    expect(codes).toContain("cycle");
  });

  it("parseWorkflowDefinition drops unknown kinds", () => {
    const def = parseWorkflowDefinition({
      nodes: [
        { id: "n1", kind: "agent_step", role: "A", task: "T" },
        { id: "x", kind: "start" },
      ],
      edges: [{ from: "n1", to: "x" }],
    });
    expect(def.nodes).toHaveLength(1);
    expect(def.edges).toHaveLength(1);
  });
});

describe("workflows client", () => {
  it("maps wire → domain", () => {
    const w = toUserWorkflow({
      id: "wf-1",
      name: "三步质检",
      description: null,
      definition: emptyWorkflowDefinition(),
      version: 2,
      created_at: "2026-07-31T00:00:00Z",
      updated_at: "2026-07-31T01:00:00Z",
    });
    expect(w.name).toBe("三步质检");
    expect(w.version).toBe(2);
    expect(w.definition.nodes).toEqual([]);
  });

  it("falls back to localStorage when API is 404", async () => {
    apiGet.mockRejectedValue(new ApiError(404, "not found"));
    apiPost.mockRejectedValue(new ApiError(404, "not found"));
    apiPatch.mockRejectedValue(new ApiError(404, "not found"));

    expect(await listWorkflows()).toEqual([]);

    const created = await createWorkflow({
      name: "本地草稿",
      definition: {
        nodes: [
          createAgentStepNode({
            id: "n1",
            role: "调研员",
            task: "收集",
          }),
        ],
        edges: [],
      },
    });
    expect(created.localOnly).toBe(true);
    expect(created.name).toBe("本地草稿");

    const listed = await listWorkflows();
    expect(listed).toHaveLength(1);
    expect(listed[0]?.id).toBe(created.id);

    const patched = await patchWorkflow(created.id, { name: "改名" });
    expect(patched.name).toBe("改名");
    expect(patched.version).toBe(1);
  });

  it("uses remote when API responds", async () => {
    apiGet.mockResolvedValueOnce([
      {
        id: "wf-remote",
        name: "远程",
        description: null,
        definition: { nodes: [], edges: [] },
        version: 1,
        created_at: "2026-07-31T00:00:00Z",
        updated_at: "2026-07-31T00:00:00Z",
      },
    ]);
    const list = await listWorkflows();
    expect(list[0]?.id).toBe("wf-remote");
    expect(list[0]?.localOnly).toBeFalsy();
  });
});

describe("workflow templates / from-playbook (§10.8)", () => {
  it("maps template wire with slots", () => {
    const t = toWorkflowTemplate({
      id: "research_report",
      title: "调研报告",
      summary: "成文专线",
      slots: [{ key: "topic", label: "主题", required: true, hint: "议题" }],
    });
    expect(t.id).toBe("research_report");
    expect(t.title).toBe("调研报告");
    expect(t.slots).toEqual([
      { key: "topic", label: "主题", required: true, hint: "议题" },
    ]);
  });

  it("fills fallback primary slots when API omits them", () => {
    const t = toWorkflowTemplate({
      id: "build_website",
      title: "建站",
      summary: "文案→前端→QA",
      primary_slots: "site（必填，站点/落地页简述）",
    });
    expect(t.slots[0]?.key).toBe("site");
    expect(t.slots[0]?.required).toBe(true);
    expect(t.slots[0]?.hint).toContain("site");
  });

  it("listWorkflowTemplates returns empty on 404 (hide official section)", async () => {
    apiGet.mockRejectedValueOnce(new ApiError(404, "not found"));
    expect(await listWorkflowTemplates()).toEqual([]);
    expect(apiGet).toHaveBeenCalledWith("/v1/workflow-playbook-templates");
  });

  it("listWorkflowTemplates maps remote catalog", async () => {
    apiGet.mockResolvedValueOnce([
      {
        id: "parallel_brief",
        title: "多角对齐摸底",
        summary: "N 路并行摸底",
        slots: [
          { key: "topic", label: "主题" },
          { key: "angles", label: "方向" },
        ],
      },
    ]);
    const list = await listWorkflowTemplates();
    expect(list).toHaveLength(1);
    expect(list[0]?.id).toBe("parallel_brief");
    expect(list[0]?.slots.map((s) => s.key)).toEqual(["topic", "angles"]);
  });

  it("createWorkflowFromPlaybook posts playbook + slots", async () => {
    apiPost.mockResolvedValueOnce({
      id: "wf-from-pb",
      name: "我的建站",
      description: null,
      definition: { nodes: [], edges: [] },
      version: 1,
      created_at: "2026-07-31T00:00:00Z",
      updated_at: "2026-07-31T00:00:00Z",
    });
    const created = await createWorkflowFromPlaybook({
      playbook: "build_website",
      name: "我的建站",
      slots: { site: "SaaS 营销官网" },
    });
    expect(created.id).toBe("wf-from-pb");
    expect(created.localOnly).toBeFalsy();
    expect(apiPost).toHaveBeenCalledWith("/v1/workflows/from-playbook", {
      playbook: "build_website",
      name: "我的建站",
      slots: { site: "SaaS 营销官网" },
    });
  });

  it("createWorkflowFromPlaybook does not fall back locally on 404", async () => {
    apiPost.mockRejectedValueOnce(new ApiError(404, "not found"));
    await expect(
      createWorkflowFromPlaybook({
        playbook: "research_report",
        slots: { topic: "AI 监管" },
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
