import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, BASE_URL } from "../api";
import {
  bootstrapAuth,
  changePassword,
  deleteAccount,
  deleteAvatar,
  listSessions,
  revokeOtherSessions,
  revokeSession,
  updateProfile,
  uploadAvatar,
} from "../auth";

const ME = "/v1/auth/me";
const REFRESH = "/v1/auth/refresh";
const READYZ = "/readyz";

const backendUser = {
  id: "u1",
  username: "dev",
  display_name: "Dev",
  email: null,
  role: "admin",
  created_at: "2024-01-01T00:00:00Z",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Handler = (url: string) => Response;

function mockFetch(handler: Handler): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) =>
      Promise.resolve(handler(String(input))),
    ),
  );
}

beforeEach(() => {
  // Force dev auto-login to a no-op so bootstrap exercises only the cookie and
  // health-probe branches deterministically, regardless of any local .env.local.
  vi.stubEnv("VITE_DEV_USERNAME", "");
  vi.stubEnv("VITE_DEV_PASSWORD", "");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("bootstrapAuth", () => {
  it("returns authenticated when the session cookie is valid", async () => {
    mockFetch((url) => {
      if (url.endsWith(ME)) return json(backendUser);
      throw new Error(`unexpected fetch: ${url}`);
    });

    const result = await bootstrapAuth();

    expect(result.kind).toBe("authenticated");
    if (result.kind === "authenticated") {
      expect(result.user.username).toBe("dev");
    }
  });

  it("returns unauthenticated on 401 when the backend is ready", async () => {
    mockFetch((url) => {
      if (url.endsWith(REFRESH)) return json({ error: "no session" }, 401);
      if (url.endsWith(ME)) return json({ error: "no session" }, 401);
      if (url.endsWith(READYZ))
        return json({ status: "ready", database: true });
      throw new Error(`unexpected fetch: ${url}`);
    });

    const result = await bootstrapAuth();

    expect(result.kind).toBe("unauthenticated");
  });

  it("silently refreshes an expired access token and stays authenticated", async () => {
    // Cold start with an expired access cookie but a still-valid refresh cookie:
    // /auth/me 401s, the silent refresh succeeds, and the retried /auth/me works.
    let meCalls = 0;
    mockFetch((url) => {
      if (url.endsWith(REFRESH)) return json({ status: "ok" });
      if (url.endsWith(ME)) {
        meCalls += 1;
        return meCalls === 1
          ? json({ error: "access token expired" }, 401)
          : json(backendUser);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const result = await bootstrapAuth();

    expect(result.kind).toBe("authenticated");
    if (result.kind === "authenticated") {
      expect(result.user.username).toBe("dev");
    }
    expect(meCalls).toBe(2); // probed, refreshed, then re-probed successfully
  });

  it("returns unavailable on 401 when /readyz reports the database down", async () => {
    mockFetch((url) => {
      if (url.endsWith(REFRESH)) return json({ error: "no session" }, 401);
      if (url.endsWith(ME)) return json({ error: "no session" }, 401);
      if (url.endsWith(READYZ))
        return json({ status: "not_ready", database: false }, 503);
      throw new Error(`unexpected fetch: ${url}`);
    });

    const result = await bootstrapAuth();

    expect(result.kind).toBe("unavailable");
    if (result.kind === "unavailable") {
      expect(result.reason).toContain("数据库");
    }
  });

  it("returns unavailable when /auth/me 500s (server reachable but broken)", async () => {
    mockFetch((url) => {
      if (url.endsWith(ME)) return json({ error: "boom" }, 500);
      if (url.endsWith(READYZ))
        return json({ status: "not_ready", database: false }, 503);
      throw new Error(`unexpected fetch: ${url}`);
    });

    const result = await bootstrapAuth();

    expect(result.kind).toBe("unavailable");
  });

  it("returns unavailable when the backend is unreachable (network error)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    const result = await bootstrapAuth();

    expect(result.kind).toBe("unavailable");
    if (result.kind === "unavailable") {
      expect(result.reason).toContain("无法连接后端");
    }
  });

  it("returns unavailable when bootstrap probes time out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.reject(
          new DOMException("The operation timed out.", "TimeoutError"),
        ),
      ),
    );

    const result = await bootstrapAuth();

    expect(result.kind).toBe("unavailable");
    if (result.kind === "unavailable") {
      expect(result.reason).toContain("无法连接后端");
    }
  });
});

interface Captured {
  url: string;
  method?: string;
  body: unknown;
}

/** Stub fetch, recording each call's url/method/parsed-body and replying with
 *  `response`, so account-ops tests can assert the exact request they sent. */
