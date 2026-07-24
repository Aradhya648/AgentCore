import { describe, expect, it, vi } from "vitest";

// sidecar-service imports electron (+ fs-service, which also imports electron) at
// module load for IPC wiring it does not run here. Stub it so the transport-
// decoupled SidecarClient can be exercised in isolation.
vi.mock("electron", () => ({
  app: { on: vi.fn(), getAppPath: () => "" },
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
}));

import {
  SidecarClient,
  SidecarRpcError,
  type Transport,
} from "../sidecar-service";

/** A fake line transport: capture outbound lines, inject inbound ones, fake close. */
function fakeTransport() {
  let lineCb: ((line: string) => void) | null = null;
  let closeCb: ((err?: Error) => void) | null = null;
  const sent: Array<Record<string, unknown>> = [];
  const transport: Transport = {
    send: (line) => {
      expect(line.endsWith("\n")).toBe(true); // framed: exactly one line
      sent.push(JSON.parse(line));
    },
    onLine: (cb) => {
      lineCb = cb;
    },
    onClose: (cb) => {
      closeCb = cb;
    },
    close: vi.fn(),
  };
  return {
    transport,
    sent,
    /** Simulate the server sending one message line back. */
    reply: (msg: Record<string, unknown>) => lineCb?.(JSON.stringify(msg)),
    raw: (line: string) => lineCb?.(line),
    die: (err?: Error) => closeCb?.(err),
  };
}

describe("SidecarClient (stdio JSON-RPC)", () => {
  it("pairs a request to its result response by id", async () => {
    const t = fakeTransport();
    const client = new SidecarClient(t.transport);

    const p = client.request("initialize", { workspaceRoot: "/x" });
    expect(t.sent).toEqual([
      {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { workspaceRoot: "/x" },
      },
    ]);

    t.reply({ jsonrpc: "2.0", id: 1, result: { ok: true } });
    expect(await p).toEqual({ ok: true });
  });

  it("rejects with SidecarRpcError carrying the server code + message", async () => {
    const t = fakeTransport();
    const client = new SidecarClient(t.transport);

    const p = client.request("startTurn", { turnId: "t1" });
    t.reply({
      jsonrpc: "2.0",
      id: 1,
      error: { code: -32001, message: "turn cancelled" },
    });

    await expect(p).rejects.toBeInstanceOf(SidecarRpcError);
    await expect(p).rejects.toMatchObject({
      code: -32001,
      message: "turn cancelled",
    });
  });

  it("routes a notification (no id) to onNotification, not to pending requests", async () => {
    const t = fakeTransport();
    const client = new SidecarClient(t.transport);
    const notes: Array<[string, Record<string, unknown>]> = [];
    client.onNotification((method, params) => notes.push([method, params]));

    const p = client.request("startTurn", { turnId: "t1" });
    // A turn/event notification arrives mid-flight — must not settle the request.
    t.reply({
      jsonrpc: "2.0",
      method: "turn/event",
      params: {
        turnId: "t1",
        event: { type: "content_delta", payload: { delta: "hi" } },
      },
    });
    expect(notes).toEqual([
      [
        "turn/event",
        {
          turnId: "t1",
          event: { type: "content_delta", payload: { delta: "hi" } },
        },
      ],
    ]);

    // The request is still pending; its result settles it afterwards.
    t.reply({ jsonrpc: "2.0", id: 1, result: { turnId: "t1", content: "hi" } });
    expect(await p).toEqual({ turnId: "t1", content: "hi" });
  });

  it("assigns monotonically increasing ids across concurrent requests", async () => {
    const t = fakeTransport();
    const client = new SidecarClient(t.transport);

    const p1 = client.request("a", {});
    const p2 = client.request("b", {});
    expect(t.sent.map((m) => m.id)).toEqual([1, 2]);

    // Resolve out of order — each result still finds its own request.
    t.reply({ jsonrpc: "2.0", id: 2, result: "B" });
    t.reply({ jsonrpc: "2.0", id: 1, result: "A" });
    expect(await p1).toBe("A");
    expect(await p2).toBe("B");
  });

  it("rejects all in-flight requests when the process dies", async () => {
    const t = fakeTransport();
    const client = new SidecarClient(t.transport);
    let closedErr: Error | null = null;
    client.onClosed((err) => {
      closedErr = err;
    });

    const p = client.request("startTurn", { turnId: "t1" });
    t.die(new Error("sidecar 进程退出（code 1）"));

    await expect(p).rejects.toThrow("sidecar 进程退出（code 1）");
    expect(closedErr).toBeInstanceOf(Error);

    // Any further request fails fast (no hang waiting on a dead pipe).
    await expect(client.request("x", {})).rejects.toThrow();
  });

  it("ignores malformed inbound lines without crashing", async () => {
    const t = fakeTransport();
    const client = new SidecarClient(t.transport);
    const p = client.request("a", {});

    t.raw("} not json {"); // garbage line — dropped, loop survives
    t.reply({ jsonrpc: "2.0", id: 1, result: "ok" });
    expect(await p).toBe("ok");
  });
});
