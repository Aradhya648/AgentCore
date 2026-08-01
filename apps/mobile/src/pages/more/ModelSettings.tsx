import {
  type LlmProviderView,
  type LlmProvidersResponse,
  deleteLlmProvider,
  listLlmProviders,
  testLlmProvider,
} from "@/api/llmProviders";
import {
  type CreateLlmModelProfileRequest,
  type LlmModelProfileView,
  type ModelProfileSlot,
  createModelProfile,
  deleteModelProfile,
  invalidateModelProfilesCache,
  listModelProfiles,
  profileSlotsSummary,
  setDefaultModelProfile,
  updateModelProfile,
} from "@/api/modelProfiles";
import { type ModelCatalog, useModels } from "@/api/models";
import { ConfirmDialog } from "@/components/conversations";
import { ProviderForm } from "@/pages/more/ProviderForm";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

// 设置·模型配置 — BYOK providers + 模型组合管理.
//
// Chat picks combinations only; this page creates/edits combinations (main required;
// worker/background empty = follow main) and sets the account default.

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

/** A titled option group for slot selectors (platform or BYOK). */
type ProviderModelGroup = {
  key: string;
  title: string;
  items: { id: string; display_name: string; value: string }[];
};

const PLATFORM_POINTER_ID = "__platform__";

function defaultModelGroups(
  catalog: ModelCatalog | null,
  platformModel?: string | null,
): ProviderModelGroup[] {
  const groups: ProviderModelGroup[] = [];

  const platformItems: ProviderModelGroup["items"] = [];
  const platformSeen = new Set<string>();
  const addPlatform = (id: string, displayName: string) => {
    if (!id || platformSeen.has(id)) return;
    platformSeen.add(id);
    platformItems.push({
      id,
      display_name: displayName,
      value: `${PLATFORM_POINTER_ID}::${id}`,
    });
  };
  for (const item of catalog?.models ?? []) {
    if (item.origin !== "platform" || !item.available) continue;
    addPlatform(item.id, item.display_name);
  }
  const fallback = platformModel?.trim();
  if (fallback) addPlatform(fallback, fallback);
  if (platformItems.length > 0) {
    groups.push({
      key: PLATFORM_POINTER_ID,
      title: "平台额度",
      items: platformItems,
    });
  }

  const byok = new Map<string, ProviderModelGroup>();
  for (const item of catalog?.models ?? []) {
    if (item.origin !== "byok" || !item.provider_id) continue;
    const key = item.provider_id;
    const entry = {
      id: item.id,
      display_name: item.display_name,
      value: `${item.provider_id}::${item.id}`,
    };
    const g = byok.get(key);
    if (g) g.items.push(entry);
    else
      byok.set(key, {
        key,
        title: item.provider_label ?? item.vendor,
        items: [entry],
      });
  }
  groups.push(...byok.values());
  return groups;
}

function encodeSlot(slot: ModelProfileSlot): string {
  if (slot.origin === "platform") {
    return `${PLATFORM_POINTER_ID}::${slot.model}`;
  }
  return `${slot.provider_id}::${slot.model}`;
}

function decodeSlot(value: string): ModelProfileSlot | null {
  const i = value.indexOf("::");
  if (i < 0) return null;
  const provider_id = value.slice(0, i);
  const model = value.slice(i + 2);
  if (!provider_id || !model) return null;
  if (provider_id === PLATFORM_POINTER_ID) {
    return { origin: "platform", provider_id: null, model };
  }
  return { origin: "byok", provider_id, model };
}

type Surface =
  | { kind: "list" }
  | { kind: "provider"; mode: "add" }
  | { kind: "provider"; mode: "edit"; provider: LlmProviderView }
  | { kind: "profile"; mode: "new" }
  | { kind: "profile"; mode: "edit"; profile: LlmModelProfileView };

