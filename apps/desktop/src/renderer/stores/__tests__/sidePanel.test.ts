import { beforeEach, describe, expect, it } from "vitest";
import { useCommandPanelStore } from "../commandPanel";
import { useConversationStore } from "../conversation";
import { type ExecutionPlan, useExecutionStore } from "../execution";
import {
  BROWSER_TAB_ID,
  type DetailTab,
  PREVIEW_TAB_ID,
  SIDE_PANEL_DEFAULT_WIDTH,
  SIDE_PANEL_MAX_TABS,
  SIDE_PANEL_MIN_WIDTH,
  WORKSPACE_TAB_ID,
  contentDetailTabId,
  runDetailTabId,
  sidePanelMaxWidth,
  simpleTurnDetailTabId,
  useSidePanelStore,
} from "../sidePanel";

const panel = () => useSidePanelStore.getState();
const exec = () => useExecutionStore.getState();
// Each turn's execution + focus lives in its own message slot (§9.3); this suite
// drives one message.
const MID = "msg-1";
const tabId = (runId: string) => runDetailTabId(MID, runId);

const plan: ExecutionPlan = {
  id: "exec-1",
  planType: "multi_agent",
  taskSummary: "分析对比 React 和 Vue",
  agents: [{ id: "agent-1", role: "研究员" }],
  runs: [{ id: "run-1", agentId: "agent-1", task: "研究", dependsOn: [] }],
};

const runDetail = (runId: string): DetailTab => ({
  kind: "run",
  id: runDetailTabId(MID, runId),
  title: runId,
  messageId: MID,
  runId,
});

beforeEach(() => {
  // The store hydrates from localStorage at import; pin a known baseline so each
  // test starts from a closed, default-width panel sitting on the 工作区 home tab.
  useSidePanelStore.setState({
    open: false,
    width: 400,
    tabs: [],
    activeTabId: WORKSPACE_TAB_ID,
    previewTab: null,
    dismissedContexts: new Set(),
    pendingBadge: 0,
  });
  useExecutionStore.setState({ byId: {} });
  useCommandPanelStore.setState({
    active: false,
    focusedMessageId: null,
  });
  useConversationStore.setState({ currentConversationId: null });
});

describe("setWidth", () => {
  it("clamps below the minimum", () => {
    panel().setWidth(100);
    expect(panel().width).toBe(SIDE_PANEL_MIN_WIDTH);
  });

  it("clamps above the dynamic (window-relative) maximum", () => {
    panel().setWidth(9999);
    expect(panel().width).toBe(sidePanelMaxWidth());
  });

  it("rounds and keeps an in-range value", () => {
    panel().setWidth(421.6);
    expect(panel().width).toBe(422);
  });
});

describe("reclampWidth（窗口缩小后收敛到新上限）", () => {
  it("collapses an over-wide width down to the current max", () => {
    // 直接注入越界宽度（绕过 setWidth 的 clamp），模拟「窗口缩小后旧宽度已超新上限」。
    useSidePanelStore.setState({ width: sidePanelMaxWidth() + 400 });
    panel().reclampWidth();
    expect(panel().width).toBe(sidePanelMaxWidth());
  });

  it("is a no-op while the current width still fits", () => {
    const before = panel().width;
    panel().reclampWidth();
    expect(panel().width).toBe(before);
  });
});

describe("cycleWidth（双击手柄在三档间循环）", () => {
  it("cycles 默认 → 最大 → 最小 → 默认", () => {
    panel().setWidth(SIDE_PANEL_DEFAULT_WIDTH);
    panel().cycleWidth();
    expect(panel().width).toBe(sidePanelMaxWidth());
    panel().cycleWidth();
    expect(panel().width).toBe(SIDE_PANEL_MIN_WIDTH);
    panel().cycleWidth();
    expect(panel().width).toBe(SIDE_PANEL_DEFAULT_WIDTH);
  });
});

describe("openTab", () => {
  it("opens the panel, appends and activates the run tab", () => {
    panel().openTab(runDetail("run-1"));
    expect(panel().open).toBe(true);
    expect(panel().tabs.map((t) => t.id)).toEqual([tabId("run-1")]);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });

  it("dedups by id and updates the title in place", () => {
    panel().openTab(runDetail("run-1"));
    panel().openTab({ ...runDetail("run-1"), title: "研究员" });
    expect(panel().tabs).toHaveLength(1);
    expect(panel().tabs[0].title).toBe("研究员");
  });

  it("activate:false keeps the current active tab", () => {
    panel().openTab(runDetail("run-1"));
    panel().openTab(runDetail("run-2"), { activate: false });
    expect(panel().tabs).toHaveLength(2);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });

  it("caps the strip at the maximum, dropping the oldest", () => {
    for (let i = 0; i < SIDE_PANEL_MAX_TABS + 2; i++) {
      panel().openTab(runDetail(`run-${i}`));
    }
    expect(panel().tabs).toHaveLength(SIDE_PANEL_MAX_TABS);
    // run-0 and run-1 were pushed out; run-2 is now the oldest.
    expect(panel().tabs[0].id).toBe(tabId("run-2"));
  });
});

