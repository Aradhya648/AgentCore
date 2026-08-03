import {
  StreamError,
  describeStreamError,
  errorActionForCode,
  isRetriableStreamError,
  streamErrorAction,
} from "@/lib/errors";
import { afterEach, describe, expect, it, vi } from "vitest";
import { attachConversation, streamConversation } from "../streamConversation";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("describeStreamError", () => {
  it("surfaces the backend's verbatim message for a 429 (quota reset / cool-down)", () => {
    const err = new StreamError("http", 429, {
      code: "QUOTA_EXCEEDED",
      serverMessage:
        "已达每日 token 上限（2,000,000 / 2,000,000），明日 0 点（UTC）重置。",
    });
    expect(describeStreamError(err)).toBe(
      "已达每日 token 上限（2,000,000 / 2,000,000），明日 0 点（UTC）重置。",
    );
  });

  it("falls back to a cool-down message for a 429 with only Retry-After", () => {
    const err = new StreamError("http", 429, {
      code: "RATE_LIMITED",
      retryAfter: 30,
    });
    expect(describeStreamError(err)).toBe("操作过于频繁，请约 30 秒后再试");
  });

  it("falls back to a generic 429 message when nothing rides along", () => {
    expect(describeStreamError(new StreamError("http", 429))).toBe(
      "操作过于频繁或额度已用尽，请稍后再试",
    );
  });

  it("surfaces the backend's actionable message for a 402 missing BYOK key", () => {
    const err = new StreamError("http", 402, {
      code: "LLM_KEY_REQUIRED",
      serverMessage:
        "请先在「设置 · 模型配置」中填入你的 DeepSeek API Key，再发起对话。",
    });
    expect(describeStreamError(err)).toBe(
      "请先在「设置 · 模型配置」中填入你的 DeepSeek API Key，再发起对话。",
    );
  });

  it("falls back to a config hint for a 402 with no server message", () => {
    const err = new StreamError("http", 402, { code: "LLM_KEY_REQUIRED" });
    expect(describeStreamError(err)).toContain("服务商");
    expect(describeStreamError(err)).not.toContain("服务暂时不可用");
  });

  it("phrases other http errors as a temporary outage", () => {
    expect(describeStreamError(new StreamError("http", 503))).toContain(
      "服务暂时不可用",
    );
  });

  it("maps turn_in_progress to an explicit zh resume hint", () => {
    expect(
      describeStreamError(
        new StreamError("http", 409, { code: "turn_in_progress" }),
      ),
    ).toBe("会话中有正在进行的回合，等它结束后再继续");
    expect(
      describeStreamError(
        new StreamError("http", 409, {
          code: "turn_in_progress",
          serverMessage: "后端自定义文案",
        }),
      ),
    ).toBe("后端自定义文案");
  });

  it("phrases network errors and stays silent on auth", () => {
    expect(describeStreamError(new StreamError("network"))).toContain("网络");
    expect(describeStreamError(new StreamError("auth"))).toBeNull();
  });

  it("maps CLIENT_TOO_OLD / 426 to force-update product copy", () => {
    expect(
      describeStreamError(
        new StreamError("http", 426, {
          code: "CLIENT_TOO_OLD",
          serverMessage: "upgrade required",
        }),
      ),
    ).toBe("桌面端版本过旧，请更新后再试");
    expect(describeStreamError(new StreamError("http", 426))).toBe(
      "桌面端版本过旧，请更新后再试",
    );
  });
});

describe("isRetriableStreamError", () => {
  it("does not offer retry for a quota refusal (resets on a schedule)", () => {
    const err = new StreamError("http", 429, { code: "QUOTA_EXCEEDED" });
    expect(isRetriableStreamError(err)).toBe(false);
  });

  it("does not offer retry for a missing BYOK key (needs configuration)", () => {
    const err = new StreamError("http", 402, { code: "LLM_KEY_REQUIRED" });
    expect(isRetriableStreamError(err)).toBe(false);
  });

  it("offers retry for rate-limit, transport, and unknown errors", () => {
    expect(
      isRetriableStreamError(
        new StreamError("http", 429, { code: "RATE_LIMITED" }),
      ),
    ).toBe(true);
    expect(isRetriableStreamError(new StreamError("network"))).toBe(true);
    expect(isRetriableStreamError(new Error("boom"))).toBe(true);
  });
});

describe("errorActionForCode", () => {
  it("routes missing and invalid keys to the providers page", () => {
    expect(errorActionForCode("LLM_KEY_REQUIRED")).toEqual({
      label: "去设置",
      href: "/more/providers",
    });
    expect(errorActionForCode("LLM_KEY_INVALID")).toEqual({
      label: "去设置",
      href: "/more/providers",
    });
  });

  it("routes FREE_TIER_EXHAUSTED as unknown code (no settings CTA)", () => {
    // FREE_TIER_EXHAUSTED retired with the free-tier path; leftover wire codes
    // fall through to null action (quota uses QUOTA_EXCEEDED).
    expect(errorActionForCode("FREE_TIER_EXHAUSTED")).toBeNull();
  });

  it("routes balance errors to settings; quota offers a BYOK secondary exit (F6)", () => {
    expect(errorActionForCode("LLM_INSUFFICIENT_BALANCE")).toEqual({
      label: "去设置",
      href: "/more/providers",
    });
    // 平台额度耗尽补次级 CTA「接入自己的 Key」(成本配额与计费 §〇·六 F6).
    expect(errorActionForCode("QUOTA_EXCEEDED")).toEqual({
      label: "接入自己的 Key",
      href: "/more/providers",
    });
    expect(errorActionForCode(undefined)).toBeNull();
  });

  it("streamErrorAction delegates to the code map for a StreamError", () => {
    expect(
      streamErrorAction(
        new StreamError("http", 402, { code: "LLM_KEY_REQUIRED" }),
      ),
    ).toEqual({ label: "去设置", href: "/more/providers" });
    expect(streamErrorAction(new Error("boom"))).toBeNull();
  });
});

describe("streamConversation (refused turn)", () => {
  it("parses a 429 JSON body + Retry-After header into a StreamError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: {
                code: "RATE_LIMITED",
                message: "操作过于频繁，请约 42 秒后再发送。",
              },
            }),
            {
              status: 429,
              headers: {
                "Content-Type": "application/json",
                "Retry-After": "42",
              },
            },
          ),
        ),
      ),
    );

    const err = await streamConversation({
      conversationId: "c1",
      content: "hi",
      attachments: [],
      delivery: "steer",
    }).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(StreamError);
    const streamErr = err as StreamError;
    expect(streamErr.status).toBe(429);
    expect(streamErr.code).toBe("RATE_LIMITED");
    expect(streamErr.serverMessage).toBe("操作过于频繁，请约 42 秒后再发送。");
    expect(streamErr.retryAfter).toBe(42);
  });
});

describe("attachConversation (实时重连续看 1b)", () => {
  it("returns 'none' on a 204 so the caller falls back to the persisted transcript", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
    );
    await expect(attachConversation("c1")).resolves.toBe("none");
  });

  it("targets the conversation's stream endpoint with a GET", async () => {
    const fetchMock = vi.fn((_input: string, _init?: RequestInit) =>
      Promise.resolve(new Response(null, { status: 204 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    await attachConversation("conv-42");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/v1/conversations/conv-42/stream");
    expect(init?.method).toBe("GET");
  });

  it("raises a StreamError when the attach is refused (e.g. not owned → 404)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ error: { code: "NOT_FOUND" } }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    const err = await attachConversation("c1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(StreamError);
    expect((err as StreamError).status).toBe(404);
  });
});
