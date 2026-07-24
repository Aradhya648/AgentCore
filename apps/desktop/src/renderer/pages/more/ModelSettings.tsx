import {
  ModelKeyForm,
  modelConfigApiErrorMessage,
} from "@/components/llm/ModelKeyForm";
import { ToolsCapabilityBadge } from "@/components/llm/ToolsCapabilityBadge";
import { Button } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { useLlmProviders } from "@/hooks/useLlmProviders";
import { useModels } from "@/hooks/useModels";
import { hasLocalEngine } from "@/lib/capabilities";
import {
  type DefaultProviderGroup,
  buildDefaultProviderGroups,
  decodePointer,
  encodePointer,
  pointerValue,
} from "@/lib/llmDefaults";
import { llmProviderKeys, modelKeys } from "@/lib/queryKeys";
import {
  type LlmProviderView,
  type LlmProvidersResponse,
  deleteLlmProvider,
  setLlmDefaults,
  testLlmProvider,
} from "@/services/llmProviders";
import { clearSidecarHealth } from "@/services/sidecarHealth";
import { useUIStore } from "@/stores/ui";
import { useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Loader2,
  Plus,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

/**
 * 模型配置 (/more/model) — 自带 Key（BYOK）多服务商列表页。
 *
 * 平台代付部署（billing_mode === "platform"）下不配服务商也可用平台额度发起对话，接入服务商
 * 为高级选项（按你的端点自担费用）；BYOK 部署仍需至少一个服务商。文案按部署级 billing_mode /
 * platform_available 门控。数据源为 `GET /v1/users/me/llm-providers`（{@link useLlmProviders}）。
 */
export function ModelSettings() {
  const { data: response, isLoading, isError, error } = useLlmProviders();
  const { data: catalog } = useModels();
  const queryClient = useQueryClient();

  // 添加 / 编辑表单态：null = 仅列表；add = 新增；edit = 编辑某服务商。
  const [form, setForm] = useState<
    { mode: "add" } | { mode: "edit"; provider: LlmProviderView } | null
  >(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<Record<string, string | null>>(
    {},
  );
  const [cardError, setCardError] = useState<Record<string, string | null>>({});
  const [defaultsPending, setDefaultsPending] = useState(false);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: llmProviderKeys.list });
    void queryClient.invalidateQueries({ queryKey: modelKeys.catalog });
  };

  const runTest = async (providerId: string) => {
    setTestingId(providerId);
    setCardError((s) => ({ ...s, [providerId]: null }));
    try {
      const view = await testLlmProvider(providerId);
      setTestMessage((s) => ({ ...s, [providerId]: view.message ?? null }));
    } catch (e) {
      setCardError((s) => ({
        ...s,
        [providerId]: modelConfigApiErrorMessage(e, "测试失败，请重试"),
      }));
    } finally {
      setTestingId(null);
      // Pull the persisted status / supports_tools the probe just wrote.
      refresh();
    }
  };

  const onSavedProvider = (view: LlmProviderView) => {
    setForm(null);
    refresh();
    // Auto-probe on save so the card shows connectivity + tool support at once.
    void runTest(view.id);
  };

  const removeProvider = async (provider: LlmProviderView) => {
    if (!response) return;
    const remaining = response.providers.length - 1;
    const softFallback = remaining > 0 || response.platform_available;
    const confirmMsg = softFallback
      ? `删除服务商「${providerName(provider)}」？账号默认与会话覆盖会自动回落到其他服务商或平台额度，不会中断对话。`
      : `删除服务商「${providerName(provider)}」？这是唯一的服务商，删除后将无法发起对话，直到重新接入。`;
    if (!window.confirm(confirmMsg)) return;
    setCardError((s) => ({ ...s, [provider.id]: null }));
    try {
      await deleteLlmProvider(provider.id);
      if (form?.mode === "edit" && form.provider.id === provider.id) {
        setForm(null);
      }
      refresh();
    } catch (e) {
      setCardError((s) => ({
        ...s,
        [provider.id]: modelConfigApiErrorMessage(e, "删除失败，请重试"),
      }));
    }
  };

  const applyDefaults = async (
    patch: Parameters<typeof setLlmDefaults>[0],
  ): Promise<void> => {
    setDefaultsPending(true);
    try {
      const next = await setLlmDefaults(patch);
      queryClient.setQueryData<LlmProvidersResponse>(
        llmProviderKeys.list,
        next,
      );
      void queryClient.invalidateQueries({ queryKey: modelKeys.catalog });
    } catch (e) {
      window.alert(modelConfigApiErrorMessage(e, "设置默认模型失败，请重试"));
    } finally {
      setDefaultsPending(false);
    }
  };

  const platformMode = response?.billing_mode === "platform";
  const providers = response?.providers ?? [];

  return (
    <div>
      <SettingsHeader
        title="模型配置"
        description={
          platformMode
            ? "接入你自己的 OpenAI 兼容服务商（可配置多个）。不接入也可用平台额度发起对话；接入后按你的端点自担费用。Key 经 AES 加密存储，仅回显后 4 位。"
            : "接入你自己的 OpenAI 兼容服务商（可配置多个）。Key 经 AES 加密存储，仅回显后 4 位；未接入则无法发起对话。"
        }
      />

      {isLoading ? (
        <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin" />
          加载中…
        </div>
      ) : isError || !response ? (
        <p className="mt-6 text-sm text-destructive">
          {modelConfigApiErrorMessage(error, "加载失败，请重试")}
        </p>
      ) : (
        <div className="mt-6 space-y-4">
          {response.platform_available && (
            <PlatformQuotaCard response={response} />
          )}

          {providers.map((provider) =>
            form?.mode === "edit" && form.provider.id === provider.id ? (
              <ModelKeyForm
                key={provider.id}
                providerId={provider.id}
                initialLabel={provider.label}
                initialBaseUrl={provider.base_url}
                initialModel={provider.default_model}
                initialPriceCacheHit={provider.price_cache_hit}
                initialPriceCacheMiss={provider.price_cache_miss}
                initialPriceOutput={provider.price_output}
                hideTestHint
                onSaved={onSavedProvider}
                onCancel={() => setForm(null)}
              />
            ) : (
              <ProviderCard
                key={provider.id}
                provider={provider}
                testing={testingId === provider.id}
                testMessage={testMessage[provider.id]}
                actionError={cardError[provider.id]}
                onTest={() => void runTest(provider.id)}
                onEdit={() => setForm({ mode: "edit", provider })}
                onDelete={() => void removeProvider(provider)}
              />
            ),
          )}

          {providers.length === 0 && form?.mode !== "add" && (
            <EmptyProviders onAdd={() => setForm({ mode: "add" })} />
          )}

          {form?.mode === "add" ? (
            <ModelKeyForm
              hideTestHint
              onSaved={onSavedProvider}
              onCancel={() => setForm(null)}
            />
          ) : form === null && providers.length > 0 ? (
            <Button
              variant="neutral"
              size="md"
              icon={<Plus size={14} />}
              onClick={() => setForm({ mode: "add" })}
            >
              添加服务商
            </Button>
          ) : null}

          {providers.length > 0 && (
            <DefaultSelectors
              response={response}
              catalog={catalog}
              pending={defaultsPending}
              onSetChat={(pointer) => void applyDefaults({ chat: pointer })}
              onSetBackground={(pointer) =>
                void applyDefaults({ background: pointer })
              }
            />
          )}

          <InfoNote />
        </div>
      )}

      {hasLocalEngine() && <LocalEngineToggle />}
    </div>
  );
}

