// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { BrandMark } from "../BrandMark";

afterEach(cleanup);

describe("BrandMark", () => {
  it("renders AgentCore wordmark with display font class", () => {
    render(<BrandMark />);
    const word = screen.getByText("AgentCore");
    expect(word.className).toMatch(/\bfont-brand\b/);
  });

  it("can hide wordmark and keep the mark", () => {
    const { container } = render(<BrandMark showWordmark={false} />);
    expect(
      screen.queryByText("AgentCore", { selector: "span.font-brand" }),
    ).toBeNull();
    expect(screen.getByRole("img", { name: "AgentCore" })).toBeTruthy();
    expect(container.querySelector("svg")).toBeTruthy();
  });
});
