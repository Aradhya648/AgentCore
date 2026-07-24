// @vitest-environment node
/**
 * listLlmProviders maps ADMIN_PRODUCT_FORBIDDEN to the shared product-face zh hint
 * (ModelSettings shows err.message on load failure).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "@/api/client";
import {
  ADMIN_PRODUCT_FORBIDDEN_MESSAGE,
  listLlmProviders,
} from "@/api/llmProviders";

const mockFetch = vi.mocked(apiFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

describe("listLlmProviders admin gate", () => {
  it("rewrites ADMIN_PRODUCT_FORBIDDEN to the shared zh hint", async () => {
    mockFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "ADMIN_PRODUCT_FORBIDDEN",
            message: "管理员账号请使用管理后台登录",
          },
        }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );
    await expect(listLlmProviders()).rejects.toThrow(
      ADMIN_PRODUCT_FORBIDDEN_MESSAGE,
    );
  });
});