function providerName(provider: LlmProviderView): string {
  return provider.label?.trim() || hostFromBaseUrl(provider.base_url);
}

function hostFromBaseUrl(url: string | null | undefined): string {
  const trimmed = url?.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed).host;
  } catch {
    return trimmed;
  }
}

/** 平台额度卡（部署开启平台模型时，只读）。 */
function PlatformQuotaCard({ response }: { response: LlmProvidersResponse }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-border bg-card px-4 py-3">
      <Sparkles size={16} className="mt-0.5 shrink-0 text-primary" />
      <div className="min-w-0 space-y-1">
        <p className="flex items-center gap-2 text-sm text-foreground">
          平台额度
          <span className="rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
            无需配置
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          {response.free_tier_active
            ? "当前用平台免费额度运行，无需接入自己的模型；"
            : "未接入自己的模型时，对话默认走平台额度运行；"}
          接入下方服务商后可切换到自己的模型（按你的端点自担费用）。
        </p>
        {response.platform_model && (
          <p className="font-mono text-xs text-muted-foreground">
            默认平台模型 {response.platform_model}
          </p>
        )}
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  message,
  testing,
}: {
  status: string;
  message?: string | null;
  testing?: boolean;
}) {
  if (testing) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
        测试中…
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="flex items-center gap-1.5 text-xs text-success">
        <CheckCircle2 size={14} />
        连接正常
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex items-center gap-1.5 text-xs text-destructive">
        <XCircle size={14} />
        {message ?? "连接失败"}
      </span>
    );
  }
  return <span className="text-xs text-muted-foreground">未测试</span>;
}

