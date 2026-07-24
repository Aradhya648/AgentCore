import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

/**
 * BYOK 多服务商配置（设置·模型配置）数据层。
 *
 * 一个账号可配置一组 OpenAI 兼容服务商（各自 label + key + 端点 + 默认模型 + 可选价卡）；
 * 账号再指定「聊天默认」与「后台默认」两个跨服务商指针 `(provider_id, model)`。
 * 服务端只存 AES-256-GCM 密文、仅回显 Key 后 4 位。REST 类型由后端 OpenAPI 生成
 * （仓库根 `pnpm gen:types`）。
 */

type Schemas = components["schemas"];

/** 单个 BYOK 服务商的设置视图（永不含明文 Key）。 */
export type LlmProviderView = Schemas["LlmProviderView"];
/** 账号默认指针：某服务商 + 某模型。 */
export type LlmDefaultPointer = Schemas["LlmDefaultPointer"];
/**
 * 设置·模型配置的完整状态：服务商列表 + 账号默认指针 + 部署级能力。
 *
 * 部署级字段（`billing_mode` / `platform_available` / `platform_model` /
 * `free_tier_active`）由已废弃的单 Key 状态契约迁移到这里的顶层——它们描述账号/部署，
 * 不属于任何单个服务商。
 */
export type LlmProvidersResponse = Schemas["LlmProvidersResponse"];

/** 新增服务商入参（首个自动成为账号聊天默认）。 */
export type CreateLlmProviderInput = Schemas["CreateLlmProviderRequest"];
/** 部分更新服务商入参（省略 api_key 保留已存密文）。 */
export type UpdateLlmProviderInput = Schemas["UpdateLlmProviderRequest"];
/** 设置账号聊天 / 后台默认指针入参（tri-state：省略=不变，chat 必须成对，background=null 清除）。 */
export type SetLlmDefaultsInput = Schemas["SetLlmDefaultsRequest"];

/** 服务商列表 + 账号默认指针 + 部署能力（设置页单一数据源）。 */
export function listLlmProviders(): Promise<LlmProvidersResponse> {
  return api.get<LlmProvidersResponse>("/v1/users/me/llm-providers");
}

/** 新增一个 OpenAI 兼容服务商（Key 加密存储，状态置 'unchecked'）。 */
export function createLlmProvider(
  input: CreateLlmProviderInput,
): Promise<LlmProviderView> {
  return api.post<LlmProviderView>("/v1/users/me/llm-providers", input);
}

/** 更新某服务商（端点 / 模型 / label / 价卡；api_key 省略则保留已存 Key）。 */
export function updateLlmProvider(
  providerId: string,
  input: UpdateLlmProviderInput,
): Promise<LlmProviderView> {
  return api.patch<LlmProviderView>(
    `/v1/users/me/llm-providers/${providerId}`,
    input,
  );
}

/** 删除某服务商（账号默认与会话覆盖由后端静默回落，不硬失败）。 */
export function deleteLlmProvider(
  providerId: string,
): Promise<{ status: string }> {
  return api.delete<{ status: string }>(
    `/v1/users/me/llm-providers/${providerId}`,
  );
}

/** 探测某服务商端点，持久化并返回 'active' / 'error' + supports_tools。 */
export function testLlmProvider(providerId: string): Promise<LlmProviderView> {
  return api.post<LlmProviderView>(
    `/v1/users/me/llm-providers/${providerId}/test`,
  );
}

/** 设置账号聊天 / 后台默认指针（返回刷新后的完整列表状态）。 */
export function setLlmDefaults(
  input: SetLlmDefaultsInput,
): Promise<LlmProvidersResponse> {
  return api.put<LlmProvidersResponse>(
    "/v1/users/me/llm-providers/defaults",
    input,
  );
}

/** 账号聊天默认所在的服务商（`is_default_chat`），无则 undefined。 */
export function defaultChatProvider(
  response: LlmProvidersResponse | undefined | null,
): LlmProviderView | undefined {
  return response?.providers.find((p) => p.is_default_chat);
}

/**
 * 账号「有效聊天模型」所在服务商的工具调用支持位——喂给工具软门禁
 * （{@link import("@/lib/llmToolsGate").needsToolsGateHint}）。多服务商下门禁只对
 * 账号默认聊天服务商生效；keyless / 平台默认返回 undefined（平台模型不提示）。
 */
export function defaultChatSupportsTools(
  response: LlmProvidersResponse | undefined | null,
): boolean | null | undefined {
  return defaultChatProvider(response)?.supports_tools;
}
