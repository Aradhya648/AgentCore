// Bearer-token API client for the mobile web/Capacitor shell (前端技术与架构 §七).
//
// Unlike desktop (httpOnly cookies over the app:// origin), the mobile origin
// (capacitor:// / a new web origin) can't rely on SameSite cookies, so the client
// holds the token pair and sends `Authorization: Bearer <access>` on every call
// (backend resolution: api/dependencies.py get_current_user).
//
// STORAGE SEAM (P2 安全存储): the token pair's source of truth is an in-memory cache (so
// authHeader() / route guards stay synchronous), write-through to a pluggable async
// `TokenPersistence` backend. Default = web localStorage (XSS-exposed; the access TTL +
// refresh rotation bound the blast). A NATIVE build injects a Capacitor Secure Storage
// adapter via setTokenPersistence() at startup — so this file never imports Capacitor and
// the swap to OS Keychain/Keystore is one adapter + one boot call, not a rewrite.

import { clientHeaders } from "@/lib/clientBuildInfo";

/** Dev default = same-origin `/api` (Vite proxy → backend). Prod/staging CI bakes an absolute
 *  URL (`https://app…/api`). Explicit `VITE_API_URL` in `.env.local` overrides either path
 *  (e.g. point dev at a remote staging API). */
export const BASE_URL =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? "/api" : "http://localhost:8000");

const ACCESS_KEY = "agentcore.mobile.access";
const REFRESH_KEY = "agentcore.mobile.refresh";

export interface Tokens {
  access_token: string;
  refresh_token: string;
}

/**
 * Where the token pair survives across launches. All ops are async (the native
 * Keychain/Keystore is async); the in-memory cache below serves the sync read path so
 * swapping the backend never ripples async through every caller. Implementations MUST NOT
 * throw — a failed persist degrades to "this launch only", never a crash.
 */
export interface TokenPersistence {
  load(): Promise<Tokens | null>;
  save(tokens: Tokens): Promise<void>;
  clear(): Promise<void>;
}

// Default (web) backend: localStorage, wrapped to the async port so the native adapter is
// a drop-in. Not secure (XSS-exposed); a native build replaces it via setTokenPersistence.
const webTokenPersistence: TokenPersistence = {
  async load() {
    const access_token = localStorage.getItem(ACCESS_KEY);
    const refresh_token = localStorage.getItem(REFRESH_KEY);
    return access_token && refresh_token
      ? { access_token, refresh_token }
      : null;
  },
  async save(tokens) {
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  async clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

let backend: TokenPersistence = webTokenPersistence;
// In-memory source of truth for the sync read path (authHeader / RequireAuth). Seeded once
// by hydrateTokens() at startup, then kept in step with every save/clear.
let cached: Tokens | null = null;

/**
 * Swap the persistence backend. A native build injects a Capacitor Secure Storage adapter
 * here at startup (before hydrateTokens()); web keeps the localStorage default.
 */
export function setTokenPersistence(persistence: TokenPersistence): void {
  backend = persistence;
}

/**
 * Load the persisted pair into the in-memory cache. Call once at startup BEFORE the first
 * sync getTokens() (bootstrapAuth does), so route guards see a restored session. A failed
 * load is treated as "no session" (never throws).
 */
export async function hydrateTokens(): Promise<Tokens | null> {
  try {
    cached = await backend.load();
  } catch {
    cached = null;
  }
  return cached;
}

/** The current token pair from the in-memory cache (sync). Null when logged out or before
 *  hydrateTokens() has run. */
export function getTokens(): Tokens | null {
  return cached;
}

export function setTokens(tokens: Tokens): void {
  cached = tokens;
  // Write-through; persistence is async + best-effort (the session already works off the
  // cache). A rejected save just means "not restored next launch", never a broken login.
  void backend.save(tokens).catch(() => {});
}

export function clearTokens(): void {
  cached = null;
  void backend.clear().catch(() => {});
}

export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

export function authHeader(): Record<string, string> {
  const tokens = getTokens();
  return tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {};
}

// Single in-flight refresh shared by every 401'd caller (apiFetch + the SSE
// stream). The refresh token rotates on first use, so without this each concurrent
// 401 would refresh with the same token: the backend grace window keeps that from
// revoking the family, but deduping here also stops the losing request from
// clobbering the freshly-stored pair (and saves a redundant round-trip). Mirrors
// desktop services/api.ts; reset once settled so the next expiry refreshes anew.
let refreshInFlight: Promise<boolean> | null = null;

/** Rotate the token pair via the bearer refresh endpoint. Returns true on success.
 *  Tokens are cleared ONLY when the server says the session is dead (401/403 —
 *  revoked/expired/reused), so the route guard drops to login. A transient failure
 *  (network error, 5xx, 429, backend restart window) keeps the pair: the refresh
 *  token is still valid and a later retry will succeed — destroying it here would
 *  force a needless re-login. Single-flight: concurrent callers share one
 *  round-trip (see {@link refreshInFlight}). */
export function refreshTokens(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    const tokens = getTokens();
    if (!tokens) return false;
    let res: Response;
    try {
      res = await fetch(apiUrl("/v1/auth/token/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });
    } catch {
      return false; // transient: offline / backend unreachable — keep tokens
    }
    if (res.status === 401 || res.status === 403) {
      clearTokens(); // session truly dead — route guard drops to login
      return false;
    }
    if (!res.ok) return false; // transient 5xx/429 — keep tokens for retry
    try {
      const data = (await res.json()) as Tokens;
      setTokens(data);
      return true;
    } catch {
      return false; // malformed body (proxy error page) — keep tokens
    }
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

/**
 * Bearer-authenticated fetch for JSON endpoints. On 401 it refreshes once and
 * replays; a still-401 leaves tokens cleared so the caller routes back to login.
 * The SSE stream reads the body itself and mirrors this policy (see stream.ts).
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const run = () =>
    fetch(apiUrl(path), {
      ...init,
      headers: { ...clientHeaders(), ...(init.headers ?? {}), ...authHeader() },
    });
  let res = await run();
  if (res.status === 401 && (await refreshTokens())) {
    res = await run();
  }
  return res;
}
