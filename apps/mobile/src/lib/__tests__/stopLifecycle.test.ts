import { describe, expect, it } from "vitest";

import {
  STOPPED_LABEL,
  STOPPING_LABEL,
  STOP_FAILED_MESSAGE,
  allowsEventWhileStopping,
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

  it("stop_http_ok 保持 stopping", () => {
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

  it("终态 / 失败文案常量（无停止未确认 / 重试停止路径）", () => {
    expect(STOPPED_LABEL).toBe("已停止");
    expect(STOP_FAILED_MESSAGE).toContain("失败");
  });
});
