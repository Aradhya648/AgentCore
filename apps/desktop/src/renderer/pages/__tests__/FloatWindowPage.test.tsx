// @vitest-environment jsdom
import { TooltipProvider } from "@/components/ui/tooltip";
import { FloatWindowPage } from "@/pages/FloatWindowPage";
import {
  WORKSPACE_TAB_ID,
  useSidePanelStore,
  type DetailTab,
} from "@/stores/sidePanel";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

vi.mock("@/components/layout/SidePanelSurfaceBody", () => ({
  SidePanelSurfaceBody: ({ tabId }: { tabId: string }) => (
    <div data-testid={`float-body-${tabId}`} />
  ),
  sidePanelFloatTitle: (tabId: string, tabs: readonly DetailTab[]) => {
    if (tabId === WORKSPACE_TAB_ID) return "工作区";
    return tabs.find((t) => t.id === tabId)?.title ?? "浮窗";
  },
}));

vi.mock("@/components/layout/WindowControls", () => ({
  WindowControls: () => <div data-testid="window-controls" />,
}));

vi.mock("@/lib/theme", () => ({
  useApplyTheme: () => undefined,
}));

afterEach(() => {
  cleanup();
  delete window.floatWindowApi;
});

beforeEach(() => {
  useSidePanelStore.setState({
    open: false,
    width: 400,
    tabs: [],
    activeTabId: WORKSPACE_TAB_ID,
    floats: [],
    focusSurface: { type: "dock" },
  });
});

function renderFloat(search: string) {
  const ui: ReactElement = (
    <TooltipProvider>
      <MemoryRouter initialEntries={[`/float${search}`]}>
        <Routes>
          <Route path="/float" element={<FloatWindowPage />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
  return render(ui);
}

describe("FloatWindowPage", () => {
  it("renders a thin shell without AppShell chrome and shows empty when tab data missing", () => {
    renderFloat("?cid=conv-1&tab=run:missing");
    expect(screen.getByTestId("float-window-page")).toBeTruthy();
    expect(screen.getByTestId("float-window-empty")).toBeTruthy();
    expect(screen.getByText("面板数据尚未同步")).toBeTruthy();
    expect(screen.queryByTestId("float-body-run:missing")).toBeNull();
  });

  it("renders SidePanelSurfaceBody when workspace tab needs no store row", () => {
    renderFloat(`?cid=conv-1&tab=${WORKSPACE_TAB_ID}`);
    expect(screen.getByTestId(`float-body-${WORKSPACE_TAB_ID}`)).toBeTruthy();
    expect(screen.queryByTestId("float-window-empty")).toBeNull();
    expect(screen.getByText("工作区")).toBeTruthy();
  });

  it("renders body for a run tab present in the store", () => {
    const tab: DetailTab = {
      id: "run:abc",
      kind: "run",
      title: "Worker",
      messageId: "m1",
      runId: "abc",
    };
    useSidePanelStore.setState({ tabs: [tab], activeTabId: tab.id });
    renderFloat("?cid=conv-1&tab=run:abc");
    expect(screen.getByTestId("float-body-run:abc")).toBeTruthy();
    expect(screen.getByText("Worker")).toBeTruthy();
  });

  it("renders system WindowControls only (no pin / custom close)", () => {
    const tab: DetailTab = {
      id: "run:abc",
      kind: "run",
      title: "Worker",
      messageId: "m1",
      runId: "abc",
    };
    useSidePanelStore.setState({ tabs: [tab], activeTabId: tab.id });
    renderFloat("?cid=conv-1&tab=run:abc");

    expect(screen.getByTestId("window-controls")).toBeTruthy();
    expect(screen.queryByLabelText("钉回主坞")).toBeNull();
    expect(screen.queryByLabelText("关闭浮窗")).toBeNull();
  });

  it("shows missing-params empty state when tab query is absent", () => {
    renderFloat("?cid=conv-1");
    expect(screen.getByText("缺少浮窗参数")).toBeTruthy();
  });
});
