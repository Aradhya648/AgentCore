import { describe, expect, it } from "vitest";
import { SidecarEventBuffer } from "../sidecar-event-buffer";

function ev(
  type: string,
  payload: unknown = {},
  timestamp = "2026-01-01T00:00:00.000Z",
) {
  return { type, timestamp, payload };
}

describe("SidecarEventBuffer (mirror EventSink._history + D2 deviation)", () => {
  it("coalesces turn-level deltas and skips empty deltas", () => {
    const buf = new SidecarEventBuffer();
    buf.record(ev("content_delta", { delta: "hel" }));
    buf.record(ev("content_delta", { delta: "lo" }));
    buf.record(ev("content_delta", { delta: "" }));
    buf.record(ev("reasoning_delta", { delta: "think" }));
    const snap = buf.snapshot();
    expect(snap).toHaveLength(2);
    expect(snap[0]).toMatchObject({
      type: "content_delta",
      payload: { delta: "hello" },
    });
    expect(snap[1]).toMatchObject({
      type: "reasoning_delta",
      payload: { delta: "think" },
    });
  });

  it("coalesces run-level deltas only when run_id matches", () => {
    const buf = new SidecarEventBuffer();
    buf.record(ev("run_output_delta", { run_id: "a", delta: "1" }));
    buf.record(ev("run_output_delta", { run_id: "a", delta: "2" }));
    buf.record(ev("run_output_delta", { run_id: "b", delta: "x" }));
    const snap = buf.snapshot();
    expect(snap).toHaveLength(2);
    expect(snap[0].payload).toMatchObject({ run_id: "a", delta: "12" });
    expect(snap[1].payload).toMatchObject({ run_id: "b", delta: "x" });
  });

  it("skips progress / workspace_op / handoff; keeps content_reset raw", () => {
    const buf = new SidecarEventBuffer();
    buf.record(ev("tool_progress", { pct: 1 }));
    buf.record(ev("workspace_op_required", { op: "x" }));
    buf.record(ev("handoff_job_started", {}));
    buf.record(ev("content_reset", {}));
    buf.record(ev("approval_required", { id: "a1" }));
    const snap = buf.snapshot();
    expect(snap.map((e) => e.type)).toEqual([
      "content_reset",
      "approval_required",
    ]);
  });

  it("caps tool_use_end result at 8000 chars", () => {
    const buf = new SidecarEventBuffer();
    const big = "x".repeat(9000);
    buf.record(ev("tool_use_end", { result: big, tool: "t" }));
    const result = (buf.snapshot()[0].payload as { result: string }).result;
    expect(result.length).toBe(8001);
    expect(result.endsWith("…")).toBe(true);
  });

  it("keeps message_end / error (D2 deviation) and seals against later deltas", () => {
    const buf = new SidecarEventBuffer();
    buf.record(ev("content_delta", { delta: "hi" }));
    buf.record(ev("message_end", { finish_reason: "stop" }));
    buf.record(ev("content_delta", { delta: "leak" }));
    expect(buf.hasTerminal()).toBe(true);
    const snap = buf.snapshot();
    expect(snap.map((e) => e.type)).toEqual(["content_delta", "message_end"]);
    expect((snap[0].payload as { delta: string }).delta).toBe("hi");
  });

  it("error also seals the buffer", () => {
    const buf = new SidecarEventBuffer();
    buf.record(ev("error", { code: "x", message: "boom" }));
    buf.record(ev("content_delta", { delta: "nope" }));
    expect(buf.snapshot().map((e) => e.type)).toEqual(["error"]);
  });
});
