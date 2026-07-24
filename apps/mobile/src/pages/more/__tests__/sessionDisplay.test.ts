import {
  formatDeviceLabel,
  formatRelativeTime,
} from "@/pages/more/sessionDisplay";
import { describe, expect, it } from "vitest";

describe("formatDeviceLabel", () => {
  it("maps desktop + Windows UA to Windows 桌面端", () => {
    expect(
      formatDeviceLabel("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
    ).toBe("Windows 桌面端");
  });

  it("maps iPhone UA regardless of platform", () => {
    expect(
      formatDeviceLabel(
        "mobile",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
      ),
    ).toBe("iPhone");
  });

  it("maps Android UA", () => {
    expect(
      formatDeviceLabel(
        "mobile",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36",
      ),
    ).toBe("Android");
  });

  it("maps browser UA without platform to 网页", () => {
    expect(
      formatDeviceLabel(
        null,
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      ),
    ).toBe("网页");
  });

  it("falls back to platform raw when UA is unrecognized", () => {
    expect(formatDeviceLabel("desktop", "AgentCore/1.0")).toBe("桌面端");
    expect(formatDeviceLabel("custom-client", null)).toBe("custom-client");
  });

  it("labels admin sessions", () => {
    expect(formatDeviceLabel("admin", "Mozilla/5.0")).toBe("管理端（网页）");
    expect(formatDeviceLabel("admin", null)).toBe("管理端");
  });
});

describe("formatRelativeTime", () => {
  const now = Date.parse("2026-07-12T12:00:00.000Z");

  it("formats just-now / minutes / hours / days", () => {
    expect(formatRelativeTime("2026-07-12T11:59:30.000Z", now)).toBe("刚刚");
    expect(formatRelativeTime("2026-07-12T11:45:00.000Z", now)).toBe(
      "15 分钟前",
    );
    expect(formatRelativeTime("2026-07-12T09:00:00.000Z", now)).toBe(
      "3 小时前",
    );
    expect(formatRelativeTime("2026-07-10T12:00:00.000Z", now)).toBe("2 天前");
  });
});
