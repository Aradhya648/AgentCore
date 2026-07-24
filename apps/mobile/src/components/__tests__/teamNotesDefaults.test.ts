import { teamNotesDefaultExpanded } from "@/components/TeamView";
import type { ProjectedTeamNote } from "@agentcore/protocol-conformance";
import { describe, expect, it } from "vitest";

function note(
  status: ProjectedTeamNote["status"] = "active",
  overrides: Partial<ProjectedTeamNote> = {},
): ProjectedTeamNote {
  return {
    noteId: "n1",
    runId: "r1",
    agentId: "a1",
    role: "撰写员",
    kind: "decision",
    text: "用 camelCase",
    ts: 1,
    status,
    supersedes: null,
    ...overrides,
  };
}

describe("teamNotesDefaultExpanded", () => {
  it("returns false when there are no notes", () => {
    expect(teamNotesDefaultExpanded("running", [])).toBe(false);
  });

  it("expands while running with an active note", () => {
    expect(teamNotesDefaultExpanded("running", [note("active")])).toBe(true);
  });

  it("stays collapsed while running if every note is stale", () => {
    expect(
      teamNotesDefaultExpanded("running", [
        note("superseded", { noteId: "n1" }),
        note("voided", { noteId: "n2" }),
      ]),
    ).toBe(false);
  });

  it("stays collapsed for completed / stopped turns even with active notes", () => {
    expect(teamNotesDefaultExpanded("completed", [note("active")])).toBe(false);
    expect(teamNotesDefaultExpanded("failed", [note("active")])).toBe(false);
    expect(teamNotesDefaultExpanded("cancelled", [note("active")])).toBe(false);
    expect(teamNotesDefaultExpanded("paused", [note("active")])).toBe(false);
  });

  it("stays collapsed when status is missing", () => {
    expect(teamNotesDefaultExpanded(undefined, [note("active")])).toBe(false);
    expect(teamNotesDefaultExpanded(null, [note("active")])).toBe(false);
  });
});