describe("closeTab", () => {
  it("falls back to the neighbour run tab (next, else previous)", () => {
    panel().openTab(runDetail("run-1"));
    panel().openTab(runDetail("run-2"));
    panel().openTab(runDetail("run-3"));
    panel().setActiveTab(tabId("run-2"));
    panel().closeTab(tabId("run-2"));
    // Removing the active middle tab lands on its successor (run-3).
    expect(panel().tabs.map((t) => t.id)).toEqual([
      tabId("run-1"),
      tabId("run-3"),
    ]);
    expect(panel().activeTabId).toBe(tabId("run-3"));
  });

  it("falls back to the 工作区 home when the last run tab is closed", () => {
    panel().openTab(runDetail("run-1"));
    panel().closeTab(tabId("run-1"));
    expect(panel().tabs).toHaveLength(0);
    // The home tab is always there, so the panel stays open.
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(WORKSPACE_TAB_ID);
  });

  it("falls back to the 工作区 home when the last run tab is closed inside a debate room", () => {
    panel().openTab(runDetail("run-1"));
    panel().closeTab(tabId("run-1"));
    expect(panel().activeTabId).toBe(WORKSPACE_TAB_ID);
  });

  it("keeps the active tab when a different tab is closed", () => {
    panel().openTab(runDetail("run-1"));
    panel().openTab(runDetail("run-2"));
    panel().setActiveTab(tabId("run-2"));
    panel().closeTab(tabId("run-1"));
    expect(panel().tabs.map((t) => t.id)).toEqual([tabId("run-2")]);
    expect(panel().activeTabId).toBe(tabId("run-2"));
  });
});

describe("togglePanel", () => {
  it("opens, then closes (keeping the active tab)", () => {
    panel().showRunDetail(MID, "run-1");
    panel().togglePanel();
    expect(panel().open).toBe(false);
    expect(panel().activeTabId).toBe(tabId("run-1"));
    panel().togglePanel();
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });
});

describe("openPanel", () => {
  it("reveals the panel without changing the active tab", () => {
    // The 指挥台 auto-surface (前端UX设计.md §6.2) opens the dock on a new decision but
    // must not yank the user off a run-detail tab they're reading (子决策 A).
    panel().openTab(runDetail("run-1"));
    panel().togglePanel(); // close it, keeping run-1 active
    expect(panel().open).toBe(false);
    panel().openPanel();
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });
});

describe("showWorkspace", () => {
  it("reveals the panel on the 工作区 home tab", () => {
    panel().showWorkspace();
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(WORKSPACE_TAB_ID);
  });

  it("returns to the home tab from an active run tab without dropping it", () => {
    panel().openTab(runDetail("run-1"));
    panel().showWorkspace();
    expect(panel().activeTabId).toBe(WORKSPACE_TAB_ID);
    // The run tab is preserved in the strip, just no longer active.
    expect(panel().tabs.map((t) => t.id)).toEqual([tabId("run-1")]);
  });
});

describe("showRunDetail", () => {
  it("pins a run, reveals it, and activates its tab", () => {
    exec().startExecution(plan, MID);
    panel().showWorkspace();
    panel().showRunDetail(MID, "run-1", "研究员");
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(tabId("run-1"));
    expect(panel().tabs[0].title).toBe("研究员");
  });

  it("reuses one tab for a revision chain and switches runId in place", () => {
    exec().startExecution(plan, MID);
    exec().recordFrames(
      [
        {
          t: 1,
          kind: "run_started",
          agentId: "agent-1",
          runId: "run-1",
          parentRunId: null,
          runKind: "agent",
          continuesRunId: null,
        },
        {
          t: 2,
          kind: "run_completed",
          runId: "run-1",
          agentId: "agent-1",
          outputSummary: "done",
          durationMs: 1,
        },
        {
          t: 3,
          kind: "run_started",
          agentId: "run-1_rev1",
          runId: "run-1_rev1",
          parentRunId: null,
          runKind: "agent",
          continuesRunId: "run-1",
        },
        {
          t: 4,
          kind: "run_started",
          agentId: "run-1_rev2",
          runId: "run-1_rev2",
          parentRunId: null,
          runKind: "agent",
          continuesRunId: "run-1",
        },
      ],
      MID,
    );

    panel().showRunDetail(MID, "run-1", "研究员");
    panel().showRunDetail(MID, "run-1_rev1", "研究员");
    panel().showRunDetail(MID, "run-1_rev2", "研究员");

    expect(panel().tabs).toHaveLength(1);
    expect(panel().tabs[0].id).toBe(tabId("run-1"));
    expect(panel().activeTabId).toBe(tabId("run-1"));
    const tab = panel().tabs[0];
    expect(tab.kind).toBe("run");
    if (tab.kind === "run") {
      expect(tab.runId).toBe("run-1_rev2");
    }
  });

  it("keeps separate tabs for unrelated (non-revision) runs", () => {
    const multi: ExecutionPlan = {
      ...plan,
      agents: [...plan.agents, { id: "agent-2", role: "评论员" }],
      runs: [
        ...plan.runs,
        { id: "run-2", agentId: "agent-2", task: "评论", dependsOn: [] },
      ],
    };
    exec().startExecution(multi, MID);
    panel().showRunDetail(MID, "run-1", "研究员");
    panel().showRunDetail(MID, "run-2", "评论员");
    expect(panel().tabs.map((t) => t.id)).toEqual([
      tabId("run-1"),
      tabId("run-2"),
    ]);
  });
});

