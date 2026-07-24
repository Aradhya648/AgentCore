import { afterEach, describe, expect, it, vi } from "vitest";

// The service keeps its failure map as module singleton state (mirroring the
// real renderer-global subscription), so each test uses a UNIQUE rootId to avoid
// cross-test bleed — and the consume-on-take semantics keep them isolated anyway.
import {
  recordStatus,
  takeRecentSidecarFailure,
} from "@/services/sidecarStatus";

afterEach(() => vi.useRealTimers());

describe("sidecar status diagnostics (onStatus consumer)", () => {
  it("surfaces an init-failure (error) as a startup diagnostic", () => {
    recordStatus({
      rootId: "r-err",
      phase: "error",
      detail: "spawn uv ENOENT",
    });
    expect(takeRecentSidecarFailure("r-err")).toBe(
      "本地引擎启动失败：spawn uv ENOENT",
    );
  });

  it("surfaces a process exit as an exit diagnostic", () => {
    recordStatus({
      rootId: "r-exit",
      phase: "exited",
      detail: "sidecar 进程退出（code 1）",
    });
    expect(takeRecentSidecarFailure("r-exit")).toBe(
      "本地引擎进程已退出：sidecar 进程退出（code 1）",
    );
  });

  it("falls back to a default detail when none is given", () => {
    recordStatus({ rootId: "r-nodetail", phase: "error" });
    expect(takeRecentSidecarFailure("r-nodetail")).toBe(
      "本地引擎启动失败：启动失败",
    );
  });

  it("clears a stale failure when the root respawns healthy (spawned)", () => {
    recordStatus({ rootId: "r-heal", phase: "error", detail: "boom" });
    recordStatus({ rootId: "r-heal", phase: "spawned" });
    expect(takeRecentSidecarFailure("r-heal")).toBeNull();
  });

  it("consumes one-shot: the same diagnostic explains only one turn", () => {
    recordStatus({ rootId: "r-once", phase: "error", detail: "boom" });
    expect(takeRecentSidecarFailure("r-once")).toBe("本地引擎启动失败：boom");
    expect(takeRecentSidecarFailure("r-once")).toBeNull();
  });

  it("ignores a failure older than the relevance window (no stale mislabel)", () => {
    vi.useFakeTimers();
    recordStatus({ rootId: "r-stale", phase: "exited", detail: "old" });
    vi.advanceTimersByTime(15_001);
    expect(takeRecentSidecarFailure("r-stale")).toBeNull();
  });

  it("scopes diagnostics per root (one root's failure never leaks to another)", () => {
    recordStatus({ rootId: "r-a", phase: "error", detail: "a-down" });
    expect(takeRecentSidecarFailure("r-b")).toBeNull();
    expect(takeRecentSidecarFailure("r-a")).toBe("本地引擎启动失败：a-down");
  });
});
