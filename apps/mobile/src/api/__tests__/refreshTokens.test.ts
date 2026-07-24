// refreshTokens 三态失败语义（认证与会话.md §五「刷新失败三态」）：只有服务器明确
// 判死会话（401/403）才销毁本地 token 对；网络错 / 5xx / 429 / 畸形响应一律视为
// 暂时性失败，保留 token 供稍后重试——早期「任何失败即 clearTokens」会把一次网络
// 闪断放大成强制重登（token 被销毁，连重试机会都没有）。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearTokens, getTokens, refreshTokens, setTokens } from "../client";

const PAIR = { access_token: "old-access", refresh_token: "old-refresh" };

beforeEach(() => {
  setTokens({ ...PAIR });
});

afterEach(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

describe("refreshTokens failure semantics (three-state)", () => {
  it("rotates and stores the new pair on 200", async () => {
    const fresh = { access_token: "new-access", refresh_token: "new-refresh" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(fresh), { status: 200 })),
    );

    expect(await refreshTokens()).toBe(true);
    expect(getTokens()).toMatchObject(fresh);
  });

  it("clears tokens on 401 (session dead → route guard drops to login)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 401 })),
    );

    expect(await refreshTokens()).toBe(false);
    expect(getTokens()).toBeNull();
  });

  it("clears tokens on 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 403 })),
    );

    expect(await refreshTokens()).toBe(false);
    expect(getTokens()).toBeNull();
  });

  it("keeps tokens on a network error (transient — retry later)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    expect(await refreshTokens()).toBe(false);
    expect(getTokens()).toMatchObject(PAIR);
  });

  it("keeps tokens on 5xx (backend restart window)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("down", { status: 503 })),
    );

    expect(await refreshTokens()).toBe(false);
    expect(getTokens()).toMatchObject(PAIR);
  });

  it("keeps tokens on a malformed 200 body (proxy error page)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>gateway</html>", { status: 200 })),
    );

    expect(await refreshTokens()).toBe(false);
    expect(getTokens()).toMatchObject(PAIR);
  });

  it("single-flights concurrent callers into one round-trip", async () => {
    let release!: (r: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchMock = vi.fn(() => pending);
    vi.stubGlobal("fetch", fetchMock);

    const all = Promise.all([refreshTokens(), refreshTokens()]);
    release(
      new Response(
        JSON.stringify({ access_token: "a2", refresh_token: "r2" }),
        { status: 200 },
      ),
    );

    expect(await all).toEqual([true, true]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