describe("showContentDetail", () => {
  it("pins an endpoint bubble as a content tab, reveals + activates it", () => {
    panel().showContentDetail(MID, "answer-msg", "最终回答", "answer");
    const id = contentDetailTabId(MID, "answer-msg");
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(id);
    const tab = panel().tabs[0];
    expect(tab.kind).toBe("content");
    expect(tab.title).toBe("最终回答");
    // The content tab carries the bubble to render + which endpoint it is (drives
    // the tab icon), not a runId.
    if (tab.kind === "content") {
      expect(tab.contentMessageId).toBe("answer-msg");
      expect(tab.endpoint).toBe("answer");
    }
  });

  it("coexists with run tabs and dedups by its own id", () => {
    panel().showRunDetail(MID, "run-1", "研究员");
    panel().showContentDetail(MID, "answer-msg", "最终回答", "answer");
    panel().showContentDetail(MID, "answer-msg", "最终回答", "answer");
    // One run tab + one content tab; the re-open dedups rather than appends.
    expect(panel().tabs).toHaveLength(2);
    expect(panel().tabs.map((t) => t.kind)).toEqual(["run", "content"]);
  });
});

describe("showSimpleTurnDetail", () => {
  it("pins a simple-turn Q&A tab, reveals + activates it", () => {
    panel().showSimpleTurnDetail(MID, "user-1", "asst-1", "直接回答");
    const id = simpleTurnDetailTabId(MID);
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(id);
    const tab = panel().tabs[0];
    expect(tab.kind).toBe("simple-turn");
    expect(tab.title).toBe("直接回答");
    if (tab.kind === "simple-turn") {
      expect(tab.promptMessageId).toBe("user-1");
      expect(tab.answerMessageId).toBe("asst-1");
    }
  });

  it("defaults the title to 对话 and dedups by turn id", () => {
    panel().showSimpleTurnDetail(MID, "user-1", "asst-1");
    panel().showSimpleTurnDetail(MID, "user-1", "asst-1", "更新标题");
    expect(panel().tabs).toHaveLength(1);
    expect(panel().tabs[0].title).toBe("更新标题");
    expect(panel().tabs[0].id).toBe(simpleTurnDetailTabId(MID));
  });

  it("coexists with run tabs", () => {
    panel().showRunDetail(MID, "run-1", "研究员");
    panel().showSimpleTurnDetail(MID, "user-1", "asst-1");
    expect(panel().tabs.map((t) => t.kind)).toEqual(["run", "simple-turn"]);
  });
});

describe("closeContentTabs", () => {
  it("drops content tabs but keeps run tabs, re-activating a survivor", () => {
    panel().showRunDetail(MID, "run-1", "研究员");
    panel().showContentDetail(MID, "answer-msg", "最终回答", "answer");
    // The content tab is active; closing content tabs falls back to the run tab.
    panel().closeContentTabs();
    expect(panel().tabs.map((t) => t.kind)).toEqual(["run"]);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });

  it("also drops simple-turn Q&A tabs (same reading-context cleanup)", () => {
    panel().showRunDetail(MID, "run-1", "研究员");
    panel().showSimpleTurnDetail(MID, "user-1", "asst-1");
    panel().closeContentTabs();
    expect(panel().tabs.map((t) => t.kind)).toEqual(["run"]);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });

  it("falls back to the 工作区 home when no detail tab survives", () => {
    panel().showContentDetail(MID, "answer-msg", "最终回答", "answer");
    panel().closeContentTabs();
    expect(panel().tabs).toHaveLength(0);
    expect(panel().activeTabId).toBe(WORKSPACE_TAB_ID);
  });

  it("is a no-op when there are no content tabs", () => {
    panel().showRunDetail(MID, "run-1", "研究员");
    panel().closeContentTabs();
    expect(panel().tabs.map((t) => t.id)).toEqual([tabId("run-1")]);
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });
});

