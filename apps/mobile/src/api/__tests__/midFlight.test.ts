import type { SSEEvent } from "@agentcore/contract-types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sendMidFlightMessage } from "../midFlight";

vi.mock("@/api/client", () => ({
  apiUrl: (path: string) => `http://test${path}`,
  authHeader: () => ({ Authorization: "Bearer t" }),
  refreshTokens: vi.fn(async () => false),
}));

function sseBody(events: SSEEvent[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  const text = events.map((ev) => `data: ${JSON.stringify(ev)}\n\n`).join("");
  return new ReadableStream({
    start(controller) {
      controller.enqueue(enc.encode(text));
      controller.close();
    },
  });
}

function ev(type: string, payload: Record<string, unknown> = {}): SSEEvent {
  return { type, timestamp: "", payload } as SSEEvent;
}

describe("sendMidFlightMessage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("turn_queued：live 立即呈现，主路空闲后再开 turn2 并续流", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        sseBody([
          ev("turn_queued", { position: 1, queue_depth: 2 }),
          ev("message_start", { message_id: "m2" }),
          ev("message_end", { finish_reason: "end_turn" }),
        ]),
        {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        },
      ),
    );

    let primaryIdle = false;
    const live: string[] = [];
    const turn2: string[] = [];
    let began = 0;
    let resolveIdle!: () => void;
    const idlePromise = new Promise<void>((r) => {
      resolveIdle = r;
    });

    const pending = sendMidFlightMessage("c1", "第二问", {
      onLiveEvent: (e) => live.push(e.type),
      beginTurn2: () => {
        began += 1;
      },
      onTurn2Event: (e) => turn2.push(e.type),
      isPrimaryIdle: () => primaryIdle,
      waitPrimaryIdle: () => idlePromise,
    });

    // Allow turn_queued to land and arm the waiter before releasing primary.
    await vi.waitFor(() => expect(live).toEqual(["turn_queued"]));
    expect(began).toBe(0);
    expect(turn2).toEqual([]);

    primaryIdle = true;
    resolveIdle();
    const result = await pending;

    expect(result).toEqual({ kind: "queued", position: 1, queueDepth: 2 });
    expect(began).toBe(1);
    expect(turn2).toEqual(["message_start", "message_end"]);
  });

  it("user_interjection：即时 delivered，不开 turn2", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        sseBody([ev("user_interjection", { interjection_id: "ij1" })]),
        {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        },
      ),
    );

    const live: string[] = [];
    let began = 0;
    const result = await sendMidFlightMessage("c1", "插一句", {
      onLiveEvent: (e) => live.push(e.type),
      beginTurn2: () => {
        began += 1;
      },
      onTurn2Event: () => {
        throw new Error("should not turn2");
      },
      isPrimaryIdle: () => true,
      waitPrimaryIdle: async () => {},
    });

    expect(result).toEqual({ kind: "delivered" });
    expect(live).toEqual(["user_interjection"]);
    expect(began).toBe(0);
  });

  it("HTTP 202 → error（退役受理）", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ queue_id: "q" }), { status: 202 }),
    );
    const result = await sendMidFlightMessage("c1", "x", {
      onLiveEvent: () => {},
      beginTurn2: () => {},
      onTurn2Event: () => {},
      isPrimaryIdle: () => true,
      waitPrimaryIdle: async () => {},
    });
    expect(result.kind).toBe("error");
  });
});
