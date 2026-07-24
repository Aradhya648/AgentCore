// @vitest-environment jsdom
import {
  dossierSourceLabel,
  formatActChain,
} from "@/services/collaborationTimeline";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { CollaborationTimelinePanel } from "../CollaborationTimeline";

vi.mock("@/services/collaborationTimeline", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/collaborationTimeline")>();
  return {
    ...actual,
    fetchCollaborationTimeline: vi.fn(async () => ({
      folder_id: "folder-1",
      total: 1,
      limit: 20,
      offset: 0,
      dossier_refs_note:
        "路径级案卷消费事实（本场辩论开赛注入或会话内 file_read），非跨会话过程边",
      items: [
        {
          conversation_id: "c1",
          title: "LV 商标案",
          updated_at: "2026-07-19T10:00:00Z",
          execution_id: "e1",
          host_turn_id: "t1",
          acts: [
            {
              act_id: "act-1",
              kind: "multi_agent" as const,
              title: "多视角调研",
            },
            {
              act_id: "act-2",
              kind: "debate" as const,
              title: "辩论对抗",
            },
          ],
          dossier_refs: [
            {
              path: "research/法律透镜报告.md",
              sources: ["dossier_inject", "file_read"] as (
                | "dossier_inject"
                | "file_read"
              )[],
            },
          ],
        },
      ],
    })),
  };
});

vi.mock("@/services/workspaces", () => ({
  wsListFiles: vi.fn(async () => [
    { path: "research/法律透镜报告.md", isDir: false },
    { path: "debate/brief.md", isDir: false },
  ]),
}));

describe("formatActChain / dossierSourceLabel", () => {
  it("joins act titles with arrow", () => {
    expect(
      formatActChain([
        { act_id: "act-1", kind: "multi_agent", title: "多视角调研" },
        { act_id: "act-2", kind: "debate", title: "辩论对抗" },
      ]),
    ).toBe("多视角调研 → 辩论对抗");
  });

  it("labels dossier sources honestly", () => {
    expect(dossierSourceLabel(["dossier_inject"])).toBe("开赛注入");
    expect(dossierSourceLabel(["file_read"])).toBe("会话内读取");
    expect(dossierSourceLabel(["dossier_inject", "file_read"])).toBe(
      "开赛注入 · 已读",
    );
  });
});

describe("CollaborationTimelinePanel", () => {
  it("renders session title, act chain, dossier snapshot and refs note", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <CollaborationTimelinePanel folderId="folder-1" />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("LV 商标案")).toBeTruthy();
    expect(screen.getByText("多视角调研 → 辩论对抗")).toBeTruthy();
    expect(screen.getByText("阶段产物")).toBeTruthy();
    // Appears both on the dossier_refs chip and the research/ snapshot list.
    expect(
      screen.getAllByText("法律透镜报告.md").length,
    ).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/路径级案卷消费事实/)).toBeTruthy();
    expect(screen.getByText("开赛注入 · 已读")).toBeTruthy();
  });
});