export function ModelSettings() {
  const navigate = useNavigate();
  const [data, setData] = useState<LlmProvidersResponse | null>(null);
  const [profiles, setProfiles] = useState<LlmModelProfileView[]>([]);
  const [defaultProfileId, setDefaultProfileId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [surface, setSurface] = useState<Surface>({ kind: "list" });
  const [deleteTarget, setDeleteTarget] = useState<LlmProviderView | null>(
    null,
  );
  const [deleteProfileTarget, setDeleteProfileTarget] =
    useState<LlmModelProfileView | null>(null);
  const [deleting, setDeleting] = useState(false);
  const { data: catalog, refetch: refetchCatalog } = useModels();

  async function loadProfiles() {
    const res = await listModelProfiles();
    setProfiles(res.data);
    setDefaultProfileId(res.default_model_profile_id ?? null);
    invalidateModelProfilesCache();
  }

  function loadInitial() {
    setLoading(true);
    setLoadError(null);
    Promise.all([listLlmProviders(), listModelProfiles()])
      .then(([providers, profileList]) => {
        setData(providers);
        setProfiles(profileList.data);
        setDefaultProfileId(profileList.default_model_profile_id ?? null);
        invalidateModelProfilesCache();
      })
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
    await loadProfiles();
    refetchCatalog();
  }

  const platformMode = data?.platform_available === true;

  async function confirmDeleteProvider() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteLlmProvider(deleteTarget.id);
      setDeleteTarget(null);
      await reload();
    } catch {
      /* keep dialog open */
    } finally {
      setDeleting(false);
    }
  }

  async function confirmDeleteProfile() {
    if (!deleteProfileTarget) return;
    setDeleting(true);
    try {
      await deleteModelProfile(deleteProfileTarget.id);
      setDeleteProfileTarget(null);
      await loadProfiles();
    } catch {
      /* keep dialog open */
    } finally {
      setDeleting(false);
    }
  }

  const onList = surface.kind === "list";
  const title =
    surface.kind === "provider"
      ? "模型配置"
      : surface.kind === "profile"
        ? surface.mode === "new"
          ? "新建组合"
          : "编辑组合"
        : "模型配置";

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() =>
            onList ? navigate("/more") : setSurface({ kind: "list" })
          }
        >
          ← {onList ? "设置" : "模型配置"}
        </button>
        <span>{title}</span>
        <span style={{ width: 44 }} />
      </header>

      <div className="settings-body">
        {surface.kind === "provider" ? (
          <ProviderForm
            provider={surface.mode === "edit" ? surface.provider : undefined}
            onSaved={() => {
              setSurface({ kind: "list" });
              void reload();
            }}
            onCancel={() => setSurface({ kind: "list" })}
          />
        ) : surface.kind === "profile" ? (
          <ProfileForm
            profile={surface.mode === "edit" ? surface.profile : undefined}
            catalog={catalog}
            platformAvailable={platformMode}
            platformModel={data?.platform_model}
            onSaved={() => {
              setSurface({ kind: "list" });
              void loadProfiles();
            }}
            onCancel={() => setSurface({ kind: "list" })}
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

            <ProfilesSection
              profiles={profiles}
              defaultProfileId={defaultProfileId}
              catalog={catalog}
              onNew={() => setSurface({ kind: "profile", mode: "new" })}
              onEdit={(profile) =>
                setSurface({ kind: "profile", mode: "edit", profile })
              }
              onDelete={(profile) => setDeleteProfileTarget(profile)}
              onSetDefault={async (id) => {
                await setDefaultModelProfile(id);
                await loadProfiles();
              }}
            />

            <h2 className="section-title" style={{ marginTop: 20 }}>
              服务商
            </h2>
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
              onEdit={(provider) =>
                setSurface({ kind: "provider", mode: "edit", provider })
              }
              onDelete={(provider) => setDeleteTarget(provider)}
            />

            <button
              type="button"
              className="btn-outline add-provider-btn"
              onClick={() => setSurface({ kind: "provider", mode: "add" })}
            >
              ＋ 添加服务商
            </button>

            <InfoNote />
          </>
        ) : null}
      </div>

      {deleteTarget && (
        <ConfirmDialog
          title="删除服务商"
          message={`删除「${deleteTarget.label || endpointHost(deleteTarget.base_url) || "该服务商"}」后，指向它的组合槽位需重新选择。此操作不可撤销。`}
          confirmLabel={deleting ? "删除中…" : "删除"}
          busy={deleting}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => void confirmDeleteProvider()}
        />
      )}

      {deleteProfileTarget && (
        <ConfirmDialog
          title="删除组合"
          message={`删除「${deleteProfileTarget.name}」后，使用该组合的会话将回落到账号默认。此操作不可撤销。`}
          confirmLabel={deleting ? "删除中…" : "删除"}
          busy={deleting}
          onCancel={() => setDeleteProfileTarget(null)}
          onConfirm={() => void confirmDeleteProfile()}
        />
      )}
    </div>
  );
}

