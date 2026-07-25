import {
  ModelKeyForm,
  modelConfigApiErrorMessage,
} from "@/components/llm/ModelKeyForm";
import { ToolsCapabilityBadge } from "@/components/llm/ToolsCapabilityBadge";
import { Button, Card } from "@/components/ui";
import { useLlmProviders } from "@/hooks/useLlmProviders";
import {
  llmModelProfileKeys,
  llmProviderKeys,
  modelKeys,
} from "@/lib/queryKeys";
import {
  type LlmProviderView,
  type LlmProvidersResponse,
  deleteLlmProvider,
  testLlmProvider,
} from "@/services/llmProviders";
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
 * 服务商 (/more/providers) — 平台额度说明 + BYOK 列表 / 表单 / 测连 + 安全说明。
 */
export function ProviderSettings() {
  const { data: response, isLoading, isError, error } = useLlmProviders();
  const queryClient = useQueryClient();

  const [form, setForm] = useState<
    { mode: "add" } | { mode: "edit"; provider: LlmProviderView } | null
  >(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<Record<string, string | null>>(
    {},
  );
  const [cardError, setCardError] = useState<Record<string, string | null>>({});

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: llmProviderKeys.list });
    void queryClient.invalidateQueries({ queryKey: modelKeys.catalog });
    void queryClient.invalidateQueries({ queryKey: llmModelProfileKeys.list });
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
      refresh();
    }
  };

  const onSavedProvider = (view: LlmProviderView) => {
    setForm(null);
    refresh();
    void runTest(view.id);
  };

  const removeProvider = async (provider: LlmProviderView) => {
    if (!response) return;
    const remaining = response.providers.length - 1;
    const softFallback = remaining > 0 || response.platform_available;
    const confirmMsg = softFallback
      ? `删除服务商「${providerName(provider)}」？组合槽位会自动回落到其他服务商或平台额度，不会中断对话。`
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

  const platformMode = response?.billing_mode === "platform";
  const providers = response?.providers ?? [];

  return (
    <div>
      <SettingsHeader
        title="服务商"
        description={
          platformMode
            ? "接入 OpenAI 兼容服务商（可多个）。不接入也可用平台额度。"
            : "接入 OpenAI 兼容服务商（可多个）。未接入则无法对话。"
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
            <PlatformStatusLine response={response} />
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
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setForm({ mode: "add" })}
            >
              添加服务商
            </Button>
          ) : null}

          <InfoNote />
        </div>
      )}
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

function PlatformStatusLine({ response }: { response: LlmProvidersResponse }) {
  const status = response.free_tier_active
    ? "当前用平台免费额度，无需接入自己的模型"
    : "未接入自己的模型时，对话默认走平台额度";
  return (
    <div className="flex items-start gap-2 text-sm text-muted-foreground">
      <Sparkles size={16} className="mt-0.5 shrink-0 text-primary" />
      <p className="min-w-0">
        <span className="text-foreground">平台额度</span>
        <span className="mx-1.5 rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
          无需配置
        </span>
        <span className="text-xs">
          {status}
          {response.platform_model
            ? ` · 平台模型 ${response.platform_model}`
            : ""}
          。接入后可在组合里选用自己的模型。
        </span>
      </p>
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
  const metaParts = [
    host || null,
    provider.masked_key ?? "已配置",
    `回落模型 ${provider.default_model}`,
  ].filter(Boolean);

  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium text-foreground">
              {providerName(provider)}
            </p>
            <StatusBadge
              status={provider.status}
              message={testMessage}
              testing={testing}
            />
            <ToolsCapabilityBadge supportsTools={provider.supports_tools} />
          </div>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {metaParts.join(" · ")}
          </p>
          {(provider.price_cache_miss || provider.price_output) && (
            <p className="text-xs text-muted-foreground/80">
              单价 输入 {provider.price_cache_miss ?? "—"} / 输出{" "}
              {provider.price_output ?? "—"}
              {provider.price_cache_hit
                ? ` / 缓存 ${provider.price_cache_hit}`
                : ""}{" "}
              USD/1M
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="neutral"
            size="sm"
            disabled={busy}
            icon={
              testing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : undefined
            }
            onClick={onTest}
          >
            测试
          </Button>
          <Button variant="neutral" size="sm" disabled={busy} onClick={onEdit}>
            编辑
          </Button>
          <Button variant="danger" size="sm" disabled={busy} onClick={onDelete}>
            删除
          </Button>
        </div>
      </div>
      {actionError && (
        <p className="mt-2 text-xs text-destructive">{actionError}</p>
      )}
    </div>
  );
}

function EmptyProviders({ onAdd }: { onAdd: () => void }) {
  return (
    <Card className="flex flex-col items-center justify-center gap-3 border-dashed py-8 text-center">
      <p className="text-sm text-muted-foreground">还没有接入服务商。</p>
      <Button size="sm" icon={<Plus size={14} />} onClick={onAdd}>
        添加服务商
      </Button>
    </Card>
  );
}

function InfoNote() {
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <ShieldCheck
        size={14}
        className="mt-0.5 shrink-0 text-muted-foreground"
      />
      <span>
        Key 经 AES-256-GCM 加密存储，服务端只显示后 4 位。对话使用「设置 ·
        模型」里的组合；平台只统计 token，不代为计价。
      </span>
    </p>
  );
}
