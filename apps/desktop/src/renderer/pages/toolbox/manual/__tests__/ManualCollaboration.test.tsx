// @vitest-environment jsdom
import { ManualCollaboration } from "@/pages/toolbox/manual/ManualCollaboration";
import { collaborationChapter } from "@/pages/toolbox/manual/content/collaboration";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

const SECTION_IDS = [
  "briefing",
  "progress",
  "checkpoint",
  "autonomy",
  "debate",
  "control",
  "memory",
] as const;

describe("ManualCollaboration", () => {
  it("renders content-driven sections with stable deep-link ids", () => {
    render(
      <MemoryRouter initialEntries={["/toolbox/manual/collaboration"]}>
        <ManualCollaboration />
      </MemoryRouter>,
    );

    for (const id of SECTION_IDS) {
      expect(document.getElementById(id)).toBeTruthy();
    }
    expect(document.getElementById("debate")?.textContent).toMatch(/辩论室/);
    expect(document.getElementById("autonomy")?.textContent).toMatch(/自主度/);
    expect(document.getElementById("control")?.textContent).toMatch(/中途插手/);
    expect(document.getElementById("checkpoint")?.textContent).toMatch(
      /检查点与审批/,
    );
    expect(document.getElementById("collab-overview")).toBeNull();
    expect(document.getElementById("roles")).toBeNull();
    expect(document.getElementById("continuation")).toBeNull();

    expect(screen.queryByText(/后续规划/)).toBeNull();
    expect(screen.getByText(/角色由 CEO 临时分配/)).toBeTruthy();
    expect(screen.getAllByText(/带现场续派/).length).toBeGreaterThan(0);
    expect(screen.getByText("少打断（推荐）")).toBeTruthy();
    expect(screen.getByText(/设为新会话默认/)).toBeTruthy();
    expect(screen.getByText("中途插手")).toBeTruthy();
    expect(screen.getByText("记忆与偏好")).toBeTruthy();
    expect(screen.queryByText("设置 · 权限配方")).toBeNull();
    expect(screen.queryByText(/ask_user/)).toBeNull();
    expect(screen.queryByText(/plan_review/)).toBeNull();
    expect(screen.queryByText(/run_redirect/)).toBeNull();
  });

  it("preserves section order and stays text-only (embeds belong to mechanism)", () => {
    expect(collaborationChapter.sections.map((s) => s.id)).toEqual([
      ...SECTION_IDS,
    ]);

    const embedKeys = collaborationChapter.sections.flatMap((s) =>
      s.blocks.filter((b) => b.type === "embed").map((b) => b.key),
    );
    expect(embedKeys).toEqual([]);
  });
});
