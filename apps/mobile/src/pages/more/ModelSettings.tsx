import {
  type LlmDefaultPointer,
  type LlmProviderView,
  type LlmProvidersResponse,
  deleteLlmProvider,
  listLlmProviders,
  setLlmDefaults,
  testLlmProvider,
} from "@/api/llmProviders";
import {
  type ModelCatalog,
  type ModelCatalogItem,
  useModels,
} from "@/api/models";
import { ConfirmDialog } from "@/components/conversations";
import { ProviderForm } from "@/pages/more/ProviderForm";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

// 设置·模型配置 — the BYOK 多服务商 list page (mirrors desktop, mobile's own implementation).
//
// Structure: platform-credit note (when the deployment offers it) → configured provider cards
// (label / endpoint host / status / masked key / default model; 测试/编辑/删除) → 「添加服务商」
// (vendor presets live in ProviderForm) → account default chat / background model selectors
// (cross-provider, grouped). The single-key form was retired with the /llm-key contract; the
// deployment-level fields (billing_mode / platform_*) now ride on the list response top-level.

function endpointHost(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed).host;
  } catch {
    return trimmed.replace(/^https?:\/\//, "").split("/")[0] ?? trimmed;
  }
}

function capabilityLabel(supportsTools: boolean | null | undefined): string {
  if (supportsTools === true) return "支持工具调用";
  if (supportsTools === false) return "仅对话";
  return "未测试能力";
}

/** A titled provider group of BYOK catalog models (for the account default selectors). */
type ProviderModelGroup = {
  key: string;
  title: string;
  items: ModelCatalogItem[];
};

function byokModelGroups(catalog: ModelCatalog | null): ProviderModelGroup[] {
  const groups = new Map<string, ProviderModelGroup>();
  for (const item of catalog?.models ?? []) {
    if (item.origin !== "byok" || !item.provider_id) continue;
    const key = item.provider_id;
    const g = groups.get(key);
    if (g) g.items.push(item);
    else
      groups.set(key, {
        key,
        title: item.provider_label ?? item.vendor,
        items: [item],
      });
  }
  return [...groups.values()];
}

function encodePointer(p: LlmDefaultPointer): string {
  return `${p.provider_id}::${p.model}`;
}

function decodePointer(value: string): LlmDefaultPointer | null {
  const i = value.indexOf("::");
  if (i < 0) return null;
  const provider_id = value.slice(0, i);
  const model = value.slice(i + 2);
  if (!provider_id || !model) return null;
  return { provider_id, model };
}

