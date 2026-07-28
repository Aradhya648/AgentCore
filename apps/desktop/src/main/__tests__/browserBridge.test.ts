/**
 * Bridge handler 扩展测：health / navigate / command 六动作 / host_unavailable。
 */

import { createServer } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import { describe, expect, it } from "vitest";
import {
  createBridgeAuth,
  handleBridgeRequest,
  type BridgeDispatch,
  type BridgeHostResult,
} from "../browser/bridge-handler";

function mockReqRes(opts: {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: string;
}): {
  req: IncomingMessage;
  res: ServerResponse;
  statusCode: () => number;
  body: () => string;
} {
  let status = 0;
  let responseBody = "";

  const req = {
    method: opts.method,
    url: opts.url,
    headers: opts.headers ?? {},
    async *[Symbol.asyncIterator]() {
      if (opts.body) yield Buffer.from(opts.body);
    },
  } as unknown as IncomingMessage;

  const res = {
    writeHead(code: number) {
      status = code;
    },
    end(data?: string) {
      responseBody = data ?? "";
    },
  } as unknown as ServerResponse;

  return {
    req,
    res,
    statusCode: () => status,
    body: () => responseBody,
  };
}

function okDispatch(
  impl?: (
    pageId: string,
    action: string,
    args: Record<string, unknown>,
  ) => BridgeHostResult,
): BridgeDispatch {
  return async (pageId, action, args) => {
    if (impl) return impl(pageId, action, args);
    return {
      ok: true,
      data: { final_url: "https://example.com/", title: "Example", action },
    };
  };
}

describe("createBridgeAuth", () => {
  it("rejects missing / wrong / expired tokens", () => {
    let now = 1_000;
    const auth = createBridgeAuth(() => now);
    expect(auth.validateToken(null)).toBe(false);
    expect(auth.validateToken("nope")).toBe(false);
    const token = auth.issueToken(100);
    expect(auth.validateToken(token)).toBe(true);
    expect(auth.validateToken("other")).toBe(false);
    now = 1_200;
    expect(auth.validateToken(token)).toBe(false);
  });
});

describe("handleBridgeRequest", () => {
  it("returns 401 without token", async () => {
    const auth = createBridgeAuth();
    auth.issueToken();
    const { req, res, statusCode, body } = mockReqRes({
      method: "GET",
      url: "/health",
    });
    await handleBridgeRequest(req, res, (t) => auth.validateToken(t), okDispatch());
    expect(statusCode()).toBe(401);
    expect(JSON.parse(body())).toMatchObject({
      ok: false,
      error: "unauthorized",
    });
  });

  it("returns 401 with wrong token", async () => {
    const auth = createBridgeAuth();
    auth.issueToken();
    const { req, res, statusCode } = mockReqRes({
      method: "GET",
      url: "/health",
      headers: { authorization: "Bearer wrong-token" },
    });
    await handleBridgeRequest(req, res, (t) => auth.validateToken(t), okDispatch());
    expect(statusCode()).toBe(401);
  });

  it("health ok with valid token", async () => {
    const auth = createBridgeAuth();
    const token = auth.issueToken();
    const { req, res, statusCode, body } = mockReqRes({
      method: "GET",
      url: "/health",
      headers: { authorization: `Bearer ${token}` },
    });
    await handleBridgeRequest(req, res, (t) => auth.validateToken(t), okDispatch());
    expect(statusCode()).toBe(200);
    expect(JSON.parse(body())).toMatchObject({
      ok: true,
      service: "desktop-browser-bridge",
    });
  });

  it("navigate accepts pageId+url with token", async () => {
    const auth = createBridgeAuth();
    const token = auth.issueToken();
    const calls: { pageId: string; action: string; args: Record<string, unknown> }[] =
      [];
    const { req, res, statusCode, body } = mockReqRes({
      method: "POST",
      url: "/navigate",
      headers: { authorization: `Bearer ${token}` },
      body: JSON.stringify({
        pageId: "browser-page:1",
        url: "https://example.com",
      }),
    });
    await handleBridgeRequest(
      req,
      res,
      (t) => auth.validateToken(t),
      okDispatch((pageId, action, args) => {
        calls.push({ pageId, action, args });
        return { ok: true, data: { final_url: args.url as string } };
      }),
    );
    expect(statusCode()).toBe(200);
    expect(JSON.parse(body()).ok).toBe(true);
    expect(calls).toEqual([
      {
        pageId: "browser-page:1",
        action: "navigate",
        args: { url: "https://example.com" },
      },
    ]);
  });

  it("command navigate dispatches workspace:// url unchanged", async () => {
    const auth = createBridgeAuth();
    const token = auth.issueToken();
    let seen: Record<string, unknown> | null = null;
    const { req, res, statusCode, body } = mockReqRes({
      method: "POST",
      url: "/command",
      headers: { authorization: `Bearer ${token}` },
      body: JSON.stringify({
        pageId: "sess-ws",
        action: "navigate",
        args: { url: "workspace://c1/site/index.html" },
      }),
    });
    await handleBridgeRequest(
      req,
      res,
      (t) => auth.validateToken(t),
      okDispatch((_p, _a, args) => {
        seen = args;
        return { ok: true, data: { final_url: args.url as string } };
      }),
    );
    expect(statusCode()).toBe(200);
    expect(JSON.parse(body()).ok).toBe(true);
    expect(seen).toEqual({ url: "workspace://c1/site/index.html" });
  });

  it("command dispatches click/type/scroll/snapshot/screenshot", async () => {
    const auth = createBridgeAuth();
    const token = auth.issueToken();
    const seen: string[] = [];
    for (const action of [
      "click",
      "type",
      "scroll",
      "snapshot",
      "screenshot",
    ] as const) {
      const { req, res, statusCode, body } = mockReqRes({
        method: "POST",
        url: "/command",
        headers: { authorization: `Bearer ${token}` },
        body: JSON.stringify({
          session_id: "sess-1",
          action,
          args: action === "type" ? { ref: "e1", text: "hi" } : { ref: "e1", dy: 100 },
        }),
      });
      await handleBridgeRequest(
        req,
        res,
        (t) => auth.validateToken(t),
        okDispatch((_p, a) => {
          seen.push(a);
          return { ok: true, data: { action: a } };
        }),
      );
      expect(statusCode()).toBe(200);
      expect(JSON.parse(body())).toMatchObject({ ok: true });
    }
    expect(seen).toEqual(["click", "type", "scroll", "snapshot", "screenshot"]);
  });

  it("maps host_unavailable to 503", async () => {
    const auth = createBridgeAuth();
    const token = auth.issueToken();
    const { req, res, statusCode, body } = mockReqRes({
      method: "POST",
      url: "/command",
      headers: { authorization: `Bearer ${token}` },
      body: JSON.stringify({
        pageId: "p1",
        action: "navigate",
        args: { url: "https://x.test" },
      }),
    });
    await handleBridgeRequest(
      req,
      res,
      (t) => auth.validateToken(t),
      async () => ({
        ok: false,
        error: "host_unavailable: no window",
        code: "host_unavailable",
      }),
    );
    expect(statusCode()).toBe(503);
    expect(JSON.parse(body())).toMatchObject({
      ok: false,
      code: "host_unavailable",
    });
  });
});

describe("bridge loopback bind (smoke)", () => {
  it("can listen on 127.0.0.1 only", async () => {
    const server = createServer((_req, res) => {
      res.writeHead(200);
      res.end("ok");
    });
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => resolve());
    });
    const addr = server.address();
    expect(addr && typeof addr !== "string" && addr.address).toBe("127.0.0.1");
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });
});
