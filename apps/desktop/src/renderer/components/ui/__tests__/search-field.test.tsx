// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SearchField } from "../search-field";

describe("SearchField", () => {
  it("clears on Escape when escapeClears is true", () => {
    const onValueChange = vi.fn();
    render(
      <SearchField
        value="hello"
        onValueChange={onValueChange}
        aria-label="筛选"
      />,
    );
    const input = screen.getByLabelText("筛选");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onValueChange).toHaveBeenCalledWith("");
  });

  it("shows clear button for field variant when non-empty", () => {
    const onValueChange = vi.fn();
    render(
      <SearchField value="x" onValueChange={onValueChange} aria-label="筛选" />,
    );
    fireEvent.click(screen.getByLabelText("清除筛选"));
    expect(onValueChange).toHaveBeenCalledWith("");
  });
});
