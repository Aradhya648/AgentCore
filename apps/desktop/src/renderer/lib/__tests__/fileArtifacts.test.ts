import {
  type FileArtifact,
  fileArtifactsFromProcess,
  hasChangePreviews,
  mergeArtifacts,
} from "@/lib/fileArtifacts";
import type { ProcessStep } from "@/types/events";
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

  it("delete / move carry meta previews", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("file_delete", { path: "gone.ts" }),
      toolStep("file_move", { source: "a.ts", destination: "b.ts" }),
    ]);
    const byPath = Object.fromEntries(arts.map((a) => [a.path, a]));
    expect(byPath["gone.ts"]?.change).toEqual({ kind: "delete" });
    expect(byPath["b.ts"]?.change).toEqual({
      kind: "move",
      fromPath: "a.ts",
    });
  });

  it("dedupe keeps last change preview", () => {
    const arts = mergeArtifacts(
      fileArtifactsFromProcess([
        toolStep("file_write", { path: "a.ts", content: "v1" }),
        toolStep("str_replace", {
          path: "a.ts",
          old_string: "v1",
          new_string: "v2",
        }),
      ]),
    );
    expect(arts).toHaveLength(1);
    expect(arts[0].op).toBe("edit");
    expect(arts[0].change?.kind).toBe("edit");
  });

  it("hasChangePreviews is false without change payloads", () => {
    const bare: FileArtifact[] = [{ path: "x.ts", name: "x.ts", op: "write" }];
    expect(hasChangePreviews(bare)).toBe(false);
  });

  it("strips /workspace/ sandbox absolutes so preview/open paths match on-disk", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("file_write", {
        path: "/workspace/index.html",
        content: "<html/>",
      }),
      toolStep("file_move", {
        source: "/workspace/a.ts",
        destination: "/workspace/site/b.ts",
      }),
    ]);
    expect(arts.map((a) => a.path)).toEqual(["index.html", "site/b.ts"]);
    expect(arts[0].name).toBe("index.html");
    expect(arts[1].fromPath).toBe("a.ts");
  });

  it("dedupes absolute /workspace/x with relative x as the same artifact", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("file_write", { path: "/workspace/a.ts", content: "v1" }),
      toolStep("str_replace", {
        path: "a.ts",
        old_string: "v1",
        new_string: "v2",
      }),
    ]);
    expect(arts).toHaveLength(1);
    expect(arts[0].path).toBe("a.ts");
    expect(arts[0].op).toBe("edit");
  });

  it("leaves relative workspace/… paths alone (may be a real subdirectory)", () => {
    const arts = fileArtifactsFromProcess([
      toolStep("file_write", {
        path: "workspace/nested.html",
        content: "x",
      }),
    ]);
    expect(arts[0].path).toBe("workspace/nested.html");
  });
});
