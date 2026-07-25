// @vitest-environment jsdom
import { formatActChain } from "@/api/collaborationTimeline";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { CollaborationSummaryList } from "../CollaborationSummaryList";

vi.mock("@/api/collaborationTimeline", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/api/collaborationTimeline")>();
  return {
    ...actual,
    fetchCollaborationTimeline: vi.fn(async () => ({
      folder_id: "f1",
      total: 1,
      limit: 20,
      offset: 0,
      dossier_refs_note: "路径级案卷消费事实",
      items: [
        {
          conversation_id: "c1",
          title: "LV 案",
          updated_at: "2026-07-19T10:00:00Z",
          execution_id: "e1",
          host_turn_id: "t1",
          acts: [
            {
              act_id: "act-1",
              kind: "multi_agent" as const,
              title: "多视角调研",
            },
            { act_id: "act-2", kind: "debate" as const, title: "辩论对抗" },
          ],
          dossier_refs: [
            {
              path: "AgentCore/文档/research/法律透镜报告.md",
              sources: ["file_read"] as ("dossier_inject" | "file_read")[],
            },
          ],
        },
      ],
    })),
  };
});

describe("formatActChain", () => {
  it("joins titles", () => {
    expect(
      formatActChain([
        { act_id: "act-1", kind: "multi_agent", title: "多视角调研" },
        { act_id: "act-2", kind: "debate", title: "辩论对抗" },
      ]),
    ).toBe("多视角调研 → 辩论对抗");
  });
});

describe("CollaborationSummaryList", () => {
  it("renders text summary for folder workspace", async () => {
    render(
      <MemoryRouter>
        <CollaborationSummaryList wsId="folder:f1" />
      </MemoryRouter>,
    );
    expect(await screen.findByText("LV 案")).toBeTruthy();
    expect(screen.getByText("多视角调研 → 辩论对抗")).toBeTruthy();
    expect(screen.getByText(/读过案卷：法律透镜报告/)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText(/路径级案卷消费事实/)).toBeTruthy();
    });
  });

  it("hides for non-folder ws ids", () => {
    const { container } = render(
      <MemoryRouter>
        <CollaborationSummaryList wsId="conv:abc" />
      </MemoryRouter>,
    );
    expect(
      container.querySelector("[data-testid=collaboration-summary-list]"),
    ).toBeNull();
  });
});
