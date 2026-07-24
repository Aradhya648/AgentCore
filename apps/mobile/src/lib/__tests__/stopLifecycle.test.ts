import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  STOPPED_LABEL,
  STOPPING_LABEL,
  STOP_CONFIRM_TIMEOUT_MS,
  STOP_FAILED_MESSAGE,
  STOP_UNCONFIRMED_MESSAGE,
  allowsEventWhileStopping,
  createStopConfirmTimer,
  isStopBusy,
  isStopConfirmEvent,
  reduceStopPhase,
  stopButtonLabel,
} from "../stopLifecycle";

describe("stopLifecycle · phase reducer", () => {
  it("request_stop → stopping", () => {
    expect(reduceStopPhase("idle", "request_stop")).toBe("stopping");
  });

  it("stop_http_fail 回滚 idle（不伪造终态）", () => {
    expect(reduceStopPhase("stopping", "stop_http_fail")).toBe("idle");
  });

  it("confirm_terminal → idle", () => {
    expect(reduceStopPhase("stopping", "confirm_terminal")).toBe("idle");
  });

  it("confirm_timeout / stop_http_ok 保持 stopping", () => {
    expect(reduceStopPhase("stopping", "confirm_timeout")).toBe("stopping");
    expect(reduceStopPhase("stopping", "stop_http_ok")).toBe("stopping");
  });
});

describe("stopLifecycle · event gate", () => {
  it("stopping 丢弃正文 / 工具突变", () => {
    expect(allowsEventWhileStopping("content_delta")).toBe(false);
    expect(allowsEventWhileStopping("reasoning_delta")).toBe(false);
    expect(allowsEventWhileStopping("tool_use_start")).toBe(false);
    expect(allowsEventWhileStopping("tool_use_end")).toBe(false);
  });

  it("stopping 放行 run_* 与终态 / meta", () => {
    expect(allowsEventWhileStopping("run_started")).toBe(true);
    expect(allowsEventWhileStopping("run_cancelled")).toBe(true);
    expect(allowsEventWhileStopping("message_end")).toBe(true);
    expect(allowsEventWhileStopping("error")).toBe(true);
    expect(allowsEventWhileStopping("turn_saved")).toBe(true);
    expect(allowsEventWhileStopping("execution_completed")).toBe(true);
  });

  it("isStopConfirmEvent 仅 message_end / error", () => {
    expect(isStopConfirmEvent("message_end")).toBe(true);
    expect(isStopConfirmEvent("error")).toBe(true);
    expect(isStopConfirmEvent("run_cancelled")).toBe(false);
  });
});

describe("stopLifecycle · copy & busy", () => {
  it("按钮文案：停止中… / 停止", () => {
    expect(stopButtonLabel("stopping")).toBe(STOPPING_LABEL);
    expect(stopButtonLabel("idle")).toBe("停止");
  });

  it("busy = sending ∨ stopping", () => {
    expect(isStopBusy(true, "idle")).toBe(true);
    expect(isStopBusy(false, "stopping")).toBe(true);
    expect(isStopBusy(false, "idle")).toBe(false);
  });

  it("终态 / 失败文案常量", () => {
    expect(STOPPED_LABEL).toBe("已停止");
    expect(STOP_FAILED_MESSAGE).toContain("失败");
    expect(STOP_UNCONFIRMED_MESSAGE).toContain("未确认");
  });
});

describe("stopLifecycle · confirm timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("宽限到期回调；clear 取消；arm 重置", () => {
    const timer = createStopConfirmTimer();
    const onTimeout = vi.fn();

    timer.arm(onTimeout);
    vi.advanceTimersByTime(STOP_CONFIRM_TIMEOUT_MS - 1);
    expect(onTimeout).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onTimeout).toHaveBeenCalledTimes(1);

    onTimeout.mockClear();
    timer.arm(onTimeout);
    timer.clear();
    vi.advanceTimersByTime(STOP_CONFIRM_TIMEOUT_MS + 100);
    expect(onTimeout).not.toHaveBeenCalled();

    timer.arm(onTimeout);
    vi.advanceTimersByTime(STOP_CONFIRM_TIMEOUT_MS / 2);
    timer.arm(onTimeout);
    vi.advanceTimersByTime(STOP_CONFIRM_TIMEOUT_MS / 2);
    expect(onTimeout).not.toHaveBeenCalled();
    vi.advanceTimersByTime(STOP_CONFIRM_TIMEOUT_MS / 2);
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });
});
