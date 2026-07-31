import {
  fileArtifactsFromDeliveryStatus,
  resolveFileArtifactsForCard,
} from "@/lib/fileArtifacts";
import type { DeliveryStatusPayload } from "@agentcore/contract-types";
import { describe, expect, it } from "vitest";

describe("fileArtifacts from delivery_status.artifacts", () => {
  it("maps accepted+rejected", () => {
    const status = {
      execution_id: "e1",
      state: "partial",
      summary: "x",
      delivered_files: ["ok.md"],
      gaps: [],
      actions: [],
      artifacts: [
        { path: "ok.md", status: "accepted" },
        {
          path: "bad.md",
          status: "rejected",
          reason: "citations_unverified",
          detail: "缺 #rN",
        },
      ],
    } as DeliveryStatusPayload;
    const fromDelivery = fileArtifactsFromDeliveryStatus(status);
    expect(fromDelivery).not.toBeNull();
    if (fromDelivery == null) return;
    expect(fromDelivery).toEqual([
      { path: "ok.md", name: "ok.md", acceptance: "accepted" },
      {
        path: "bad.md",
        name: "bad.md",
        acceptance: "rejected",
        acceptanceReason: "citations_unverified",
        acceptanceDetail: "缺 #rN",
      },
    ]);
    expect(resolveFileArtifactsForCard(status).map((a) => a.path)).toEqual([
      "ok.md",
      "bad.md",
    ]);
  });

  it("missing artifacts field yields empty card list (no tool fallback)", () => {
    const status = {
      execution_id: "e1",
      state: "delivered",
      summary: "x",
      delivered_files: ["a.md"],
      gaps: [],
      actions: [],
    } as DeliveryStatusPayload;
    expect(fileArtifactsFromDeliveryStatus(status)).toBeNull();
    expect(resolveFileArtifactsForCard(status)).toEqual([]);
  });

  it("empty artifacts array yields empty list", () => {
    const status = {
      execution_id: "e1",
      state: "blocked",
      summary: "x",
      delivered_files: [],
      gaps: [],
      actions: [],
      artifacts: [],
    } as DeliveryStatusPayload;
    expect(fileArtifactsFromDeliveryStatus(status)).toEqual([]);
    expect(resolveFileArtifactsForCard(status)).toEqual([]);
  });
});