function ProviderCard({
  provider,
  testing,
  testMessage,
  actionError,
  onTest,
  onEdit,
  onDelete,
}: {
  provider: LlmProviderView;
  testing: boolean;
  testMessage?: string | null;
  actionError?: string | null;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const host = hostFromBaseUrl(provider.base_url);
  const busy = testing;
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium text-foreground">
              {providerName(provider)}
            </p>
            {provider.is_default_chat && <DefaultBadge>聊天默认</DefaultBadge>}
            {provider.is_default_background && (
              <DefaultBadge>后台默认</DefaultBadge>
            )}
          </div>
          {host && (
            <p className="truncate font-mono text-xs text-muted-foreground">
              {host}
            </p>
          )}
          <p className="font-mono text-sm text-foreground">
            {provider.masked_key ?? "已配置"}
          </p>
          <p className="font-mono text-xs text-foreground">
            默认模型 {provider.default_model}
          </p>
          {(provider.price_cache_miss || provider.price_output) && (
            <p className="text-xs text-muted-foreground">
              单价 输入 {provider.price_cache_miss ?? "—"} / 输出{" "}
              {provider.price_output ?? "—"}
              {provider.price_cache_hit
                ? ` / 缓存 ${provider.price_cache_hit}`
                : ""}{" "}
              USD/1M
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <StatusBadge
              status={provider.status}
              message={testMessage}
              testing={testing}
            />
            <ToolsCapabilityBadge supportsTools={provider.supports_tools} />
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
          <Button
            variant="neutral"
            size="md"
            disabled={busy}
            icon={
              testing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : undefined
            }
            onClick={onTest}
          >
            测试连接
          </Button>
          <Button variant="neutral" size="md" disabled={busy} onClick={onEdit}>
            编辑
          </Button>
          <Button variant="danger" size="md" disabled={busy} onClick={onDelete}>
            删除
          </Button>
        </div>
      </div>
      {actionError && (
        <p className="mt-3 text-xs text-destructive">{actionError}</p>
      )}
    </div>
  );
}

function DefaultBadge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-primary/10 px-1 py-0.5 text-xs text-primary">
      {children}
    </span>
  );
}

function EmptyProviders({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-12 text-center">
      <p className="text-sm text-muted-foreground">
        还没有接入任何服务商。接入后，你端点发现的模型会出现在聊天框的模型选择器中。
      </p>
      <Button size="md" icon={<Plus size={14} />} onClick={onAdd}>
        添加服务商
      </Button>
    </div>
  );
}

