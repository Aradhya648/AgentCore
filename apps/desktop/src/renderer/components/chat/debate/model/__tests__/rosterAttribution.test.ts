import { describe, expect, it } from "vitest";
import {
  formatCrossModelRosterLine,
  formatModelSlotLabel,
} from "../rosterAttribution";

describe("formatModelSlotLabel", () => {
  it("maps provider prefix to vendor label", () => {
    expect(formatModelSlotLabel("doubao/seed-2.0")).toBe("豆包");
    expect(formatModelSlotLabel("deepseek/deepseek-v4-flash")).toBe("DeepSeek");
  });

  it("appends ·BYOK when origin is byok", () => {
    expect(formatModelSlotLabel("deepseek/deepseek-v4-flash", "byok")).toBe(
      "DeepSeek·BYOK",
    );
  });

  it("empty model → null", () => {
    expect(formatModelSlotLabel("")).toBeNull();
    expect(formatModelSlotLabel(null)).toBeNull();
    expect(formatModelSlotLabel(undefined)).toBeNull();
  });
});

describe("formatCrossModelRosterLine", () => {
  it("有模型字段 → 正方 X · 反方 Y · 裁判 Z", () => {
    expect(
      formatCrossModelRosterLine(
        [
          { name: "正方", model: "doubao/seed-2.0", origin: "platform" },
          {
            name: "反方",
            model: "deepseek/deepseek-v4-flash",
            origin: "platform",
          },
        ],
        { model: "deepseek/deepseek-v4-pro", origin: "platform" },
      ),
    ).toBe("正方 豆包 · 反方 DeepSeek · 裁判 DeepSeek");
  });

  it("无模型字段 → null（同模型场零噪声）", () => {
    expect(
      formatCrossModelRosterLine([{ name: "正方" }, { name: "反方" }], null),
    ).toBeNull();
    expect(
      formatCrossModelRosterLine(
        [
          { name: "正方", model: "" },
          { name: "反方", model: "  " },
        ],
        { model: "" },
      ),
    ).toBeNull();
  });

  it("仅裁判有 model 也出署名", () => {
    expect(
      formatCrossModelRosterLine([{ name: "正方" }, { name: "反方" }], {
        model: "deepseek/deepseek-v4-flash",
      }),
    ).toBe("裁判 DeepSeek");
  });
});
