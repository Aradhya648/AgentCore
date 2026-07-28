import type { SidecarEventPush } from "@shared/sidecar-contract";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  claimSidecarTurnSink,
  installSidecarEventPump,
  resetSidecarEventPumpForTests,
} from "../sidecarEventPump";

type EventCb = (push: SidecarEventPush) => void;

let onEventCb: EventCb | null;
let onEventMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetSidecarEventPumpForTests();
  onEventCb = null;
  onEventMock = vi.fn((cb: EventCb) => {
    onEventCb = cb;
    return () => {
      if (onEventCb === cb) onEventCb = null;
    };
  });
  vi.stubGlobal("window", {
    sidecarApi: { onEvent: onEventMock },
  });
});

function push(conversationId: string, turnId: string, delta: string): void {
  onEventCb?.({
    conversationId,
    turnId,
    event: {
      type: "content_delta",
      timestamp: "t",
      payload: { delta },
    },
  });
}

describe("sidecarEventPump (per-turn single sink)", () => {
  it("installs sidecar:event only once across repeated install/claim", () => {
    installSidecarEventPump();
    installSidecarEventPump();
    claimSidecarTurnSink("c1", "t1", () => {});
    claimSidecarTurnSink("c2", "t2", () => {});
    expect(onEventMock).toHaveBeenCalledTimes(1);
  });

  it("routes a content_delta to the sole claimed sink", () => {
    const sink = vi.fn();
    claimSidecarTurnSink("c1", "t1", sink);
    push("c1", "t1", "hello");
    push("c1", "other", "skip");
    push("other", "t1", "skip");
    expect(sink).toHaveBeenCalledTimes(1);
    expect(sink.mock.calls[0][0].event.payload).toEqual({ delta: "hello" });
  });

  it("new claim revokes prior owner — same delta reaches only the new sink", () => {
    const first = vi.fn();
    const second = vi.fn();
    const revoked = vi.fn();
    claimSidecarTurnSink("c1", "t1", first, { onRevoked: revoked });
    claimSidecarTurnSink("c1", "t1", second);
    expect(revoked).toHaveBeenCalledTimes(1);
    push("c1", "t1", "x");
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("null turnId accepts any turn until setTurnId narrows", () => {
    const sink = vi.fn();
    const claim = claimSidecarTurnSink("c1", null, sink);
    push("c1", "t-a", "a");
    push("c1", "t-b", "b");
    expect(sink).toHaveBeenCalledTimes(2);
    claim.setTurnId("t-b");
    push("c1", "t-a", "skip");
    push("c1", "t-b", "c");
    expect(sink).toHaveBeenCalledTimes(3);
    expect(sink.mock.calls[2][0].event.payload).toEqual({ delta: "c" });
  });

  it("release stops delivery; stale release after takeover is a no-op", () => {
    const a = vi.fn();
    const b = vi.fn();
    const claimA = claimSidecarTurnSink("c1", "t1", a);
    const claimB = claimSidecarTurnSink("c1", "t1", b);
    claimA.release();
    push("c1", "t1", "still-b");
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalledTimes(1);
    claimB.release();
    push("c1", "t1", "gone");
    expect(b).toHaveBeenCalledTimes(1);
  });
});