describe("openPreview / closePreview（内置浏览器预览 tab）", () => {
  it("opens the preview tab, reveals the panel and activates it", () => {
    panel().openPreview("c1", "site/index.html", "index.html");
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(PREVIEW_TAB_ID);
    expect(panel().previewTab).toEqual({
      conversationId: "c1",
      path: "site/index.html",
      name: "index.html",
    });
  });

  it("reuses the single preview tab when opening another file (swaps target)", () => {
    panel().openPreview("c1", "a.html", "a.html");
    panel().openPreview("c1", "b/c.html", "c.html");
    expect(panel().previewTab).toEqual({
      conversationId: "c1",
      path: "b/c.html",
      name: "c.html",
    });
    expect(panel().activeTabId).toBe(PREVIEW_TAB_ID);
  });

  it("closePreview clears the target and falls back to 工作区 when it was active", () => {
    panel().openPreview("c1", "a.html", "a.html");
    panel().closePreview();
    expect(panel().previewTab).toBeNull();
    expect(panel().activeTabId).toBe(WORKSPACE_TAB_ID);
  });

  it("closePreview keeps the active tab when preview wasn't the active one", () => {
    panel().openPreview("c1", "a.html", "a.html");
    // Switch away to a run tab, then close the (background) preview tab.
    panel().showRunDetail(MID, "run-1", "研究员");
    expect(panel().activeTabId).toBe(tabId("run-1"));
    panel().closePreview();
    expect(panel().previewTab).toBeNull();
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });
});

describe("showBrowser（团队浏览器 tab · 条件常驻）", () => {
  it("reveals the panel and activates the browser tab", () => {
    panel().showBrowser();
    expect(panel().open).toBe(true);
    expect(panel().activeTabId).toBe(BROWSER_TAB_ID);
  });

  it("carries no per-tab target state (存在性派生自会话内容，非 store 字段)", () => {
    panel().showBrowser();
    // tab 是否显示由 useBrowserRegion 从 execution 投影派生；store 只记「谁是激活 tab」。
    expect(Object.keys(panel())).not.toContain("browserLiveTab");
  });

  it("is idempotent — re-revealing keeps the same active tab", () => {
    panel().showBrowser();
    panel().showBrowser();
    expect(panel().activeTabId).toBe(BROWSER_TAB_ID);
  });

  it("leaves the browser tab in the background when a run tab is drilled after it", () => {
    panel().showBrowser();
    panel().showRunDetail(MID, "run-1", "研究员");
    expect(panel().activeTabId).toBe(tabId("run-1"));
  });

  it("clears pendingBadge on reveal (matches other reveal paths)", () => {
    panel().incrementPendingBadge();
    panel().showBrowser();
    expect(panel().pendingBadge).toBe(0);
  });
});

describe("auto-surface dismiss + pending badge", () => {
  it("records command context on closePanel when canvas command tab is active", () => {
    useConversationStore.setState({ currentConversationId: "conv-1" });
    useCommandPanelStore.setState({ active: true, focusedMessageId: MID });
    panel().openPanel();
    panel().closePanel();
    expect(panel().isAutoSurfaceDismissed("command:conv-1")).toBe(true);
  });

  it("clearAutoSurfaceDismiss removes a context", () => {
    panel().dismissAutoSurface("debate:msg-1");
    expect(panel().isAutoSurfaceDismissed("debate:msg-1")).toBe(true);
    panel().clearAutoSurfaceDismiss("debate:msg-1");
    expect(panel().isAutoSurfaceDismissed("debate:msg-1")).toBe(false);
  });

  it("incrementPendingBadge accumulates while panel stays closed", () => {
    panel().incrementPendingBadge();
    panel().incrementPendingBadge();
    expect(panel().pendingBadge).toBe(2);
  });

  it("clears pendingBadge when opening via showWorkspace / openPanel", () => {
    panel().incrementPendingBadge();
    panel().showWorkspace();
    expect(panel().pendingBadge).toBe(0);

    panel().incrementPendingBadge();
    panel().openPanel();
    expect(panel().pendingBadge).toBe(0);
  });

  it("clears pendingBadge when togglePanel opens the dock", () => {
    panel().incrementPendingBadge();
    panel().togglePanel();
    expect(panel().open).toBe(true);
    expect(panel().pendingBadge).toBe(0);
  });

  it("keeps pendingBadge when togglePanel closes the dock", () => {
    panel().showWorkspace();
    panel().incrementPendingBadge();
    panel().togglePanel();
    expect(panel().open).toBe(false);
    expect(panel().pendingBadge).toBe(1);
  });
});
