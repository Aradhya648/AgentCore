import { describe, expect, it } from "vitest";
import {
  embeddedPreviewVisible,
  previewAddressLabel,
} from "../embeddedPreview";

describe("embeddedPreviewVisible（内嵌预览遮挡判定）", () => {
  it("激活且无遮挡 → 可见", () => {
    expect(embeddedPreviewVisible(true, false)).toBe(true);
  });

  it("非激活 → 隐藏（无论遮挡）", () => {
    expect(embeddedPreviewVisible(false, false)).toBe(false);
    expect(embeddedPreviewVisible(false, true)).toBe(false);
  });

  it("激活但被弹层遮挡 → 隐藏（让位给 dialog / dropdown / 命令面板）", () => {
    expect(embeddedPreviewVisible(true, true)).toBe(false);
  });
});

describe("previewAddressLabel（只读地址栏文案）", () => {
  it("preview:// 地址 → 解码后的工作区相对路径", () => {
    expect(
      previewAddressLabel("preview://conv-id/dir/a%20b.html", "entry.html"),
    ).toBe("dir/a b.html");
  });

  it("空地址（未加载）→ 回退到入口文件路径", () => {
    expect(previewAddressLabel(null, "site/index.html")).toBe(
      "site/index.html",
    );
    expect(previewAddressLabel("", "site/index.html")).toBe("site/index.html");
  });

  it("preview 根地址（无路径）→ 回退到入口路径", () => {
    expect(previewAddressLabel("preview://conv-id/", "index.html")).toBe(
      "index.html",
    );
  });

  it("非 preview scheme（异常情况）→ 原样展示真实去向，不隐藏", () => {
    expect(previewAddressLabel("https://example.com/x", "index.html")).toBe(
      "https://example.com/x",
    );
  });

  it("无法解析 → 回退到入口路径", () => {
    expect(previewAddressLabel("::::", "index.html")).toBe("index.html");
  });
});
