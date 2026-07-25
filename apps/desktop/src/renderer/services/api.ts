import { clientHeaders } from "@/lib/clientBuildInfo";
import { logEvent } from "@/lib/log";
import type { AuthRefreshResult } from "../../shared/outbox-contract";

export type { AuthRefreshResult };

export const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

/** Bounded wait for auth-gate probes so a hung backend never strands the UI on "加载中…". */
export const BOOTSTRAP_TIMEOUT_MS = 10_000;

/**
 * `fetch` with an abort deadline. Timeouts surface as {@link NetworkError} so
 * bootstrap/outage paths treat a stuck server like any other transport failure.
 */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs = BOOTSTRAP_TIMEOUT_MS,
): Promise<Response> {
  try {
    return await fetch(input, {
      ...init,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "TimeoutError") {
      throw new NetworkError(cause);
    }
    if (cause instanceof NetworkError) throw cause;
    throw new NetworkError(cause);
  }
}

export class ApiError extends Error {
  /** Backend error code from the `{error:{code,message}}` contract (main.py's
   * global handler over the AgentCoreError hierarchy), when the body parses. Lets
   * callers branch on the cause without string-matching the message. */
  readonly code?: string;
  /** The backend's user-facing message from the same contract — often a ready-to
   * -show zh string. Distinct from {@link body}, which is the raw (possibly
   * non-JSON) response text kept for logging. */
  readonly serverMessage?: string;
  /** Seconds to wait before retrying, from a `Retry-After` header (e.g. 429s). */
  readonly retryAfter?: number;

  constructor(
    public status: number,
    public body: string,
    headers?: Headers,
  ) {
    super(`API ${status}: ${body}`);
    this.name = "ApiError";
    // Every backend error is `{error:{code,message}}`; parse it so the shared
    // error map (lib/errors) can phrase REST failures the same way it phrases
    // SSE-turn failures. A non-JSON body (e.g. a proxy error page) just leaves
    // code/serverMessage undefined and callers fall back to status phrasing.
    try {
      const parsed = JSON.parse(body) as {
        error?: { code?: string; message?: string };
        detail?: { code?: string; message?: string } | string;
      };
      this.code = parsed.error?.code;
      this.serverMessage = parsed.error?.message;
      // FastAPI HTTPException(detail={code, message}) — P1 interaction 410/409.
      if (!this.code && typeof parsed.detail === "object" && parsed.detail) {
        this.code = parsed.detail.code;
        this.serverMessage = parsed.detail.message ?? this.serverMessage;
      }
    } catch {
      /* non-JSON body — keep the raw text only */
    }
    const ra = Number(headers?.get("Retry-After"));
    this.retryAfter = Number.isFinite(ra) && ra > 0 ? ra : undefined;
  }
}

/**
 * The request never completed at the transport layer (server unreachable, DNS
 * failure, offline, blocked CORS preflight). Distinct from {@link ApiError},
 * which means the server *did* respond, just with a non-2xx status. Callers use
 * this split to tell a backend outage apart from a 401/4xx.
 */
export class NetworkError extends Error {
  constructor(public readonly detail?: unknown) {
    super("network request failed");
    this.name = "NetworkError";
  }
}

// Invoked when a request stays unauthorized even after a refresh attempt, so the
// app can drop to the login screen. Registered by the auth gate to avoid a
// store import cycle (the auth store must not depend on this module).
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** Drop to the login screen via the registered handler (no-op if unset). */
let lastSessionKickAt = 0;

/**
 * Mid-session kick to login. Debounced log (`auth.session_kicked`) so a 401 burst
 * does not spam desktop.jsonl — cold-start still uses `auth.bootstrap`.
 */
export function notifyUnauthorized(fields?: Record<string, unknown>): void {
  const now = Date.now();
  if (now - lastSessionKickAt > 5_000) {
    lastSessionKickAt = now;
    logEvent("warn", "auth.session_kicked", fields);
  }
  onUnauthorized?.();
}

let csrfToken: string | null = null;

function captureCsrf(response: Response): void {
  const token = response.headers.get("X-CSRF-Token");
  if (token) csrfToken = token;
}

export function clearCsrfToken(): void {
  csrfToken = null;
}

/** Attach to raw ``fetch`` calls that bypass ``api.*`` (SSE, uploads, …). */
export function getCsrfHeaders(method = "POST"): Record<string, string> {
  return csrfHeaders(method);
}

function csrfHeaders(method: string): Record<string, string> {
  if (!csrfToken) return {};
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return {};
  return { "X-CSRF-Token": csrfToken };
}

// Invoked when a request looks like a backend outage (transport failure or 5xx)
// so the app can confirm via /readyz and switch to a retry screen mid-session,
// the same way it does on startup. Registered by the auth gate.
let onServiceUnavailable: (() => void) | null = null;

export function setServiceUnavailableHandler(
  handler: (() => void) | null,
): void {
  onServiceUnavailable = handler;
}

/** Invoked after a successful silent token refresh (for AgentTown session sync). */
let onSessionRenewed: (() => void) | null = null;

export function setSessionRenewedHandler(handler: (() => void) | null): void {
  onSessionRenewed = handler;
}

const isAuthPath = (path: string): boolean => path.startsWith("/v1/auth/");

// A single in-flight refresh shared by every 401'd caller. The refresh token
// rotates on first use, so concurrent requests must NOT each POST /refresh: the
// 2nd would present an already-rotated token, the backend's reuse detection would
// revoke the whole family, and the user would be logged out mid-session
// (认证与会话.md §五/§七). Collapsing the burst into one promise guarantees a
// single rotation; the backend grace window is the cross-window backstop.
let refreshInFlight: Promise<AuthRefreshResult> | null = null;

/**
 * Attempt a single token refresh; three-state so transient outages never look
 * like session death.
 *
 * Single-flight: concurrent callers share one /refresh round-trip (see
 * {@link refreshInFlight}). Exported so non-`api` callers (the raw-fetch SSE
 * stream, the workspace/handoff/realtime channels) reuse the exact same
 * refresh-once policy *and* the same dedup, instead of each racing a rotation.
 */
export function tryRefresh(): Promise<AuthRefreshResult> {
  // D4: when Electron main owns refresh single-flight, delegate so writebacker
  // and renderer never rotate the same refresh family concurrently.
  const outboxRefresh =
    typeof globalThis !== "undefined" &&
    "window" in globalThis &&
    (
      globalThis as {
        window?: {
          outboxApi?: { authRefresh?: () => Promise<AuthRefreshResult> };
        };
      }
    ).window?.outboxApi?.authRefresh;
  if (outboxRefresh) {
    return outboxRefresh().then((outcome) => {
      if (outcome === "renewed") onSessionRenewed?.();
      return outcome;
    });
  }
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async (): Promise<AuthRefreshResult> => {
    try {
      const res = await fetchWithTimeout(`${BASE_URL}/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      captureCsrf(res);
      if (res.ok) {
        onSessionRenewed?.();
        return "renewed";
      }
      if (res.status === 401 || res.status === 403) {
        logEvent("warn", "auth.refresh", {
          result: "auth_dead",
          via: "cookie",
          status: res.status,
          message: await peekAuthErrorMessage(res),
        });
        return "auth_dead";
      }
      return "transient";
    } catch {
      return "transient";
    }
  })().finally(() => {
    // Let the next expiry start a fresh refresh once this one has settled.
    refreshInFlight = null;
  });
  return refreshInFlight;
}

/** Best-effort server error text for product logs (never tokens). */
async function peekAuthErrorMessage(
  res: Response,
): Promise<string | undefined> {
  try {
    const source = typeof res.clone === "function" ? res.clone() : res;
    const body: unknown = await source.json();
    if (!body || typeof body !== "object") return undefined;
    const err = (body as { error?: unknown }).error;
    const raw =
      typeof err === "string"
        ? err
        : err && typeof err === "object"
          ? (err as { message?: unknown }).message
          : (body as { message?: unknown }).message;
    return typeof raw === "string" ? raw.slice(0, 120) : undefined;
  } catch {
    return undefined;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = false,
  timeoutMs?: number,
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const method = (options.method ?? "GET").toUpperCase();
  const fetchInit: RequestInit = {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...clientHeaders(),
      ...csrfHeaders(method),
      ...options.headers,
    },
    ...options,
  };
  let response: Response;
  try {
    response =
      timeoutMs != null
        ? await fetchWithTimeout(url, fetchInit, timeoutMs)
        : await fetch(url, fetchInit);
  } catch (cause) {
    // fetch only rejects on transport failure (the server never answered), so
    // surface a typed NetworkError the bootstrap can treat as an outage.
    if (!isAuthPath(path)) onServiceUnavailable?.();
    throw new NetworkError(cause);
  }

  captureCsrf(response);

  if (response.ok) {
    return response.json();
  }

  // Access token likely expired: refresh once and replay. Auth endpoints opt
  // out so login failures and the refresh call itself never recurse.
  // Three-state: only `auth_dead` drops to login; `transient` uses the outage gate.
  if (response.status === 401 && !isAuthPath(path)) {
    if (!retry) {
      const outcome = await tryRefresh();
      if (outcome === "renewed") {
        return request<T>(path, options, true);
      }
      if (outcome === "transient") {
        onServiceUnavailable?.();
      } else {
        notifyUnauthorized({ reason: "refresh_auth_dead", path });
      }
    } else {
      notifyUnauthorized({ reason: "replay_still_401", path });
    }
  }

  // A 5xx means the server is reachable but broken; flag a possible outage so
  // the gate can confirm via /readyz and drop to the retry screen. Auth paths
  // opt out — the bootstrap flow already diagnoses those explicitly.
  if (response.status >= 500 && !isAuthPath(path)) {
    onServiceUnavailable?.();
  }

  throw new ApiError(response.status, await response.text(), response.headers);
}

/** Auth-gate bootstrap REST calls — same as {@link request} but bounded in time. */
export function bootstrapRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return request<T>(path, options, false, BOOTSTRAP_TIMEOUT_MS);
}

/**
 * Like {@link request}, but also returns the HTTP status (for idempotent
 * create-or-reuse endpoints that distinguish 200 vs 201).
 */
async function requestWithStatus<T>(
  path: string,
  options: RequestInit = {},
  retry = false,
): Promise<{ data: T; status: number }> {
  const url = `${BASE_URL}${path}`;
  const method = (options.method ?? "GET").toUpperCase();
  const fetchInit: RequestInit = {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...clientHeaders(),
      ...csrfHeaders(method),
      ...options.headers,
    },
    ...options,
  };
  let response: Response;
  try {
    response = await fetch(url, fetchInit);
  } catch (cause) {
    if (!isAuthPath(path)) onServiceUnavailable?.();
    throw new NetworkError(cause);
  }

  captureCsrf(response);

  if (response.ok) {
    return { data: (await response.json()) as T, status: response.status };
  }

  if (response.status === 401 && !isAuthPath(path)) {
    if (!retry) {
      const outcome = await tryRefresh();
      if (outcome === "renewed") {
        return requestWithStatus<T>(path, options, true);
      }
      if (outcome === "transient") {
        onServiceUnavailable?.();
      } else {
        notifyUnauthorized({ reason: "refresh_auth_dead", path });
      }
    } else {
      notifyUnauthorized({ reason: "replay_still_401", path });
    }
  }

  if (response.status >= 500 && !isAuthPath(path)) {
    onServiceUnavailable?.();
  }

  throw new ApiError(response.status, await response.text(), response.headers);
}

export const api = {
  get: <T>(path: string) => request<T>(path),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  /** POST that surfaces status (200 reuse vs 201 create). */
  postWithStatus: <T>(path: string, body?: unknown) =>
    requestWithStatus<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    }),
};
