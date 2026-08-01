import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  api: { post: vi.fn() },
  BASE_URL: "http://test",
}));

import { api } from "@/services/api";
import { requestAutoTitle } from "@/services/conversations";

const post = vi.mocked(api.post);

beforeEach(() => {
  post.mockReset();
});

describe("requestAutoTitle", () => {
  it("posts user_message to …/auto-title and returns title", async () => {
    post.mockResolvedValueOnce({ title: "周报提纲" });
    const out = await requestAutoTitle("c1", "  帮我写周报  ");
    expect(post).toHaveBeenCalledWith("/v1/conversations/c1/auto-title", {
      user_message: "帮我写周报",
    });
    expect(out).toBe("周报提纲");
  });

  it("returns null on blank input without calling the API", async () => {
    expect(await requestAutoTitle("c1", "   ")).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it("returns null on API failure (silent)", async () => {
    post.mockRejectedValueOnce(new Error("network"));
    expect(await requestAutoTitle("c1", "hi")).toBeNull();
  });
});