/**
 * 账号默认模型与后台任务模型两个跨服务商选择器（按服务商分组）。设账号级 chat / 后台默认指针
 * `(provider_id, model)`；后台可选「跟随聊天默认」清除。
 */
function DefaultSelectors({
  response,
  catalog,
  pending,
  onSetChat,
  onSetBackground,
}: {
  response: LlmProvidersResponse;
  catalog: ReturnType<typeof useModels>["data"];
  pending: boolean;
  onSetChat: (pointer: { provider_id: string; model: string }) => void;
  onSetBackground: (
    pointer: { provider_id: string; model: string } | null,
  ) => void;
}) {
  const groups = buildDefaultProviderGroups(
    response.providers,
    catalog,
    response.default_chat,
    response.default_background,
  );

  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <p className="text-sm font-medium text-foreground">账号默认模型</p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        聊天与后台任务（标题、记忆等）分别使用哪个服务商的模型，可跨服务商选择。
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block" htmlFor="account-default-chat">
          <span className="text-xs text-muted-foreground">聊天默认</span>
          <ProviderModelSelect
            id="account-default-chat"
            groups={groups}
            value={pointerValue(response.default_chat)}
            disabled={pending}
            onChange={(value) => {
              const pointer = decodePointer(value);
              if (pointer) onSetChat(pointer);
            }}
          />
        </label>
        <label className="block" htmlFor="account-default-background">
          <span className="text-xs text-muted-foreground">后台任务模型</span>
          <ProviderModelSelect
            id="account-default-background"
            groups={groups}
            value={pointerValue(response.default_background)}
            disabled={pending}
            followLabel="跟随聊天默认"
            onChange={(value) => onSetBackground(decodePointer(value))}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            用于标题、记忆等后台任务的便宜模型；留空则跟随聊天默认。
          </p>
        </label>
      </div>
    </div>
  );
}

function ProviderModelSelect({
  id,
  groups,
  value,
  disabled,
  followLabel,
  onChange,
}: {
  id?: string;
  groups: DefaultProviderGroup[];
  value: string;
  disabled?: boolean;
  /** When set, offer an empty「跟随」option (background selector). */
  followLabel?: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="mt-1 h-8 w-full rounded-lg border border-input bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
    >
      {followLabel !== undefined ? (
        <option value="">{followLabel}</option>
      ) : (
        value === "" && (
          <option value="" disabled>
            选择模型
          </option>
        )
      )}
      {groups.map((group) => (
        <optgroup key={group.providerId} label={group.providerLabel}>
          {group.models.map((m) => (
            <option
              key={m.model}
              value={encodePointer(group.providerId, m.model)}
            >
              {m.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

function LocalEngineToggle() {
  const enabled = useUIStore((s) => s.sidecarEnabled);
  const setEnabled = useUIStore((s) => s.setSidecarEnabled);
  const onToggle = (v: boolean): void => {
    setEnabled(v);
    if (v) clearSidecarHealth();
  };
  return (
    <div className="mt-4 flex items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm text-foreground">本地引擎</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          绑定本机本地文件夹的对话默认在你的电脑上运行（直连本地磁盘、更快），启动失败会自动切回
          云端。裸聊与云端项目仍走云；AI
          推理仍在云端，断网时不可用。关闭后全部走云端。
        </p>
      </div>
      <Switch checked={enabled} onCheckedChange={onToggle} label="本地引擎" />
    </div>
  );
}

function InfoNote() {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-border bg-muted/30 px-4 py-3">
      <ShieldCheck
        size={16}
        className="mt-0.5 shrink-0 text-muted-foreground"
      />
      <p className="text-xs text-muted-foreground">
        你的 Key 仅用于你自己的对话，经 AES-256-GCM 加密存储，服务端只显示后 4
        位、不会回传完整内容。聊天、委派、辩论均使用此处配置的模型；平台只统计
        token 用量、不代为计价。
      </p>
    </div>
  );
}