export function ModelSettings() {
  const navigate = useNavigate();
  const [data, setData] = useState<LlmProvidersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<
    { mode: "add" } | { mode: "edit"; provider: LlmProviderView } | null
  >(null);
  const [deleteTarget, setDeleteTarget] = useState<LlmProviderView | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);
  const { data: catalog, refetch: refetchCatalog } = useModels();

  function loadInitial() {
    setLoading(true);
    setLoadError(null);
    listLlmProviders()
      .then(setData)
      .catch((e: unknown) =>
        setLoadError(
          e instanceof Error && e.message ? e.message : "加载失败，请重试",
        ),
      )
      .finally(() => setLoading(false));
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: loadInitial is stable; run once on mount
  useEffect(() => {
    loadInitial();
  }, []);

  async function reload() {
    const next = await listLlmProviders();
    setData(next);
    // A configured / removed / defaulted provider changes the catalog (availability +
    // resolved account model) — revalidate so the picker + 当前模型 badge stay honest.
    refetchCatalog();
  }

  const platformMode =
    data?.platform_available === true || data?.billing_mode === "platform";

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteLlmProvider(deleteTarget.id);
      setDeleteTarget(null);
      await reload();
    } catch {
      /* keep the dialog open; the card list is unchanged */
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => (form ? setForm(null) : navigate("/more"))}
        >
          ← {form ? "模型配置" : "设置"}
        </button>
        <span>模型配置</span>
        <span style={{ width: 44 }} />
      </header>

      <div className="settings-body">
        {form ? (
          <ProviderForm
            provider={form.mode === "edit" ? form.provider : undefined}
            onSaved={() => {
              setForm(null);
              void reload();
            }}
            onCancel={() => setForm(null)}
          />
        ) : loading ? (
          <p className="muted hint">加载中…</p>
        ) : loadError ? (
          <div className="hint">
            <p className="error">{loadError}</p>
            <button
              type="button"
              onClick={loadInitial}
              style={{ marginTop: 12 }}
            >
              重试
            </button>
          </div>
        ) : data ? (
          <>
            <p className="settings-desc">
              {platformMode
                ? "接入你自己的 OpenAI 兼容服务商为高级选项——不接入也可用平台额度直接对话。可添加多个服务商，按你的端点自担费用。Key 经 AES 加密存储，仅回显后 4 位。"
                : "添加一个或多个 OpenAI 兼容服务商（API Key、Base URL、默认模型名）即可对话。Key 经 AES 加密存储，仅回显后 4 位。"}
            </p>

            <ProviderList
              providers={data.providers}
              onTest={async (id) => {
                const updated = await testLlmProvider(id);
                setData((prev) =>
                  prev
                    ? {
                        ...prev,
                        providers: prev.providers.map((p) =>
                          p.id === updated.id ? updated : p,
                        ),
                      }
                    : prev,
                );
                refetchCatalog();
              }}
              onEdit={(provider) => setForm({ mode: "edit", provider })}
              onDelete={(provider) => setDeleteTarget(provider)}
            />

            <button
              type="button"
              className="btn-outline add-provider-btn"
              onClick={() => setForm({ mode: "add" })}
            >
              ＋ 添加服务商
            </button>

            <DefaultsSection
              data={data}
              catalog={catalog}
              onChanged={(next) => {
                setData(next);
                refetchCatalog();
              }}
            />

            <InfoNote />
          </>
        ) : null}
      </div>

      {deleteTarget && (
        <ConfirmDialog
          title="删除服务商"
          message={`删除「${deleteTarget.label || endpointHost(deleteTarget.base_url) || "该服务商"}」后，指向它的账号默认与会话将自动回落到其他可用模型。此操作不可撤销。`}
          confirmLabel={deleting ? "删除中…" : "删除"}
          busy={deleting}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => void confirmDelete()}
        />
      )}
    </div>
  );
}

