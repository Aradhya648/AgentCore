// Auth flow for the mobile bearer client (M3). Register uses the platform-neutral
// /v1/auth/register; session uses bearer /v1/auth/token*. REST DTOs track OpenAPI
// via @agentcore/contract-rest-types.
import {
  apiFetch,
  apiUrl,
  clearTokens,
  getTokens,
  hydrateTokens,
  setTokens,
} from "@/api/client";
import { disablePush, enablePush } from "@/api/push";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type User = Schemas["UserResponse"];
type TokenResponse = Schemas["TokenResponse"];

// /readyz has no response_model — keep a local shape (mirrors desktop auth.ts).
interface ReadinessResponse {
  status: "ready" | "not_ready";
  database: boolean;
}

export interface RegisterInput {
  username: string;
  password: string;
  displayName?: string;
}

/** Create an account (no session). Caller should follow with {@link login}. */
export async function register(input: RegisterInput): Promise<User> {
  const res = await fetch(apiUrl("/v1/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: input.username,
      password: input.password,
      display_name: input.displayName || undefined,
    } satisfies Schemas["RegisterRequest"]),
  });
  if (!res.ok) {
    throw new Error(await errorMessage(res, "注册失败"));
  }
  return (await res.json()) as User;
}

export async function login(username: string, password: string): Promise<User> {
  const res = await fetch(apiUrl("/v1/auth/token"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      password,
      persist_session: true,
    } satisfies Schemas["LoginRequest"]),
  });
  if (!res.ok) {
    throw new Error(await errorMessage(res, "登录失败"));
  }
  const data = (await res.json()) as TokenResponse;
  setTokens({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
  });
  void enablePush();
  return data.user ?? (await me());
}

export async function me(): Promise<User> {
  const res = await apiFetch("/v1/auth/me");
  if (!res.ok) throw new Error("未认证");
  return (await res.json()) as User;
}

export async function logout(): Promise<void> {
  const tokens = getTokens();
  if (tokens) {
    await disablePush();
    await fetch(apiUrl("/v1/auth/token/revoke"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        refresh_token: tokens.refresh_token,
      } satisfies Schemas["TokenRevokeRequest"]),
    }).catch(() => {});
  }
  clearTokens();
}

export type BootstrapResult =
  | { kind: "authenticated" }
  | { kind: "unauthenticated" }
  | { kind: "unavailable"; reason: string };

/** Probe backend readiness via /readyz. */
export async function diagnoseOutage(): Promise<string | null> {
  try {
    const res = await fetch(apiUrl("/readyz"));
    const ready = (await res.json()) as ReadinessResponse;
    if (res.ok && ready.database) return null;
    if (!ready.database) return "数据库不可用：请确认数据库已启动后重试。";
    return "后端服务异常：请稍后重试。";
  } catch {
    return "无法连接后端：请确认后端服务已启动后重试。";
  }
}

let bootstrapOnce: Promise<BootstrapResult> | null = null;

export function bootstrapAuth(force = false): Promise<BootstrapResult> {
  if (force) bootstrapOnce = null;
  if (!bootstrapOnce) bootstrapOnce = runBootstrap();
  return bootstrapOnce;
}

async function runBootstrap(): Promise<BootstrapResult> {
  await hydrateTokens();
  if (getTokens()) {
    try {
      const res = await apiFetch("/v1/auth/me");
      if (res.ok) {
        void enablePush();
        return { kind: "authenticated" };
      }
      if (res.status !== 401) {
        return { kind: "unavailable", reason: await outageReason() };
      }
      clearTokens();
    } catch {
      return { kind: "unavailable", reason: await outageReason() };
    }
  }
  if (await devAutoLogin()) return { kind: "authenticated" };

  const reason = await diagnoseOutage();
  return reason ? { kind: "unavailable", reason } : { kind: "unauthenticated" };
}

async function outageReason(): Promise<string> {
  return (await diagnoseOutage()) ?? "后端服务异常：请稍后重试。";
}

async function devAutoLogin(): Promise<boolean> {
  if (!import.meta.env.DEV) return false;
  const username = import.meta.env.VITE_DEV_USERNAME;
  const password = import.meta.env.VITE_DEV_PASSWORD;
  if (!username || !password) return false;
  try {
    await login(username, password);
    return true;
  } catch (err) {
    console.warn("[dev] auto-login failed: check VITE_DEV_* / backend", err);
    return false;
  }
}

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    return body.error?.message ?? `${fallback} (${res.status})`;
  } catch {
    return `${fallback} (${res.status})`;
  }
}
