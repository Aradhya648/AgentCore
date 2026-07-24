// Login-device sessions for the mobile bearer client (账户设置 · 登录设备).
//
// One row per refresh-token family. REST DTOs track OpenAPI via
// @agentcore/contract-rest-types.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type SessionSummary = Schemas["SessionSummary"];
export type SessionListResponse = Schemas["SessionListResponse"];

/** List the caller's active login devices. */
export async function listSessions(): Promise<SessionListResponse> {
  const res = await apiFetch("/v1/auth/sessions");
  if (!res.ok) throw new Error(await errorMessage(res, "加载登录设备失败"));
  return (await res.json()) as SessionListResponse;
}

/** Log out one device (revoke its refresh-token family). Current session OK. */
export async function revokeSession(familyId: string): Promise<void> {
  const res = await apiFetch(
    `/v1/auth/sessions/${encodeURIComponent(familyId)}`,
    {
      method: "DELETE",
    },
  );
  if (!res.ok) throw new Error(await errorMessage(res, "退出设备失败"));
}

/** Log out every other device; keep the caller's current family. */
export async function revokeOtherSessions(): Promise<void> {
  const res = await apiFetch("/v1/auth/sessions/revoke-others", {
    method: "POST",
  });
  if (!res.ok) throw new Error(await errorMessage(res, "退出其他设备失败"));
}

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    return body.error?.message ?? `${fallback} (${res.status})`;
  } catch {
    return `${fallback} (${res.status})`;
  }
}
