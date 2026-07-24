// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UserInterjectionsPanel } from "../UserInterjectionsPanel";

describe("UserInterjectionsPanel", () => {
  it("renders delivered vs queued badges", () => {
    render(
      <UserInterjectionsPanel
        items={[
          {
            interjectionId: "a",
            executionId: "e1",
            content: "补充成本对比",
            status: "delivered",
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
    expect(screen.getByText("已传达给团队")).toBeTruthy();
    expect(screen.getByText("已排队")).toBeTruthy();
    expect(screen.getByText("补充成本对比")).toBeTruthy();
    expect(screen.getByText("与当前任务无关")).toBeTruthy();
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
  });

  it("renders nothing when empty", () => {
    const { container } = render(<UserInterjectionsPanel items={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
