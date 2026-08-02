import { describe, expect, it } from "vitest";
import {
  MODEL_CONFIG_PATH,
  StreamHttpError,
  describeStreamHttpError,
  emptyChatCopy,
  emptyFailureNotice,
  errorActionForCode,
} from "../errors";

describe("errorActionForCode", () => {
  it("routes LLM_KEY_REQUIRED to 去配置", () => {
    expect(errorActionForCode("LLM_KEY_REQUIRED")).toEqual({
      label: "去配置",
      href: MODEL_CONFIG_PATH,
    });
  });

  it("routes LLM_KEY_INVALID to 去配置 (BYOK) or 接入自己的 Key (platform)", () => {
    expect(errorActionForCode("LLM_KEY_INVALID")).toEqual({
      label: "去配置",
      href: MODEL_CONFIG_PATH,
    });
    expect(
      errorActionForCode("LLM_KEY_INVALID", { credentialSource: "platform" }),
    ).toEqual({
      label: "接入自己的 Key",
      href: MODEL_CONFIG_PATH,
    });
  });

  it("offers a BYOK secondary exit for QUOTA_EXCEEDED (F6), null otherwise", () => {
    expect(errorActionForCode("QUOTA_EXCEEDED")).toEqual({
      label: "接入自己的 Key",
      href: MODEL_CONFIG_PATH,
    });
    expect(errorActionForCode("SOME_UNKNOWN")).toBeNull();
    expect(errorActionForCode(undefined)).toBeNull();
  });
});

describe("describeStreamHttpError", () => {
  it("prefers the backend message for LLM_KEY_REQUIRED and offers 去配置", () => {
    const err = new StreamHttpError(
      402,
      "LLM_KEY_REQUIRED",
      "请先在「设置 · 模型配置」中填入你的 API Key，再发起对话。",
    );
    expect(describeStreamHttpError(err)).toEqual({
      message: "请先在「设置 · 模型配置」中填入你的 API Key，再发起对话。",
      action: { label: "去配置", href: MODEL_CONFIG_PATH },
    });
  });

  it("falls back to a config hint when the body has no message", () => {
    const err = new StreamHttpError(402, "LLM_KEY_REQUIRED");
    const d = describeStreamHttpError(err);
    expect(d.message).toContain("模型配置");
    expect(d.action?.label).toBe("去配置");
  });

  it("surfaces a generic status message without action when code is unknown", () => {
    const err = new StreamHttpError(500, undefined, undefined);
    expect(describeStreamHttpError(err)).toEqual({
      message: "请求失败 (500)",
      action: null,
    });
  });
});

describe("emptyChatCopy", () => {
  it("returns the no-gate welcome copy (platform-paid, keyless included)", () => {
    const copy = emptyChatCopy();
    expect(copy.title).toBe("开始新对话");
    expect(copy.subtitle).toContain("Agent 团队");
    expect(copy.action).toBeNull();
  });
});

describe("emptyFailureNotice", () => {
  it("explains empty error / unproductive finishes", () => {
    expect(emptyFailureNotice("error")).toBe("模型调用失败，请重试。");
    expect(emptyFailureNotice("unproductive")).toBe(
      "工具连续无有效进展或参数无效，请重试。",
    );
  });

  it("stays silent for normal / other finishes", () => {
    expect(emptyFailureNotice("end_turn")).toBeNull();
    expect(emptyFailureNotice("degraded")).toBeNull();
    expect(emptyFailureNotice(null)).toBeNull();
    expect(emptyFailureNotice(undefined)).toBeNull();
  });
});
