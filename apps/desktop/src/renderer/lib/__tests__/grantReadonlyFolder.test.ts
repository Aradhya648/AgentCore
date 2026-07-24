import { describe, expect, it } from "vitest";
import { formatGrantReadonlyFolderAnswer } from "../grantReadonlyFolder";

describe("formatGrantReadonlyFolderAnswer", () => {
  it("mentions readonly session scope without absolute paths", () => {
    const text = formatGrantReadonlyFolderAnswer(
      "授权只读访问",
      "6月报表",
      "external/6月报表",
    );
    expect(text).toContain("只读");
    expect(text).toContain("仅本次对话");
    expect(text).toContain("可撤销");
    expect(text).toContain("external/6月报表");
    expect(text).not.toMatch(/^[A-Za-z]:\\/);
  });
});
