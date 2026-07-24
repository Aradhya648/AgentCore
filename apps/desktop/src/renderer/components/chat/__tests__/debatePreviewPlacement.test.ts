import {
  shouldHostPreviewInGraph,
  teamHasStartedRuns,
} from "@/components/chat/debatePreviewPlacement";
import { describe, expect, it } from "vitest";

describe("shouldHostPreviewInGraph", () => {
  const debateResolved = {
    status: "resolved" as const,
  };
  const delegateResolved = {
    status: "resolved" as const,
  };
  const started = [{ status: "running" }];
  const dormant = [{ status: "pending" }, { status: "skipped" }];

  it("debate resolved + team started → host in graph", () => {
    expect(shouldHostPreviewInGraph(debateResolved, started)).toBe(true);
  });

  it("delegate resolved + team started → host in graph", () => {
    expect(shouldHostPreviewInGraph(delegateResolved, started)).toBe(true);
  });

  it("resolved + team not started → keep standalone card", () => {
    expect(shouldHostPreviewInGraph(debateResolved, dormant)).toBe(false);
    expect(shouldHostPreviewInGraph(delegateResolved, dormant)).toBe(false);
  });

  it("pending → never host (standalone DormantTeamPreview)", () => {
    expect(shouldHostPreviewInGraph({ status: "pending" }, started)).toBe(
      false,
    );
  });

  it("missing preview or runs → false", () => {
    expect(shouldHostPreviewInGraph(null, started)).toBe(false);
    expect(shouldHostPreviewInGraph(debateResolved, null)).toBe(false);
    expect(shouldHostPreviewInGraph(undefined, undefined)).toBe(false);
  });

  it("shares teamHasStartedRuns gate with InlineTeamGraph", () => {
    expect(teamHasStartedRuns(started)).toBe(true);
    expect(teamHasStartedRuns(dormant)).toBe(false);
    expect(shouldHostPreviewInGraph(debateResolved, started)).toBe(
      teamHasStartedRuns(started),
    );
    expect(shouldHostPreviewInGraph(debateResolved, dormant)).toBe(
      teamHasStartedRuns(dormant),
    );
  });
});
