// HTTP client for the admin console. The admin app is a *separate origin* from
// the API (独立 web 控制台), so every request is credentialed (cookies ride along
// cross-origin via SameSite=Lax + CORS allow-credentials) — see README for the
// CORS/cookie setup. Mirrors the desktop renderer's api.ts: typed ApiError over
// the backend's `{error:{code,message}}` contract, a NetworkError for transport
// failures, and a single refresh-then-replay on 401.

import { clientHeaders } from "@/lib/clientBuildInfo";

export const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  /** Backend error code from the `{error:{code,message}}` contract, when present. */
  readonly code?: string;
  /** Backend user-facing message (often a ready-to-show zh string). */
  readonly serverMessage?: string;

  constructor(
    public status: number,
    public body: string,
  ) {
    super(`API ${status}: ${body}`);
    this.name = "ApiError";
    try {
      const parsed = JSON.parse(body) as {
        error?: { code?: string; message?: string };
      };
      this.code = parsed.error?.code;
      this.serverMessage = parsed.error?.message;
    } catch {
      /* non-JSON body — keep the raw text only */
    }
  }
}

/** The request never completed at the transport layer (server down / CORS). */
export class NetworkError extends Error {
  constructor(public readonly detail?: unknown) {
    super("network request failed");
    this.name = "NetworkError";
  }
}

// Invoked when a request stays 401 even after a refresh, so the app drops to the
// login screen. Registered by the auth bootstrap to avoid a store import cycle.
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

let csrfToken: string | null = null;

function captureCsrf(response: Response): void {
  const token = response.headers.get("X-CSRF-Token");
  if (token) csrfToken = token;
}

export function clearCsrfToken(): void {
  csrfToken = null;
}

function csrfHeaders(method: string): Record<string, string> {
  if (!csrfToken) return {};
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return {};
  return { "X-CSRF-Token": csrfToken };
}

// The credential/session endpoints whose 401 is *expected* (bad password, no
// session yet) — they must NOT trigger the refresh-replay-then-logout flow.
const isAuthPath = (path: string): boolean => path.startsWith("/v1/auth/");

/**
 * Silent cookie refresh. Exported for cold-start bootstrap: `/v1/auth/me` is an
 * auth path so {@link request} will not auto-refresh on its 401 — bootstrap must
 * call this explicitly, then retry `/me`. Regular API 401s still go through the
 * in-request refresh below (non-auth paths only, to avoid refresh recursion).
 */
export async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    captureCsrf(res);
    return res.ok;
  } catch {
    return false;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = false,
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...clientHeaders(),
        ...csrfHeaders(method),
        ...options.headers,
      },
      ...options,
    });
  } catch (cause) {
    throw new NetworkError(cause);
  }

  captureCsrf(response);

  if (response.ok) {
    // 204/empty bodies: don't choke on an absent JSON payload.
    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  if (response.status === 401 && !isAuthPath(path)) {
    if (!retry && (await tryRefresh())) {
      return request<T>(path, options, true);
    }
    onUnauthorized?.();
  }

  throw new ApiError(response.status, await response.text());
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** A user-facing zh message for any thrown api error (backend msg → status → net). */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.serverMessage) return err.serverMessage;
    if (err.status === 403) return "需要管理员权限";
    if (err.status === 401) return "登录已失效，请重新登录";
    return `请求失败（${err.status}）`;
  }
  if (err instanceof NetworkError) return "无法连接后端，请确认服务已启动";
  return "发生未知错误";
}
