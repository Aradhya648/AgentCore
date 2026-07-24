import {
  type CreateLlmProviderInput,
  type LlmProviderView,
  type UpdateLlmProviderInput,
  createLlmProvider,
  updateLlmProvider,
} from "@/api/llmProviders";
import { useState } from "react";

// 添加 / 编辑一个 BYOK 服务商 (设置·模型配置). Mobile-local vendor presets (no shared package
// with desktop) prefill the endpoint / label / model list; 「自定义」falls back to free text.
// Add creates a provider (first one auto-becomes the chat default, server-side); edit PATCHes
// endpoint / model / label / price and may leave the key untouched (留空保留已存密文).

/** Mobile-local BYOK presets. */
type ProviderId =
  | "deepseek"
  | "openai"
  | "moonshot"
  | "zhipu"
  | "doubao"
  | "openrouter"
  | "custom";

type ProviderPreset = {
  id: Exclude<ProviderId, "custom">;
  label: string;
  baseUrl: string;
  baseUrlAliases?: readonly string[];
  defaultModel: string;
  models: readonly string[];
};

const PROVIDER_PRESETS: readonly ProviderPreset[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    baseUrlAliases: ["https://api.deepseek.com/v1"],
    defaultModel: "deepseek-v4-flash",
    models: ["deepseek-v4-flash", "deepseek-v4-pro"],
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o",
    models: ["gpt-4o", "gpt-4o-mini", "o3-mini"],
  },
  {
    id: "moonshot",
    label: "Kimi (Moonshot)",
    baseUrl: "https://api.moonshot.cn/v1",
    baseUrlAliases: ["https://api.moonshot.ai/v1"],
    defaultModel: "kimi-k2.5",
    models: ["kimi-k2.5", "kimi-k2", "moonshot-v1-8k", "moonshot-v1-32k"],
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    defaultModel: "glm-4-plus",
    models: ["glm-4-plus", "glm-4-flash", "glm-4-air"],
  },
  {
    id: "doubao",
    label: "豆包 (火山方舟)",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-pro-32k",
    models: ["doubao-pro-32k", "doubao-lite-32k"],
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
  },
];

const DEFAULT_PROVIDER_ID: Exclude<ProviderId, "custom"> = "deepseek";
const MODEL_OTHER_VALUE = "__other__";

function normalizeBaseUrl(url: string): string {
  let normalized = url.trim().toLowerCase();
  while (normalized.endsWith("/")) {
    normalized = normalized.slice(0, -1);
  }
  return normalized;
}

function resolveProvider(baseUrl: string): ProviderId {
  const trimmed = baseUrl.trim();
  if (!trimmed) return DEFAULT_PROVIDER_ID;
  const normalized = normalizeBaseUrl(trimmed);
  for (const preset of PROVIDER_PRESETS) {
    const candidates = [preset.baseUrl, ...(preset.baseUrlAliases ?? [])];
    if (candidates.some((c) => normalizeBaseUrl(c) === normalized)) {
      return preset.id;
    }
  }
  return "custom";
}

function getPreset(id: Exclude<ProviderId, "custom">): ProviderPreset {
  const preset = PROVIDER_PRESETS.find((p) => p.id === id);
  if (!preset) throw new Error(`Unknown provider: ${id}`);
  return preset;
}

