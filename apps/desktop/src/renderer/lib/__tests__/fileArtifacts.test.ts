import {
  type FileArtifact,
  fileArtifactsFromDeliveryStatus,
  fileArtifactsFromProcess,
  hasChangePreviews,
  mergeArtifacts,
  resolveFileArtifactsForCard,
} from "@/lib/fileArtifacts";
import type { DeliveryStatusPayload, ProcessStep } from "@/types/events";
import { describe, expect, it } from "vitest";

function toolStep(
  tool_name: string,
  args: Record<string, unknown>,
  status: "success" | "error" = "success",
): ProcessStep {
  return {
    kind: "tool",
    id: `t-${tool_name}`,
    tool_name,
    arguments: args,
    result: null,
    status,
  };
}

describe("fileArtifacts change previews (A1)", () => {
  it("str_replace carries edit preview", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("str_replace", {
        path: "src/a.ts",
        old_string: "const x = 1",
        new_string: "const x = 2",
      }),
    ]);
    expect(arts).toHaveLength(1);
    expect(arts[0].change).toEqual({
      kind: "edit",
      oldText: "const x = 1",
      newText: "const x = 2",
    });
    expect(hasChangePreviews(arts)).toBe(true);
  });

  it("file_write / file_append carry write preview", () => {
    const write = fileArtifactsFromProcess([
      toolStep("file_write", { path: "a.md", content: "hello" }),
    ]);
    expect(write[0].change).toEqual({
      kind: "write",
      content: "hello",
      mode: "overwrite",
    });
    const append = fileArtifactsFromProcess([
      toolStep("file_append", { path: "a.md", content: "\nmore" }),
    ]);
    expect(append[0].change).toEqual({
      kind: "write",
      content: "\nmore",
      mode: "append",
    });
  });

  it("file_delete / file_move carry meta preview", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("file_delete", { path: "gone.ts" }),
      toolStep("file_move", {
        source: "old.ts",
        destination: "new.ts",
      }),
    ]);
    expect(arts.find((a) => a.path === "gone.ts")?.change).toEqual({
      kind: "delete",
    });
    expect(arts.find((a) => a.path === "new.ts")?.change).toEqual({
      kind: "move",
      fromPath: "old.ts",
    });
  });

  it("mergeArtifacts keeps last op per path", () => {
    expect(
      fileArtifactsFromProcess([
        toolStep("file_write", { path: "a.ts", content: "1" }),
        toolStep("str_replace", {
          path: "a.ts",
          old_string: "1",
          new_string: "2",
        }),
      ]).map((a) => a.op),
    ).toEqual(["edit"]);
  });

  it("hasChangePreviews is false when no change", () => {
    const bare: FileArtifact[] = [{ path: "x.ts", name: "x.ts", op: "write" }];
    expect(hasChangePreviews(bare)).toBe(false);
  });

  it("failed tool steps are skipped", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("file_write", { path: "a.md", content: "x" }, "error"),
    ]);
    expect(arts).toHaveLength(0);
  });

  it("unknown tools skipped", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("web_search", { query: "x" }),
    ]);
    expect(arts).toHaveLength(0);
  });

  it("mergeArtifacts flattens sources", () => {
    const arts = mergeArtifacts(
      fileArtifactsFromProcess([
        toolStep("file_write", { path: "a.md", content: "a" }),
      ]),
      fileArtifactsFromProcess([
        toolStep("file_write", { path: "b.md", content: "b" }),
      ]),
    );
    expect(arts.map((a) => a.path).sort()).toEqual(["a.md", "b.md"]);
  });
});

describe("fileArtifacts from delivery_status.artifacts", () => {
  it("maps accepted+rejected and ignores tool lists", () => {
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
