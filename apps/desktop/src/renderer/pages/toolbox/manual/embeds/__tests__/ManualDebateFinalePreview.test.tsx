// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ManualDebateFinalePreview } from "../ManualDebateFinalePreview";

afterEach(cleanup);

describe("ManualDebateFinalePreview", () => {
  it("renders without crashing", () => {
    render(<ManualDebateFinalePreview />);
    expect(screen.getByText("主持人终审")).toBeTruthy();
    expect(screen.getByText("倾向加速派")).toBeTruthy();
    expect(screen.getByText(/建议：/)).toBeTruthy();
  });
});