function ProviderList({
  providers,
  onTest,
  onEdit,
  onDelete,
}: {
  providers: LlmProviderView[];
  onTest: (id: string) => Promise<void>;
  onEdit: (provider: LlmProviderView) => void;
  onDelete: (provider: LlmProviderView) => void;
}) {
  if (providers.length === 0) {
    return (
      <p className="muted hint" data-testid="providers-empty">
        还没有配置服务商。
      </p>
    );
  }
  return (
    <div className="provider-list">
      {providers.map((p) => (
        <ProviderCard
          key={p.id}
          provider={p}
          onTest={onTest}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

function StatusBadge({
  status,
  message,
}: {
  status: string;
  message?: string | null;
}) {
  if (status === "active") {
    return <span className="status-line status-ok">● 连接正常</span>;
  }
  if (status === "error") {
    return (
      <span className="status-line status-err">● {message ?? "连接失败"}</span>
    );
  }
  return <span className="status-line status-idle">未测试</span>;
}

function ProviderCard({
  provider,
  onTest,
  onEdit,
  onDelete,
}: {
  provider: LlmProviderView;
  onTest: (id: string) => Promise<void>;
  onEdit: (provider: LlmProviderView) => void;
  onDelete: (provider: LlmProviderView) => void;
}) {
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const host = endpointHost(provider.base_url);

  async function test() {
    setTesting(true);
    setError(null);
    try {
      await onTest(provider.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "测试失败，请重试");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="section-card provider-card" data-testid="provider-card">
      <div className="provider-head">
        <span className="provider-label">
          {provider.label || host || "服务商"}
        </span>
        <span className="provider-default-badges">
          {provider.is_default_chat && (
            <span className="provider-badge">对话默认</span>
          )}
          {provider.is_default_background && (
            <span className="provider-badge">后台默认</span>
          )}
        </span>
      </div>

      {host && <p className="provider-host muted">{host}</p>}
      <span className="masked-key">{provider.masked_key ?? "已配置"}</span>
      <p className="provider-model">模型 {provider.default_model}</p>
      {(provider.price_cache_miss || provider.price_output) && (
        <p className="muted" style={{ fontSize: 12 }}>
          单价 输入 {provider.price_cache_miss ?? "—"} / 输出{" "}
          {provider.price_output ?? "—"}
          {provider.price_cache_hit
            ? ` / 缓存 ${provider.price_cache_hit}`
            : ""}{" "}
          USD/1M
        </p>
      )}

      <div>
        <StatusBadge status={provider.status} message={provider.message} />
        <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
          {capabilityLabel(provider.supports_tools)}
        </span>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn-outline"
          onClick={() => void test()}
          disabled={testing}
        >
          {testing ? "测试中…" : "测试连接"}
        </button>
        <button
          type="button"
          className="btn-outline"
          onClick={() => onEdit(provider)}
          disabled={testing}
        >
          编辑
        </button>
        <button
          type="button"
          className="btn-danger-outline"
          onClick={() => onDelete(provider)}
          disabled={testing}
        >
          删除
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function DefaultsSection({
  data,
  catalog,
  onChanged,
}: {
  data: LlmProvidersResponse;
  catalog: ModelCatalog | null;
  onChanged: (next: LlmProvidersResponse) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const groups = byokModelGroups(catalog);

  // 账号默认指针只指向 BYOK 服务商（LlmDefaultPointer 必带 provider_id）；没有服务商时不展示。
  if (data.providers.length === 0 || groups.length === 0) return null;

  const chatValue = data.default_chat ? encodePointer(data.default_chat) : "";
  const backgroundValue = data.default_background
    ? encodePointer(data.default_background)
    : "";

  async function apply(promise: Promise<LlmProvidersResponse>) {
    setSaving(true);
    setError(null);
    try {
      onChanged(await promise);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  function onChatChange(value: string) {
    const ptr = decodePointer(value);
    if (!ptr) return;
    void apply(setLlmDefaults({ chat: ptr }));
  }

  function onBackgroundChange(value: string) {
    if (value === "") {
      void apply(setLlmDefaults({ background: null }));
      return;
    }
    const ptr = decodePointer(value);
    if (!ptr) return;
    void apply(setLlmDefaults({ background: ptr }));
  }

  const renderOptgroups = () =>
    groups.map((g) => (
      <optgroup key={g.key} label={g.title}>
        {g.items.map((m) => (
          <option
            key={`${m.provider_id}:${m.id}`}
            value={`${m.provider_id}::${m.id}`}
          >
            {m.display_name}
          </option>
        ))}
      </optgroup>
    ));

  return (
    <div className="section" style={{ marginTop: 8 }}>
      <h2 className="section-title">账号默认模型</h2>
      <p className="section-note">
        全链路默认使用的模型，可跨服务商选择；后台模型用于标题、记忆等便宜任务。
      </p>
      <div className="section-card">
        <div className="field">
          <label className="field-label" htmlFor="default-chat">
            对话默认模型
          </label>
          <select
            id="default-chat"
            className="text-input"
            value={chatValue}
            disabled={saving}
            onChange={(e) => onChatChange(e.target.value)}
          >
            {!data.default_chat && (
              <option value="" disabled>
                选择对话默认模型
              </option>
            )}
            {renderOptgroups()}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="default-background">
            后台默认模型
          </label>
          <select
            id="default-background"
            className="text-input"
            value={backgroundValue}
            disabled={saving}
            onChange={(e) => onBackgroundChange(e.target.value)}
          >
            <option value="">跟随对话默认模型</option>
            {renderOptgroups()}
          </select>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}

function InfoNote() {
  return (
    <p className="section-note" style={{ marginTop: 16 }}>
      你的 Key 仅用于你自己的对话，经 AES-256-GCM 加密存储，服务端只显示后 4
      位。平台只统计 token 用量。
    </p>
  );
}
