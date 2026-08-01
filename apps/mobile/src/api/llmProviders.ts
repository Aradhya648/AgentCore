// BYOK 多服务商配置 REST for the mobile client (设置·模型配置).
//
// Account default combination lives on `/v1/users/me/llm-model-profiles`
// (`default_model_profile_id`); this module only covers provider CRUD + deployment caps.
import { apiFetch } from "@/api/client";

/** Settings view of one BYOK provider — never the plaintext key. */
export interface LlmProviderView {
  id: string;
  label: string;
  base_url: string;
  default_model: string;
  /** Connectivity result: unchecked | active | error. */
  status: string;
  masked_key?: string | null;
  message?: string | null;
  supports_tools?: boolean | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** The full 设置·模型配置 provider state + deployment caps. */
export interface LlmProvidersResponse {
  providers: LlmProviderView[];
  /** Deployment billing mode (byok | platform). */
  billing_mode: string;
  /** Whether platform models are available on this deployment. */
  platform_available: boolean;
  /** Operator platform model id when platform is available. */
  platform_model?: string | null;
  /** Echo of account default combination id (authoritative list is llm-model-profiles). */
  default_model_profile_id?: string | null;
}

/** Add one provider (first provider auto-becomes the chat default). `api_key` required. */
export interface CreateLlmProviderInput {
  api_key: string;
  base_url?: string | null;
  default_model?: string | null;
  label?: string;
}

/** Partial update — omit `api_key` to keep the stored ciphertext (edit endpoint/model). */
export interface UpdateLlmProviderInput {
  api_key?: string | null;
  base_url?: string | null;
  default_model?: string | null;
  label?: string | null;
}

/** Same phrasing as desktop LoginPage — admin sessions cannot use product APIs. */
export const ADMIN_PRODUCT_FORBIDDEN_MESSAGE =
  "此账号为管理员账号，请使用管理后台登录";

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as {
      error?: { code?: string; message?: string };
    };
    if (body.error?.code === "ADMIN_PRODUCT_FORBIDDEN") {
      return ADMIN_PRODUCT_FORBIDDEN_MESSAGE;
    }
    return body.error?.message ?? `${fallback} (${res.status})`;
  } catch {
    return `${fallback} (${res.status})`;
  }
}

async function readProviders(
  res: Response,
  fallback: string,
): Promise<LlmProvidersResponse> {
  if (!res.ok) throw new Error(await errorMessage(res, fallback));
  return (await res.json()) as LlmProvidersResponse;
}

async function readProvider(
  res: Response,
  fallback: string,
): Promise<LlmProviderView> {
  if (!res.ok) throw new Error(await errorMessage(res, fallback));
  return (await res.json()) as LlmProviderView;
}

/** List the account's providers + deployment capabilities. */
export async function listLlmProviders(): Promise<LlmProvidersResponse> {
  return readProviders(
    await apiFetch("/v1/users/me/llm-providers"),
    "加载失败",
  );
}

/** Add one OpenAI-compatible provider (returns the created provider view). */
export async function createLlmProvider(
  input: CreateLlmProviderInput,
): Promise<LlmProviderView> {
  const res = await apiFetch("/v1/users/me/llm-providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readProvider(res, "保存失败");
}

/** Update one provider (endpoint / model / label; key optional to keep). */
export async function updateLlmProvider(
  id: string,
  input: UpdateLlmProviderInput,
): Promise<LlmProviderView> {
  const res = await apiFetch(`/v1/users/me/llm-providers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readProvider(res, "保存失败");
}

/** Remove one provider. */
export async function deleteLlmProvider(id: string): Promise<void> {
  const res = await apiFetch(`/v1/users/me/llm-providers/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await errorMessage(res, "删除失败"));
}

/** Probe one provider's endpoint and persist 'active' / 'error' + supports_tools. */
export async function testLlmProvider(id: string): Promise<LlmProviderView> {
  const res = await apiFetch(`/v1/users/me/llm-providers/${id}/test`, {
    method: "POST",
  });
  return readProvider(res, "测试失败");
}
