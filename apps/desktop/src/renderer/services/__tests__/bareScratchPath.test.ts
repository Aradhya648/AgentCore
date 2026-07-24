import { describe, expect, it } from "vitest";
import { bareConversationScratchSubpath } from "../bareScratchPath";

describe("bareConversationScratchSubpath", () => {
  it("returns conversations/<id> under the container root", () => {
    expect(bareConversationScratchSubpath("abc-123")).toBe(
      "conversations/abc-123",
    );
  });
});