function ProfilesSection({
  profiles,
  defaultProfileId,
  catalog,
  onNew,
  onEdit,
  onDelete,
  onSetDefault,
}: {
  profiles: LlmModelProfileView[];
  defaultProfileId: string | null;
  catalog: ModelCatalog | null;
  onNew: () => void;
  onEdit: (p: LlmModelProfileView) => void;
  onDelete: (p: LlmModelProfileView) => void;
  onSetDefault: (id: string) => Promise<void>;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Prefer user + system; still show selected implicits if any remain.
  const visible = profiles.filter((p) => p.kind !== "implicit");

  async function makeDefault(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await onSetDefault(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "设置默认失败");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="section" data-testid="profiles-section">
      <h2 className="section-title">模型组合</h2>
      <p className="section-note">
        聊天页选择的是组合（主模型 · Worker），不是单个模型。Worker /
        后台为空时跟随主模型。可设一个账号默认组合。
      </p>

      {visible.length === 0 ? (
        <p className="muted hint" data-testid="profiles-empty">
          还没有组合。
        </p>
      ) : (
        <div className="provider-list">
          {visible.map((p) => {
            const isDefault = p.is_default || p.id === defaultProfileId;
            const canDelete = p.kind === "user";
            const canEdit = p.kind === "user";
            return (
              <div
                key={p.id}
                className="section-card provider-card"
                data-testid={`profile-card-${p.id}`}
              >
                <div className="provider-head">
                  <span className="provider-label">{p.name}</span>
                  <span className="provider-default-badges">
                    {isDefault && (
                      <span className="provider-badge">账号默认</span>
                    )}
                    {p.kind === "system" && (
                      <span className="provider-badge">预置</span>
                    )}
                  </span>
                </div>
                <p className="provider-model muted">
                  {profileSlotsSummary(catalog, p)}
                </p>
                <div className="btn-row">
                  {canEdit && (
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() => onEdit(p)}
                      disabled={busyId !== null}
                    >
                      编辑
                    </button>
                  )}
                  {!isDefault && (
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() => void makeDefault(p.id)}
                      disabled={busyId !== null}
                    >
                      {busyId === p.id ? "设置中…" : "设为默认"}
                    </button>
                  )}
                  {canDelete && (
                    <button
                      type="button"
                      className="btn-danger-outline"
                      onClick={() => onDelete(p)}
                      disabled={busyId !== null}
                    >
                      删除
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <button
        type="button"
        className="btn-outline add-provider-btn"
        data-testid="profile-new"
        onClick={onNew}
      >
        ＋ 新建组合
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function ProfileForm({
  profile,
  catalog,
  platformAvailable,
  platformModel,
  onSaved,
  onCancel,
}: {
  profile?: LlmModelProfileView;
  catalog: ModelCatalog | null;
  platformAvailable: boolean;
  platformModel?: string | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const editing = Boolean(profile);
  const groups = defaultModelGroups(catalog, platformModel);
  const firstMain =
    groups[0]?.items[0]?.value ??
    (platformModel ? `${PLATFORM_POINTER_ID}::${platformModel}` : "");
  const noSelectableModels = groups.every((g) => g.items.length === 0);

  const [name, setName] = useState(profile?.name ?? "");
  const [mainValue, setMainValue] = useState(
    profile ? encodeSlot(profile.main) : firstMain,
  );
  const [workerValue, setWorkerValue] = useState(
    profile?.worker ? encodeSlot(profile.worker) : "",
  );
  const [backgroundValue, setBackgroundValue] = useState(
    profile?.background ? encodeSlot(profile.background) : "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const renderOptgroups = () =>
    groups.map((g) => (
      <optgroup key={g.key} label={g.title}>
        {g.items.map((m) => (
          <option key={m.value} value={m.value}>
            {m.display_name}
          </option>
        ))}
      </optgroup>
    ));

  async function save() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("请填写组合名称");
      return;
    }
    const main = decodeSlot(mainValue);
    if (!main) {
      setError("请选择主模型");
      return;
    }
    const worker = workerValue ? decodeSlot(workerValue) : null;
    const background = backgroundValue ? decodeSlot(backgroundValue) : null;
    if (workerValue && !worker) {
      setError("Worker 模型无效");
      return;
    }
    if (backgroundValue && !background) {
      setError("后台模型无效");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (editing && profile) {
        await updateModelProfile(profile.id, {
          name: trimmed,
          main,
          worker,
          background,
        });
      } else {
        const body: CreateLlmModelProfileRequest = {
          name: trimmed,
          main,
          worker,
          background,
          set_as_default: false,
        };
        await createModelProfile(body);
      }
      invalidateModelProfilesCache();
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="section" data-testid="profile-form">
      <div className="section-card">
        <div className="field">
          <label className="field-label" htmlFor="profile-name">
            名称
          </label>
          <input
            id="profile-name"
            className="text-input"
            value={name}
            disabled={saving}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：日常写作"
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="profile-main">
            主模型
          </label>
          <select
            id="profile-main"
            className="text-input"
            value={mainValue}
            disabled={saving || groups.length === 0}
            onChange={(e) => setMainValue(e.target.value)}
          >
            {!mainValue && (
              <option value="" disabled>
                选择主模型
              </option>
            )}
            {renderOptgroups()}
          </select>
          {noSelectableModels && (
            <p
              className="muted"
              data-testid="profile-no-models"
              style={{ fontSize: 12, marginTop: 4 }}
            >
              {platformAvailable
                ? "暂无可用模型。平台额度暂不可用，请联系管理员或稍后重试。"
                : "暂无可用模型，请先添加服务商。"}
            </p>
          )}
        </div>
        <div className="field">
          <label className="field-label" htmlFor="profile-worker">
            Worker 模型
          </label>
          <select
            id="profile-worker"
            className="text-input"
            value={workerValue}
            disabled={saving}
            onChange={(e) => setWorkerValue(e.target.value)}
          >
            <option value="">跟随主模型</option>
            {renderOptgroups()}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="profile-background">
            后台模型
          </label>
          <select
            id="profile-background"
            className="text-input"
            value={backgroundValue}
            disabled={saving}
            onChange={(e) => setBackgroundValue(e.target.value)}
          >
            <option value="">跟随主模型</option>
            {renderOptgroups()}
          </select>
          <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            标题、记忆等便宜任务；空则跟随主模型。
          </p>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="field-actions">
          <button
            type="button"
            className="btn-outline"
            onClick={onCancel}
            disabled={saving}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || !name.trim() || !mainValue}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
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
      </div>

      {host && <p className="provider-host muted">{host}</p>}
      <span className="masked-key">{provider.masked_key ?? "已配置"}</span>
      <p className="provider-model">模型 {provider.default_model}</p>

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

function InfoNote() {
  return (
    <p className="section-note" style={{ marginTop: 16 }}>
      你的 Key 仅用于你自己的对话，经 AES-256-GCM 加密存储，服务端只显示后 4
      位。平台只统计 token 用量。
    </p>
  );
}
