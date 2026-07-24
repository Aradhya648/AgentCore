import { api } from "@/services/api";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { rewriteSelection } from "../rewrite";

vi.mock("@/services/api", () => ({ api: { post: vi.fn() } }));

const post = vi.mocked(api.post);

beforeEach(() => {
  post.mockReset();
});

describe("rewriteSelection", () => {
  it("maps camelCase params to the snake_case request body and returns rewritten", async () => {
    post.mockResolvedValue({ rewritten: "改写后的文本" });

    const out = await rewriteSelection({
      selection: "今天天气不错",
      instruction: "改得更正式",
      contextBefore: "前文",
      contextAfter: "后文",
    });

    expect(out).toBe("改写后的文本");
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/v1/files/assist/rewrite", {
      selection: "今天天气不错",
      instruction: "改得更正式",
      context_before: "前文",
      context_after: "后文",
    });
  });

  it("defaults missing context fields to empty strings (never undefined on the wire)", async () => {
    post.mockResolvedValue({ rewritten: "x" });

    await rewriteSelection({ selection: "s", instruction: "i" });

    expect(post).toHaveBeenCalledWith("/v1/files/assist/rewrite", {
      selection: "s",
      instruction: "i",
      context_before: "",
      context_after: "",
    });
  });

  it("propagates api errors to the caller (e.g. 402 LLM_KEY_REQUIRED)", async () => {
    const err = new Error("LLM_KEY_REQUIRED");
    post.mockRejectedValue(err);

    await expect(
      rewriteSelection({ selection: "s", instruction: "i" }),
    ).rejects.toBe(err);
  });
});
