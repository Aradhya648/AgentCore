// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { COMPOSER_PENDING_HINT } from "@/lib/composerPendingHint";
import { ComposerPendingHintNotice } from "../ComposerPendingHintNotice";

afterEach(cleanup);

describe("ComposerPendingHintNotice", () => {
  it("renders nothing when hidden", () => {
    const { container } = render(<ComposerPendingHintNotice show={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the short zh pending hint when visible", () => {
    render(<ComposerPendingHintNotice show />);
    expect(screen.getByTestId("composer-pending-hint").textContent).toBe(
      COMPOSER_PENDING_HINT,
    );
  });
});
