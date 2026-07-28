import { FINISH_REASON_META } from "@/components/ui/finish-reason-chip";
import {
  connectivityEscalationSuffix,
  errorActionForCode,
  isClientSideLlmRejection,
  isConnectivityErrorCode,
  resetSessionConnectivityFailures,
  syntheticErrorForEmptyFailure,
} from "@/lib/errors";
import { afterEach, describe, expect, it } from "vitest";

describe("syntheticErrorForEmptyFailure", () => {
  it("synthesizes a card for empty error-finished turns", () => {
    expect(syntheticErrorForEmptyFailure("error")).toEqual({
      code: "LLM_ERROR",
      message: "模型调用失败，请重试。",
    });
  });

  it("keeps upstream rate-limit product copy when code is known", () => {
    expect(syntheticErrorForEmptyFailure("error", "LLM_RATE_LIMIT")).toEqual({
      code: "LLM_RATE_LIMIT",
      message: "上游限流，暂时无法继续本回合。请稍后再试或点重试。",
    });
  });

  it("returns null for non-error finishes", () => {
    expect(syntheticErrorForEmptyFailure("end_turn")).toBeNull();
    expect(syntheticErrorForEmptyFailure("degraded")).toBeNull();
    expect(syntheticErrorForEmptyFailure(undefined)).toBeNull();
  });
});

describe("LLM_RATE_LIMIT connectivity", () => {
  it("treats upstream rate limit as retriable connectivity", () => {
    expect(isConnectivityErrorCode("LLM_RATE_LIMIT")).toBe(true);
  });
});

describe("FinishReasonChip error meta", () => {
  it("includes an error entry", () => {
    expect(FINISH_REASON_META.error).toMatchObject({ label: "调用失败" });
  });
});

describe("error action by type", () => {
  it("auth / balance → 去设置; connectivity → null (retry in bubble)", () => {
    expect(errorActionForCode("LLM_KEY_INVALID")?.label).toBe("去设置");
    expect(errorActionForCode("LLM_INSUFFICIENT_BALANCE")?.label).toBe(
      "去设置",
    );
    expect(errorActionForCode("LLM_TIMEOUT")).toBeNull();
    expect(isConnectivityErrorCode("LLM_TIMEOUT")).toBe(true);
    expect(isConnectivityErrorCode("LLM_KEY_INVALID")).toBe(false);
  });
});

describe("isClientSideLlmRejection", () => {
  it("treats 4xx (except 429) as client rejection", () => {
    expect(isClientSideLlmRejection({ upstreamStatus: 400 })).toBe(true);
    expect(isClientSideLlmRejection({ upstreamStatus: 422 })).toBe(true);
    expect(isClientSideLlmRejection({ upstreamStatus: 429 })).toBe(false);
    expect(isClientSideLlmRejection({ upstreamStatus: 502 })).toBe(false);
  });

  it("matches invalid_request / jiurelay copy in message text", () => {
    expect(
      isClientSideLlmRejection({
        message:
          "platform 请求参数或消息格式不被当前模型支持，请检查 messages、tools、tool_choice",
      }),
    ).toBe(true);
    expect(
      isClientSideLlmRejection({
        message: '{"error":{"code":"invalid_request"}}',
      }),
    ).toBe(true);
    expect(isClientSideLlmRejection({ message: "连接超时" })).toBe(false);
  });
});

describe("connectivityEscalationSuffix", () => {
  afterEach(() => {
    resetSessionConnectivityFailures();
  });

  it("stays quiet on the first failure, escalates from the second message", () => {
    expect(connectivityEscalationSuffix("LLM_TIMEOUT", "m1")).toBeNull();
    expect(connectivityEscalationSuffix("LLM_TIMEOUT", "m2")).toContain(
      "设置 · 服务商",
    );
    // Same message id must not re-count.
    expect(connectivityEscalationSuffix("LLM_TIMEOUT", "m2")).toContain(
      "设置 · 服务商",
    );
  });

  it("ignores non-connectivity codes", () => {
    expect(connectivityEscalationSuffix("LLM_KEY_INVALID", "m1")).toBeNull();
    expect(connectivityEscalationSuffix(undefined, "m1")).toBeNull();
  });

  it("does not escalate upstream 400 invalid_request into connectivity hint", () => {
    expect(
      connectivityEscalationSuffix("LLM_ERROR", "m1", {
        message: "platform 请求参数或消息格式不被当前模型支持",
        upstreamStatus: 400,
      }),
    ).toBeNull();
    expect(
      connectivityEscalationSuffix("LLM_ERROR", "m2", {
        message: "platform 请求参数或消息格式不被当前模型支持",
        upstreamStatus: 400,
      }),
    ).toBeNull();
  });
});
