// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UserInterjectionsPanel } from "../UserInterjectionsPanel";

describe("UserInterjectionsPanel", () => {
  it("renders received vs queued badges (legacy delivered still OK)", () => {
    render(
      <UserInterjectionsPanel
        items={[
          {
            interjectionId: "a",
            executionId: "e1",
            content: "补充成本对比",
            status: "received",
            note: null,
          },
          {
            interjectionId: "b",
            executionId: "e1",
            content: "另写贺卡",
            status: "queued",
            note: "与当前任务无关",
          },
        ]}
      />,
    );
    expect(screen.getByText("主 Agent 已收到")).toBeTruthy();
    expect(screen.getByText("将在下一条回复处理")).toBeTruthy();
    expect(screen.getByText("补充成本对比")).toBeTruthy();
    expect(screen.getByText("与当前任务无关")).toBeTruthy();
    expect(screen.queryByText("已传达给团队")).toBeNull();
  });

  it("failed badge is not success-green copy", () => {
    render(
      <UserInterjectionsPanel
        items={[
          {
            interjectionId: "f",
            executionId: "e1",
            content: "排队失败的插话",
            status: "failed",
            note: null,
          },
        ]}
      />,
    );
    expect(screen.getByText("未能排队，请重试或再说一次")).toBeTruthy();
    expect(screen.queryByText("已传达给团队")).toBeNull();
    expect(screen.queryByText("主 Agent 已收到")).toBeNull();
  });

  it("addressed uses read-sense copy, not fake success", () => {
    render(
      <UserInterjectionsPanel
        items={[
          {
            interjectionId: "x",
            executionId: "e1",
            content: "已承接的补充",
            status: "addressed",
            note: "已在合成草稿中承接",
          },
        ]}
      />,
    );
    expect(screen.getByText("主 Agent 已回应")).toBeTruthy();
    expect(screen.queryByText("已传达给团队")).toBeNull();
  });

  it("renders attachment name chips", () => {
    render(
      <UserInterjectionsPanel
        items={[
          {
            interjectionId: "a",
            executionId: "e1",
            content: "对照附件",
            status: "delivered",
            note: null,
            attachments: [
              {
                name: "成本表.xlsx",
                workspacePath: "attachments/成本表.xlsx",
                binary: true,
              },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByText("成本表.xlsx")).toBeTruthy();
    expect(screen.getByText("主 Agent 已收到")).toBeTruthy();
  });

  it("renders nothing when empty", () => {
    const { container } = render(<UserInterjectionsPanel items={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
