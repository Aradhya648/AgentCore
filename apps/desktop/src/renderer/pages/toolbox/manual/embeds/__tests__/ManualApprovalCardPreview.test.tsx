// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { ManualApprovalCardPreview } from "../ManualApprovalCardPreview";

afterEach(cleanup);

describe("ManualApprovalCardPreview", () => {
  it("renders without crashing", () => {
    render(
      <MemoryRouter>
        <ManualApprovalCardPreview />
      </MemoryRouter>,
    );
    expect(screen.getByText("Agent 请求执行")).toBeTruthy();
    expect(screen.getByText("写入文件")).toBeTruthy();
    expect(screen.getByText("允许一次")).toBeTruthy();
    expect(screen.getByText("拒绝")).toBeTruthy();
  });
});
