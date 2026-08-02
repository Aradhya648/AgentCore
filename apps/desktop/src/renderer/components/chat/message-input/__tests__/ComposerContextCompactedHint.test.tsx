import { COMPOSER_CONTEXT_COMPACTED_HINT } from "@/lib/composerContextCompactedHint";
// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ComposerContextCompactedHint } from "../ComposerContextCompactedHint";

afterEach(cleanup);

describe("ComposerContextCompactedHint", () => {
  it("renders nothing when hidden", () => {
    const { container } = render(<ComposerContextCompactedHint show={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the short zh compacted tip when visible", () => {
    render(<ComposerContextCompactedHint show />);
    expect(
      screen.getByTestId("composer-context-compacted-hint").textContent,
    ).toBe(COMPOSER_CONTEXT_COMPACTED_HINT);
  });
});
