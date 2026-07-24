// AutonomyPolicy REST for the mobile client (设置·自主度).
//
// Cloud-only rounds: no sidecar local cache — read/write the user preference
// directly. Schema matches desktop GET/PUT /v1/users/me/autonomy.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type AutonomyPolicy = Schemas["AutonomyPolicy"];
export type AutonomyView = Schemas["AutonomyView"];

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    return body.error?.message ?? `${fallback} (${res.status})`;
  } catch {
    return `${fallback} (${res.status})`;
  }
}

export async function getAutonomy(): Promise<AutonomyView> {
  const res = await apiFetch("/v1/users/me/autonomy");
  if (!res.ok) throw new Error(await errorMessage(res, "加载自主度设置失败"));
  return (await res.json()) as AutonomyView;
}

export async function setAutonomy(
  policy: AutonomyPolicy,
): Promise<AutonomyView> {
  const res = await apiFetch("/v1/users/me/autonomy", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ policy }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "设置失败"));
  return (await res.json()) as AutonomyView;
}
