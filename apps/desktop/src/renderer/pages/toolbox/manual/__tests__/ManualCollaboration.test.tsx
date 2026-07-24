// @vitest-environment jsdom
import { ManualCollaboration } from "@/pages/toolbox/manual/ManualCollaboration";
import { collaborationChapter } from "@/pages/toolbox/manual/content/collaboration";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

const SECTION_IDS = [
  "collab-overview",
  "briefing",
  "roles",
  "debate",
  "progress",
  "checkpoint",
  "autonomy",
  "control",
  "continuation",
  "memory",
] as const;

describe("ManualCollaboration", () => {
  it("renders content-driven sections with stable deep-link ids", () => {
    render(
      <MemoryRouter initialEntries={["/toolbox/manual/collaboration"]}>
        <ManualCollaboration />
      </MemoryRouter>,
    );

    // 功能页 ? 入口深链 id 不可变；全节锚点齐全
    for (const id of SECTION_IDS) {
      expect(document.getElementById(id)).toBeTruthy();
    }
    expect(document.getElementById("debate")?.textContent).toMatch(/辩论室/);
    expect(document.getElementById("autonomy")?.textContent).toMatch(/自主度/);
    expect(document.getElementById("continuation")?.textContent).toMatch(
      /带现场续派/,
    );
    expect(document.getElementById("checkpoint")?.textContent).toMatch(
      /检查点与审批/,
    );

    // 旧「后续规划」占位已删；术语用「队员」
    expect(screen.queryByText(/后续规划/)).toBeNull();
    expect(screen.getByText(/临时给队员配角色/)).toBeTruthy();
    expect(screen.getAllByText(/带现场续派/).length).toBeGreaterThan(0);
    expect(screen.getByText("每次询问")).toBeTruthy();
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
