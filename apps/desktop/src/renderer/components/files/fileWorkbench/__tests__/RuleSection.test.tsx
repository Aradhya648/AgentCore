// @vitest-environment jsdom
/**
 * RuleSection —「规则」under AgentCore convention tree:
 * GLOBAL lists only global rules; project scope filters by folderId.
 */

import { ApiError } from "@/services/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/documents", () => ({
  listUserRules: vi.fn(),
  createRuleDocument: vi.fn(),
  deleteDocument: vi.fn(),
  renameDocument: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({
  notifyActionError: vi.fn(),
  notifySuccess: vi.fn(),
}));

import { createRuleDocument, listUserRules } from "@/services/documents";
import { RuleSection } from "../RuleSection";

const rule = (over: Record<string, unknown> = {}) => ({
  id: "r",
  parentId: null,
  folderId: null,
  kind: "document" as const,
  role: "rule" as const,
  aiMaintained: false,
  applyMode: "always",
  name: "r.md",
  content: "",
  version: "v",
  ...over,
});

function renderGlobal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onOpen = vi.fn();
  const onDeleted = vi.fn();
  const onRenamed = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <RuleSection
        scope={{ kind: "global" }}
        activePath={null}
        onOpen={onOpen}
        onDeleted={onDeleted}
        onRenamed={onRenamed}
      />
    </QueryClientProvider>,
  );
  return { onOpen, onDeleted, onRenamed };
}

function renderProject(folderId = "F1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onOpen = vi.fn();
  const onDeleted = vi.fn();
  const onRenamed = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <RuleSection
        scope={{ kind: "project", folderId }}
        activePath={null}
        onOpen={onOpen}
        onDeleted={onDeleted}
        onRenamed={onRenamed}
      />
    </QueryClientProvider>,
  );
  return { onOpen, onDeleted, onRenamed };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(listUserRules).mockResolvedValue([]);
});

afterEach(cleanup);

describe("RuleSection (global)", () => {
  it("lists GLOBAL rules without a 项目规则 aggregator", async () => {
    vi.mocked(listUserRules).mockResolvedValue([
      rule({ id: "g1", name: "语气规则.md" }),
    ]);
    renderGlobal();

    expect(await screen.findByText("语气规则.md")).toBeTruthy();
    expect(screen.getByText("新建规则")).toBeTruthy();
    expect(screen.queryByText("项目规则")).toBeNull();
    expect(screen.queryByText("你的规则")).toBeNull();
    expect(screen.getByText("规则")).toBeTruthy();
  });

  it("shows an empty hint when there are no global rules yet", async () => {
    renderGlobal();
    expect(await screen.findByText("还没有全局规则")).toBeTruthy();
  });

  it("opens a rule in the detail pane (path = its doc id)", async () => {
    vi.mocked(listUserRules).mockResolvedValue([
      rule({ id: "g1", name: "语气规则.md" }),
    ]);
    const { onOpen } = renderGlobal();

    fireEvent.click(await screen.findByText("语气规则.md"));
    expect(onOpen).toHaveBeenCalledWith("g1", "语气规则.md");
  });

  it("creates a GLOBAL rule with a fresh name and opens it", async () => {
    vi.mocked(createRuleDocument).mockResolvedValue(
      rule({ id: "new", name: "新规则.md" }),
    );
    const { onOpen } = renderGlobal();

    await screen.findByText("新建规则");
    await act(async () => {
      fireEvent.click(screen.getByText("新建规则"));
    });

    expect(createRuleDocument).toHaveBeenCalledWith("新规则.md", null);
    await waitFor(() =>
      expect(onOpen).toHaveBeenCalledWith("new", "新规则.md"),
    );
  });

  it("shows a calm unavailable state when the backend predates /documents", async () => {
    vi.mocked(listUserRules).mockRejectedValue(new ApiError(404, "not found"));
    renderGlobal();
    expect(await screen.findByText(/暂不可用/)).toBeTruthy();
  });
});

describe("RuleSection (project)", () => {
  it("lists only that project's rules and creates a project-scoped rule", async () => {
    vi.mocked(listUserRules).mockResolvedValue([
      rule({ id: "g1", name: "全局.md" }),
      rule({ id: "p1", folderId: "F1", name: "部署规则.md" }),
      rule({ id: "p2", folderId: "F2", name: "别的项目.md" }),
    ]);
    vi.mocked(createRuleDocument).mockResolvedValue(
      rule({ id: "p3", folderId: "F1", name: "新规则.md" }),
    );
    const { onOpen } = renderProject("F1");

    fireEvent.click(screen.getByText("规则"));
    expect(await screen.findByText("部署规则.md")).toBeTruthy();
    expect(screen.queryByText("全局.md")).toBeNull();
    expect(screen.queryByText("别的项目.md")).toBeNull();
    expect(screen.queryByText("项目规则")).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByText("新建规则"));
    });
    expect(createRuleDocument).toHaveBeenCalledWith("新规则.md", "F1");
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p3", "新规则.md"));
  });

  it("shows project empty state", async () => {
    renderProject();
    fireEvent.click(screen.getByText("规则"));
    expect(await screen.findByText("本项目还没有规则")).toBeTruthy();
  });
});