function captureFetch(response: Response): Captured[] {
  const calls: Captured[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method,
        body:
          typeof init?.body === "string" ? JSON.parse(init.body) : init?.body,
      });
      return Promise.resolve(response.clone());
    }),
  );
  return calls;
}

describe("changePassword", () => {
  it("POSTs current + new password to /auth/change-password", async () => {
    const calls = captureFetch(json({ status: "ok" }));

    await changePassword("old-pw", "brand-new-pw");

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/v1/auth/change-password");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({
      current_password: "old-pw",
      new_password: "brand-new-pw",
    });
  });

  it("rejects with ApiError when the current password is wrong", async () => {
    captureFetch(
      json({ error: { code: "auth", message: "当前密码不正确" } }, 401),
    );

    await expect(changePassword("nope", "brand-new-pw")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("updateProfile", () => {
  it("PATCHes only the provided fields and maps the response", async () => {
    const calls = captureFetch(
      json({ ...backendUser, display_name: "New Name" }),
    );

    const user = await updateProfile({ displayName: "New Name" });

    expect(calls[0].url).toContain("/v1/auth/me");
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ display_name: "New Name" });
    expect(user.displayName).toBe("New Name");
  });

  it("sends an explicit null to clear the email", async () => {
    const calls = captureFetch(json({ ...backendUser, email: null }));

    await updateProfile({ email: null });

    expect(calls[0].body).toEqual({ email: null });
  });

  it("rejects with ApiError when the email is taken", async () => {
    captureFetch(
      json({ error: { code: "validation", message: "该邮箱已被占用" } }, 422),
    );

    await expect(
      updateProfile({ email: "taken@example.com" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("deleteAccount", () => {
  it("DELETEs /auth/me with the confirming password", async () => {
    const calls = captureFetch(json({ status: "ok" }));

    await deleteAccount("my-password");

    expect(calls[0].url).toContain("/v1/auth/me");
    expect(calls[0].method).toBe("DELETE");
    expect(calls[0].body).toEqual({ password: "my-password" });
  });
});

describe("uploadAvatar", () => {
  it("POSTs the raw file body and resolves the returned avatar URL", async () => {
    const calls = captureFetch(
      json({ ...backendUser, avatar_url: "/v1/users/u1/avatar?v=abc" }),
    );
    const file = new File([new Uint8Array([1, 2, 3])], "a.png", {
      type: "image/png",
    });

    const user = await uploadAvatar(file);

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/v1/users/me/avatar");
    expect(calls[0].method).toBe("POST");
    // Raw bytes, not JSON — the File rides through as the body untouched.
    expect(calls[0].body).toBe(file);
    // Relative server URL gets resolved against the API base for <img src>.
    expect(user.avatarUrl).toBe(`${BASE_URL}/v1/users/u1/avatar?v=abc`);
  });

  it("rejects with ApiError when the image is rejected", async () => {
    captureFetch(
      json({ error: { code: "validation", message: "图片无法解码" } }, 422),
    );
    const file = new File([new Uint8Array([0])], "bad.txt", {
      type: "image/png",
    });

    await expect(uploadAvatar(file)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("deleteAvatar", () => {
  it("DELETEs the avatar and clears the mapped URL", async () => {
    const calls = captureFetch(json({ ...backendUser, avatar_url: null }));

    const user = await deleteAvatar();

    expect(calls[0].url).toContain("/v1/users/me/avatar");
    expect(calls[0].method).toBe("DELETE");
    expect(user.avatarUrl).toBeNull();
  });
});

describe("listSessions / revokeSession / revokeOtherSessions", () => {
  const session = {
    id: "fam-1",
    platform: "desktop",
    user_agent: "Mozilla/5.0",
    ip: "127.0.0.1",
    created_at: "2026-07-01T00:00:00Z",
    last_used_at: "2026-07-12T00:00:00Z",
    current: true,
  };

  it("GETs /auth/sessions and returns the list payload", async () => {
    const calls = captureFetch(json({ data: [session], total: 1 }));

    const res = await listSessions();

    expect(calls[0].url).toContain("/v1/auth/sessions");
    expect(calls[0].method).toBeUndefined(); // GET default
    expect(res.total).toBe(1);
    expect(res.data[0].id).toBe("fam-1");
  });

  it("DELETEs /auth/sessions/{family_id}", async () => {
    const calls = captureFetch(json({ status: "ok" }));

    await revokeSession("fam-1");

    expect(calls[0].url).toContain("/v1/auth/sessions/fam-1");
    expect(calls[0].method).toBe("DELETE");
  });

  it("POSTs /auth/sessions/revoke-others", async () => {
    const calls = captureFetch(json({ status: "ok" }));

    await revokeOtherSessions();

    expect(calls[0].url).toContain("/v1/auth/sessions/revoke-others");
    expect(calls[0].method).toBe("POST");
  });
});
