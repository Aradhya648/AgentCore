// @vitest-environment jsdom
import { InterjectionTimeline } from "@/components/chat/InterjectionTimeline";
import { useExecutionStore } from "@/stores/execution";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  useExecutionStore.setState({ byId: {} });
});

describe("InterjectionTimeline", () => {
  it("renders user-style bubbles with S2 status copy", () => {
    useExecutionStore.setState({
      byId: {
        m1: {
          userInterjections: [
            {
              interjectionId: "ij1",
              executionId: "e1",
              content: "补充成本对比",
              status: "received",
              note: null,
            },
            {
              interjectionId: "ij2",
              executionId: "e1",
              content: "无关贺卡",
              status: "queued",
              note: null,
            },
          ],
        },
      },
    } as never);

    render(<InterjectionTimeline messageId="m1" />);
    expect(screen.getByTestId("interjection-timeline")).toBeTruthy();
    expect(screen.getByText("补充成本对比")).toBeTruthy();
    expect(screen.getByText("主 Agent 已收到")).toBeTruthy();
    expect(screen.getByText("将在下一条回复处理")).toBeTruthy();
    expect(screen.queryByText("已传达给团队")).toBeNull();
  });

  it("renders nothing when empty", () => {
    const { container } = render(<InterjectionTimeline messageId="missing" />);
    expect(container.firstChild).toBeNull();
  });
});
