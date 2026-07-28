import { conversationHasFileArtifacts } from "@/lib/conversationFileChanges";
import type { Message } from "@/stores/conversation/types";
import type { ProcessStep } from "@/types/events";
import { describe, expect, it } from "vitest";

function toolStep(
  tool_name: string,
  args: Record<string, unknown>,
): ProcessStep {
  return {
    kind: "tool",
    id: `t-${tool_name}`,
    tool_name,
    arguments: args,
    result: null,
    status: "success",
  };
}

function msg(
  partial: Partial<Message> & Pick<Message, "id" | "role">,
): Message {
  return {
    content: "",
    createdAt: new Date().toISOString(),
    executionId: null,
    isStreaming: false,
    ...partial,
  };
}

describe("conversationHasFileArtifacts", () => {
  it("is false when there are no assistant file ops", () => {
    expect(
      conversationHasFileArtifacts(
        [
          msg({ id: "u1", role: "user", content: "hi" }),
          msg({ id: "a1", role: "assistant", content: "ok" }),
        ],
        {},
      ),
    ).toBe(false);
  });

  it("is true when process has a successful file write", () => {
    expect(
      conversationHasFileArtifacts(
        [
          msg({
            id: "a1",
            role: "assistant",
            process: [toolStep("file_write", { path: "a.ts", content: "x" })],
          }),
        ],
        {},
      ),
    ).toBe(true);
  });
});
