/**
 * BYOK vendor presets — frontend-only catalog for model settings.
 *
 * Each preset supplies a canonical base_url and common model IDs; users may
 * still override model names (their key determines what actually works).
 */

export type ByokProviderId =
  | "openai"
  | "deepseek"
  | "moonshot"
  | "zhipu"
  | "doubao"
  | "openrouter"
  | "custom";

export interface ByokProviderPreset {
  id: Exclude<ByokProviderId, "custom">;
  label: string;
  baseUrl: string;
  /** Alternate base URLs that should map to this preset (e.g. regional endpoints). */
  baseUrlAliases?: readonly string[];
  defaultModel: string;
  models: readonly string[];
  keyHelpUrl?: string;
}

export const BYOK_CUSTOM_PROVIDER_ID = "custom" as const;

export const BYOK_PROVIDER_PRESETS: readonly ByokProviderPreset[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    baseUrlAliases: ["https://api.deepseek.com/v1"],
    defaultModel: "deepseek-v4-flash",
    models: ["deepseek-v4-flash", "deepseek-v4-pro"],
    keyHelpUrl: "https://platform.deepseek.com/api_keys",
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o",
    models: ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    keyHelpUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "moonshot",
    label: "Kimi (Moonshot)",
    baseUrl: "https://api.moonshot.cn/v1",
    baseUrlAliases: ["https://api.moonshot.ai/v1"],
    defaultModel: "kimi-k2.5",
    models: ["kimi-k2.5", "kimi-k2", "moonshot-v1-8k", "moonshot-v1-32k"],
    keyHelpUrl: "https://platform.moonshot.cn/console/api-keys",
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    defaultModel: "glm-4-plus",
    models: ["glm-4-plus", "glm-4-flash", "glm-4-air"],
    keyHelpUrl: "https://open.bigmodel.cn/usercenter/apikeys",
  },
  {
    id: "doubao",
    label: "豆包 (火山方舟)",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-pro-32k",
    models: ["doubao-pro-32k", "doubao-lite-32k"],
    keyHelpUrl:
      "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "openrouter/auto",
    models: [
      "openrouter/auto",
      "anthropic/claude-sonnet-4",
      "google/gemini-2.5-pro",
    ],
    keyHelpUrl: "https://openrouter.ai/keys",
  },
] as const;

export const DEFAULT_BYOK_PROVIDER_ID: Exclude<ByokProviderId, "custom"> =
  "deepseek";

const PRESET_BY_ID = new Map(
  BYOK_PROVIDER_PRESETS.map((preset) => [preset.id, preset]),
);

/** Normalize base_url for preset matching (case, trailing slashes). */
export function normalizeByokBaseUrl(url: string): string {
  let normalized = url.trim().toLowerCase();
  while (normalized.endsWith("/")) {
    normalized = normalized.slice(0, -1);
  }
  return normalized;
}

function presetBaseUrls(preset: ByokProviderPreset): string[] {
  return [preset.baseUrl, ...(preset.baseUrlAliases ?? [])];
}

export function getByokProviderPreset(
  id: Exclude<ByokProviderId, "custom">,
): ByokProviderPreset {
  const preset = PRESET_BY_ID.get(id);
  if (!preset) {
    throw new Error(`Unknown BYOK provider preset: ${id}`);
  }
  return preset;
}

export function isCustomByokProvider(
  id: ByokProviderId,
): id is typeof BYOK_CUSTOM_PROVIDER_ID {
  return id === BYOK_CUSTOM_PROVIDER_ID;
}

/** Match stored base_url to a preset, or fall back to custom. */
export function resolveByokProviderFromConfig(baseUrl: string): ByokProviderId {
  const trimmed = baseUrl.trim();
  if (!trimmed) return DEFAULT_BYOK_PROVIDER_ID;

  const normalized = normalizeByokBaseUrl(trimmed);
  for (const preset of BYOK_PROVIDER_PRESETS) {
    if (
      presetBaseUrls(preset).some(
        (candidate) => normalizeByokBaseUrl(candidate) === normalized,
      )
    ) {
      return preset.id;
    }
  }
  return BYOK_CUSTOM_PROVIDER_ID;
}

export function listByokProviderOptions(): Array<{
  id: ByokProviderId;
  label: string;
}> {
  return [
    ...BYOK_PROVIDER_PRESETS.map((preset) => ({
      id: preset.id,
      label: preset.label,
    })),
    { id: BYOK_CUSTOM_PROVIDER_ID, label: "自定义" },
  ];
}