export function ProviderForm({
  provider,
  onSaved,
  onCancel,
}: {
  /** When set, the form edits this provider; otherwise it adds a new one. */
  provider?: LlmProviderView;
  /** Called after a successful create/update (parent reloads the authoritative list). */
  onSaved: (saved: LlmProviderView) => void;
  onCancel: () => void;
}) {
  const editing = provider != null;
  const defaultPreset = getPreset(DEFAULT_PROVIDER_ID);
  const initialBaseUrl = provider?.base_url ?? "";
  const initialModel = provider?.default_model ?? "";

  const [apiKey, setApiKey] = useState("");
  const [providerId, setProviderId] = useState<ProviderId>(() =>
    editing ? resolveProvider(initialBaseUrl) : DEFAULT_PROVIDER_ID,
  );
  const [label, setLabel] = useState(
    () => provider?.label ?? defaultPreset.label,
  );
  const [baseUrl, setBaseUrl] = useState(
    () => initialBaseUrl.trim() || defaultPreset.baseUrl,
  );
  const [defaultModel, setDefaultModel] = useState(
    () => initialModel.trim() || defaultPreset.defaultModel,
  );
  const [priceCacheMiss, setPriceCacheMiss] = useState(
    provider?.price_cache_miss ?? "",
  );
  const [priceOutput, setPriceOutput] = useState(provider?.price_output ?? "");
  const [priceCacheHit, setPriceCacheHit] = useState(
    provider?.price_cache_hit ?? "",
  );
  const [customModelMode, setCustomModelMode] = useState(() => {
    const model = initialModel.trim();
    if (!model) return false;
    const resolved = resolveProvider(initialBaseUrl);
    if (resolved === "custom") return false;
    return !getPreset(resolved).models.includes(model);
  });
  const [reveal, setReveal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasInitialAdvanced = Boolean(
    (provider?.price_cache_hit ?? "").trim() ||
      (provider?.price_cache_miss ?? "").trim() ||
      (provider?.price_output ?? "").trim(),
  );
  const [advancedOpen, setAdvancedOpen] = useState(hasInitialAdvanced);

  const preset = providerId === "custom" ? null : getPreset(providerId);
  const modelSuggestions = preset?.models ?? [];
  const useModelSelect = modelSuggestions.length > 0;
  const keyOk = editing || apiKey.trim().length > 0;
  const canSave =
    keyOk &&
    baseUrl.trim().length > 0 &&
    defaultModel.trim().length > 0 &&
    !saving;

  const modelSelectValue =
    useModelSelect &&
    !customModelMode &&
    modelSuggestions.includes(defaultModel)
      ? defaultModel
      : MODEL_OTHER_VALUE;

  function selectProvider(next: ProviderId) {
    setProviderId(next);
    if (next !== "custom") {
      const p = getPreset(next);
      setBaseUrl(p.baseUrl);
      setDefaultModel(p.defaultModel);
      setLabel(p.label);
      setCustomModelMode(false);
    } else {
      setCustomModelMode(false);
    }
  }

  function selectModelOption(value: string) {
    if (value === MODEL_OTHER_VALUE) {
      setCustomModelMode(true);
      return;
    }
    setCustomModelMode(false);
    setDefaultModel(value);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const miss = priceCacheMiss.trim();
      const out = priceOutput.trim();
      const hit = priceCacheHit.trim();
      const pricesEmpty = !miss && !out && !hit;
      const trimmedKey = apiKey.trim();
      const common = {
        base_url: baseUrl.trim() || null,
        default_model: defaultModel.trim() || null,
        label: label.trim(),
        price_cache_miss: pricesEmpty ? null : miss || null,
        price_output: pricesEmpty ? null : out || null,
        price_cache_hit: pricesEmpty ? null : hit || null,
      };
      let saved: LlmProviderView;
      if (editing && provider) {
        const patch: UpdateLlmProviderInput = { ...common };
        // 编辑时留空 = 保留已存密文（省略 api_key）。
        if (trimmedKey) patch.api_key = trimmedKey;
        saved = await updateLlmProvider(provider.id, patch);
      } else {
        const body: CreateLlmProviderInput = {
          api_key: trimmedKey,
          ...common,
        };
        saved = await createLlmProvider(body);
      }
      onSaved(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="section-card">
      <span className="section-title">
        {editing ? "编辑服务商" : "添加服务商"}
      </span>

      <div className="field">
        <label className="field-label" htmlFor="llm-provider">
          厂商
        </label>
        <select
          id="llm-provider"
          value={providerId}
          onChange={(e) => selectProvider(e.target.value as ProviderId)}
          className="text-input"
        >
          {PROVIDER_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
          <option value="custom">自定义</option>
        </select>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="llm-label">
          显示名称
        </label>
        <input
          id="llm-label"
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="如 DeepSeek、火山方舟"
          autoComplete="off"
          spellCheck={false}
          className="text-input"
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="llm-api-key">
          API Key{editing ? "（可选）" : ""}
        </label>
        <div className="key-input-wrap">
          <input
            id="llm-api-key"
            type={reveal ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={editing ? "留空则保留已保存的 Key" : "sk-..."}
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="button"
            className="key-reveal"
            onClick={() => setReveal((r) => !r)}
          >
            {reveal ? "隐藏" : "显示"}
          </button>
        </div>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="llm-base-url">
          Base URL
        </label>
        <input
          id="llm-base-url"
          type="text"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={
            providerId === "custom"
              ? "https://your-endpoint.example/v1"
              : preset?.baseUrl
          }
          autoComplete="off"
          spellCheck={false}
          className="text-input"
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="llm-default-model">
          默认模型名
        </label>
        {useModelSelect ? (
          <select
            id="llm-default-model"
            value={modelSelectValue}
            onChange={(e) => selectModelOption(e.target.value)}
            className="text-input"
          >
            {modelSuggestions.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
            <option value={MODEL_OTHER_VALUE}>其他…</option>
          </select>
        ) : (
          <input
            id="llm-default-model"
            type="text"
            value={defaultModel}
            onChange={(e) => setDefaultModel(e.target.value)}
            placeholder="model-name"
            autoComplete="off"
            spellCheck={false}
            className="text-input"
          />
        )}
        {useModelSelect &&
          (customModelMode || modelSelectValue === MODEL_OTHER_VALUE) && (
            <input
              type="text"
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              placeholder={preset?.defaultModel ?? "model-name"}
              autoComplete="off"
              spellCheck={false}
              className="text-input"
              style={{ marginTop: 8 }}
            />
          )}
      </div>

      <details
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
      >
        <summary className="field-label" style={{ cursor: "pointer" }}>
          高级选项 · 单价卡
        </summary>
        <p className="section-note" style={{ margin: "8px 0 4px" }}>
          输入与输出成对填写后可显示 ≈¥ 估算；全空清除价卡（USD / 1M）。
        </p>
        <div className="field" style={{ marginTop: 8 }}>
          <label className="field-label" htmlFor="llm-price-miss">
            输入价
          </label>
          <input
            id="llm-price-miss"
            type="text"
            inputMode="decimal"
            value={priceCacheMiss}
            onChange={(e) => setPriceCacheMiss(e.target.value)}
            placeholder="如 0.28"
            autoComplete="off"
            spellCheck={false}
            className="text-input"
          />
        </div>
        <div className="field" style={{ marginTop: 8 }}>
          <label className="field-label" htmlFor="llm-price-out">
            输出价
          </label>
          <input
            id="llm-price-out"
            type="text"
            inputMode="decimal"
            value={priceOutput}
            onChange={(e) => setPriceOutput(e.target.value)}
            placeholder="如 0.42"
            autoComplete="off"
            spellCheck={false}
            className="text-input"
          />
        </div>
        <div className="field" style={{ marginTop: 8 }}>
          <label className="field-label" htmlFor="llm-price-hit">
            缓存命中价（可选）
          </label>
          <input
            id="llm-price-hit"
            type="text"
            inputMode="decimal"
            value={priceCacheHit}
            onChange={(e) => setPriceCacheHit(e.target.value)}
            placeholder="缺省=输入价"
            autoComplete="off"
            spellCheck={false}
            className="text-input"
          />
        </div>
      </details>

      <div className="field-actions">
        <button
          type="button"
          className="btn-outline"
          onClick={onCancel}
          disabled={saving}
        >
          取消
        </button>
        <button type="button" disabled={!canSave} onClick={() => void save()}>
          {saving ? "保存中…" : "保存"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
