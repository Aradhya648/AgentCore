// @vitest-environment jsdom
import { useConversationStore } from "@/stores/conversation";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { GraphAppendAnchor } from "../GraphAppendAnchor";

const CID = "c-gappend-anchor";

describe("GraphAppendAnchor", () => {
  beforeEach(() => {
    useConversationStore.setState({ currentConversationId: null, byId: {} });
    const store = useConversationStore.getState();
    store.switchConversation(CID);
    store.addMessage({
      id: "client-m1",
      serverMessageId: "m1",
      role: "assistant",
      content: "host",
      createdAt: new Date().toISOString(),
      executionId: "exec1",
      isStreaming: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("renders cumulative append copy and focuses the host bubble", () => {
    render(<GraphAppendAnchor hostMessageId="m1" addedCount={2} />);
    expect(screen.getByTestId("graph-append-anchor").textContent).toContain(
      "↑ 已往上方协作图追加 2 名成员",
    );
    fireEvent.click(screen.getByTestId("graph-append-anchor"));
    expect(useConversationStore.getState().byId[CID].messageFocus?.id).toBe(
      "client-m1",
    );
  });

  it("uses debate-act copy when opening a debate act", () => {
    render(
      <GraphAppendAnchor hostMessageId="m1" addedCount={1} actKind="debate" />,
    );
    expect(screen.getByTestId("graph-append-anchor").textContent).toContain(
      "↑ 开辩论幕·1 人进场",
    );
  });

  it("appends authorizedBy subtitle for stage_card / auto / preview", () => {
    render(
      <GraphAppendAnchor
        hostMessageId="m1"
        addedCount={1}
        actKind="debate"
        authorizedBy="stage_card"
      />,
    );
    expect(screen.getByTestId("graph-append-anchor").textContent).toContain(
      "经推进卡授权",
    );
  });
});
