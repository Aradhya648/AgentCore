import { describe, expect, it } from "vitest";
import {
  sessionDeviceLabel,
  sessionLastActiveLabel,
} from "../sessionDeviceLabel";

describe("sessionDeviceLabel", () => {
  it("labels Windows / macOS / Linux desktop from platform + UA", () => {
    expect(
      sessionDeviceLabel(
        "desktop",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Electron/28.0.0",
      ),
    ).toBe("Windows 桌面端");
    expect(
      sessionDeviceLabel(
        "desktop",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Electron/28.0.0",
      ),
    ).toBe("macOS 桌面端");
    expect(
      sessionDeviceLabel(
        "desktop",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Electron/28.0.0",
      ),
    ).toBe("Linux 桌面端");
  });

  it("labels mobile devices from UA", () => {
    expect(
      sessionDeviceLabel(
        "mobile",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
      ),
    ).toBe("iPhone");
    expect(
      sessionDeviceLabel(
        "mobile",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36",
      ),
    ).toBe("Android");
  });

  it("labels plain browser as 网页 and admin as 管理后台", () => {
    expect(
      sessionDeviceLabel(
        "desktop",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      ),
    ).toBe("网页");
    expect(sessionDeviceLabel("admin", "curl/8.0")).toBe("管理后台");
  });

  it("falls back to platform text or 未知设备", () => {
    expect(sessionDeviceLabel("desktop", null)).toBe("桌面端");
    expect(sessionDeviceLabel("mobile", "")).toBe("移动端");
    expect(sessionDeviceLabel("custom-platform", null)).toBe("custom-platform");
    expect(sessionDeviceLabel(null, null)).toBe("未知设备");
  });
});

describe("sessionLastActiveLabel", () => {
  const now = Date.parse("2026-07-12T12:00:00Z");

  it("formats relative Chinese phrases", () => {
    expect(sessionLastActiveLabel("2026-07-12T11:59:30Z", now)).toBe("刚刚");
    expect(sessionLastActiveLabel("2026-07-12T11:45:00Z", now)).toBe(
      "15 分钟前",
    );
    expect(sessionLastActiveLabel("2026-07-12T09:00:00Z", now)).toBe(
      "3 小时前",
    );
    expect(sessionLastActiveLabel("2026-07-10T12:00:00Z", now)).toBe("2 天前");
  });
});
