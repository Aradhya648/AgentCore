import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// sidecarHealth 的失败诊断取自 sidecarStatus；mock 掉它，让每个用例自己控制「探活失败时带出
// 的诊断」（真实实现是与主进程 onStatus 推送绑定的一次性消费，见 sidecarStatus.test）。
vi.mock("@/services/sidecarStatus", () => ({
  takeRecentSidecarFailure: vi.fn(() => null),
}));

import type { SidecarTarget } from "@/services/sidecarRouting";
import { takeRecentSidecarFailure } from "@/services/sidecarStatus";
import {
  clearSidecarHealth,
  getSidecarHealth,
  markSidecarUnhealthy,
  probeSidecar,
} from "../sidecarHealth";

const takeRecentSidecarFailureMock = vi.mocked(takeRecentSidecarFailure);

function target(rootId = "r1", subpath = ""): SidecarTarget {
  return { rootId, subpath };
}

let probeMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clearSidecarHealth(); // 模块单例 Map：每个用例从干净状态起
  takeRecentSidecarFailureMock.mockReturnValue(null);
  probeMock = vi.fn(() => Promise.resolve());
  // SUT 经 preload `window.sidecarApi` 桥到主进程；node 测试环境无 `window`，直接注入
  // （镜像 streamConversationViaSidecar.test 的做法）。
  (globalThis as Record<string, unknown>).window = {
    sidecarApi: { probe: probeMock },
  };
});

afterEach(() => {
  clearSidecarHealth();
  (globalThis as Record<string, unknown>).window = undefined;
});

describe("sidecarHealth — 首次探活 + 会话级健康缓存", () => {
  it("探活未知根：握手成功 → 标 ok、返回 healthy、按 root+subpath 拉起一次", async () => {
    const t = target("r-ok");
    await expect(probeSidecar(t)).resolves.toEqual({
      healthy: true,
      probed: true,
      detail: null,
    });
    expect(probeMock).toHaveBeenCalledTimes(1);
    expect(probeMock).toHaveBeenCalledWith({ rootId: "r-ok", subpath: "" });
    expect(getSidecarHealth(t)).toBe("ok");
  });

  it("已 ok 的根：再探活直接命中缓存，不再拉起", async () => {
    const t = target("r-ok2");
    await probeSidecar(t);
    await expect(probeSidecar(t)).resolves.toEqual({
      healthy: true,
      probed: false,
      detail: null,
    });
    expect(probeMock).toHaveBeenCalledTimes(1); // 未重探
  });

  it("探活失败：标 bad，并带出 sidecarStatus 的针对性诊断", async () => {
    takeRecentSidecarFailureMock.mockReturnValue(
      "本地引擎启动失败：spawn uv ENOENT",
    );
    probeMock.mockRejectedValue(new Error("handshake failed"));
    const t = target("r-bad");
    await expect(probeSidecar(t)).resolves.toEqual({
      healthy: false,
      probed: true,
      detail: "本地引擎启动失败：spawn uv ENOENT",
    });
    expect(getSidecarHealth(t)).toBe("bad");
  });

  it("探活失败但无诊断：detail 为 null（调用方退回兜底文案）", async () => {
    probeMock.mockRejectedValue(new Error("boom"));
    await expect(probeSidecar(target("r-bad2"))).resolves.toEqual({
      healthy: false,
      probed: true,
      detail: null,
    });
  });

  it("已 bad 的根：再探活直接命中缓存（false、无诊断），不再拉起", async () => {
    probeMock.mockRejectedValue(new Error("boom"));
    const t = target("r-bad3");
    await probeSidecar(t); // → bad，probe 调用一次
    await expect(probeSidecar(t)).resolves.toEqual({
      healthy: false,
      probed: false,
      detail: null,
    });
    expect(probeMock).toHaveBeenCalledTimes(1); // 未重探
  });

  it("markSidecarUnhealthy：降级路径直接标 bad，后续探活命中缓存、不拉起", async () => {
    const t = target("r-mark");
    markSidecarUnhealthy(t);
    expect(getSidecarHealth(t)).toBe("bad");
    await expect(probeSidecar(t)).resolves.toEqual({
      healthy: false,
      probed: false,
      detail: null,
    });
    expect(probeMock).not.toHaveBeenCalled();
  });

  it("clearSidecarHealth：清空 → 回到 unknown、允许对修好的根重探", async () => {
    const t = target("r-clear");
    markSidecarUnhealthy(t);
    clearSidecarHealth();
    expect(getSidecarHealth(t)).toBe("unknown");
    await probeSidecar(t);
    expect(probeMock).toHaveBeenCalledTimes(1); // 清空后重探
    expect(getSidecarHealth(t)).toBe("ok");
  });

  it("非桌面 / 未注入 sidecarApi：视作不健康、不抛", async () => {
    (globalThis as Record<string, unknown>).window = {};
    await expect(probeSidecar(target("r-web"))).resolves.toEqual({
      healthy: false,
      probed: false,
      detail: null,
    });
  });

  it("按 root + subpath 分别缓存（同根不同子路径互不影响）", async () => {
    const root = target("r-multi", "");
    const sub = target("r-multi", "pkg/app");
    await probeSidecar(root);
    expect(getSidecarHealth(root)).toBe("ok");
    expect(getSidecarHealth(sub)).toBe("unknown"); // 独立 key（r-multi:: vs r-multi::pkg/app）
  });
});
