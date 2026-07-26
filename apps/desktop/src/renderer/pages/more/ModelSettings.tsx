import { modelConfigApiErrorMessage } from "@/components/llm/ModelKeyForm";
import { Button, Card, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useLlmModelProfiles } from "@/hooks/useLlmModelProfiles";
import { useLlmProviders } from "@/hooks/useLlmProviders";
import { useModels } from "@/hooks/useModels";
import {
  type DefaultProviderGroup,
  buildDefaultProviderGroups,
  decodePointer,
  encodePointer,
  pointerValue,
} from "@/lib/llmDefaults";
import {
  llmModelProfileKeys,
  llmProviderKeys,
  modelKeys,
} from "@/lib/queryKeys";
import { notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  type CreateLlmModelProfileInput,
  type LlmModelProfileView,
  type ModelProfileSlot,
  createLlmModelProfile,
  deleteLlmModelProfile,
  profileSlotSummary,
  setDefaultLlmModelProfile,
  updateLlmModelProfile,
} from "@/services/llmModelProfiles";
import type { LlmProviderView } from "@/services/llmProviders";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Plus,
  Star,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SettingsHeader } from "./SettingsHeader";

/**
 * 模型 (/more/model) — 账号默认组合 + 组合 CRUD。
 *
 * 组合 = `{ main, worker?, background? }`；账号默认组合与会话引用见
 * `/v1/users/me/llm-model-profiles`。凭据与测连见 `/more/providers`。
 */
export function ModelSettings() {
  const { data: response, isLoading, isError, error } = useLlmProviders();
  const { data: catalog } = useModels();
  const queryClient = useQueryClient();

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: llmProviderKeys.list });
    void queryClient.invalidateQueries({ queryKey: modelKeys.catalog });
    void queryClient.invalidateQueries({ queryKey: llmModelProfileKeys.list });
  };

  const providers = response?.providers ?? [];
  const platformAvailable = response?.platform_available ?? false;
  const platformMode = response?.billing_mode === "platform";
  const canEditProfiles = providers.length > 0 || platformAvailable;

  return (
    <div>
      <SettingsHeader
        title="模型"
        description={
          platformMode || platformAvailable
            ? "选择账号默认组合（主模型 + 可选 Worker / 后台）。可用平台额度直接对话，也可接入服务商。"
            : "选择账号默认组合（主模型 + 可选 Worker / 后台）。需先接入服务商。"
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
          <PlatformStatusLine
            platformAvailable={platformAvailable}
            freeTierActive={response.free_tier_active}
            platformModel={response.platform_model ?? null}
            hasProviders={providers.length > 0}
          />

          {canEditProfiles ? (
            <ModelProfilesSection
              providers={providers}
              catalog={catalog}
              onChanged={refresh}
            />
          ) : (
            <EmptyProfilesCta />
          )}
        </div>
      )}
    </div>
  );
}

function EmptyProfilesCta() {
  const navigate = useNavigate();
  return (
    <Card className="flex flex-col items-center justify-center gap-3 border-dashed py-8 text-center">
      <p className="text-sm text-muted-foreground">
        还没有可用模型。先接入服务商。
      </p>
      <Button
        size="sm"
        icon={<Plus size={14} />}
        onClick={() => navigate("/more/providers")}
      >
        接入服务商
      </Button>
    </Card>
  );
}

function PlatformStatusLine({
  platformAvailable,
  freeTierActive,
  platformModel,
  hasProviders,
}: {
  platformAvailable: boolean;
  freeTierActive: boolean;
  platformModel: string | null;
  hasProviders: boolean;
}) {
  if (!platformAvailable && hasProviders) {
    return (
      <p className="text-xs text-muted-foreground">
        已接入服务商。{" "}
        <Link
          to="/more/providers"
          className="text-primary underline-offset-2 hover:underline"
        >
          管理服务商
        </Link>
      </p>
    );
  }
  if (!platformAvailable) return null;

  const status = freeTierActive ? "可用平台免费额度" : "可用平台额度";
  const modelHint = platformModel ? ` · ${platformModel}` : "";

  return (
    <p className="text-xs text-muted-foreground">
      {status}
      {modelHint}。{" "}
      <Link
        to="/more/providers"
        className="text-primary underline-offset-2 hover:underline"
      >
        {hasProviders ? "管理服务商" : "接入服务商"}
      </Link>
    </p>
  );
}

/**
 * 模型组合列表 + 编辑：主必填；Worker / 后台默认跟随、可展开选模型。
 * 系统预置不可删，可设默认 / 复制为用户组合；用户组合可新建 / 改名 / 删。
 */
function ModelProfilesSection({
  providers,
  catalog,
  onChanged,
}: {
  providers: LlmProviderView[];
  catalog: ReturnType<typeof useModels>["data"];
  onChanged: () => void;
}) {
  const {
    data: profileList,
    isLoading,
    isError,
    error,
  } = useLlmModelProfiles();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const catalogModels = catalog?.models ?? [];
  const manageable = useMemo(
    () =>
      (profileList?.data ?? []).filter(
        (p) => p.kind === "system" || p.kind === "user",
      ),
    [profileList],
  );

  const groups = buildDefaultProviderGroups(
    providers,
    catalog,
    ...manageable.flatMap((p) => [p.main, p.worker, p.background]),
  );

  const seedMain = (): ModelProfileSlot | null => {
    const cur = catalog?.current;
    if (cur?.id) {
      return {
        origin: cur.origin,
        provider_id: cur.provider_id ?? null,
        model: cur.id,
      };
    }
    const first = catalogModels.find((m) => m.available !== false);
    if (!first) return null;
    return {
      origin: first.origin,
      provider_id: first.provider_id ?? null,
      model: first.id,
    };
  };

  const withPending = async (fn: () => Promise<void>) => {
    setPending(true);
    setActionError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setActionError(modelConfigApiErrorMessage(e, "操作失败，请重试"));
    } finally {
      setPending(false);
    }
  };

  const onSetDefault = (profile: LlmModelProfileView) =>
    withPending(async () => {
      await setDefaultLlmModelProfile(profile.id);
      notifySuccess(`已将「${profile.name}」设为默认组合`);
    });

  const onDelete = (profile: LlmModelProfileView) => {
    if (profile.kind !== "user") return;
    if (
      !window.confirm(
        `删除组合「${profile.name}」？引用该组合的会话将回落账号默认。`,
      )
    )
      return;
    void withPending(async () => {
      await deleteLlmModelProfile(profile.id);
      if (editingId === profile.id) setEditingId(null);
      notifySuccess(`已删除「${profile.name}」`);
    });
  };

  const onCopy = (profile: LlmModelProfileView) =>
    withPending(async () => {
      const created = await createLlmModelProfile({
        name: `${profile.name} 副本`,
        main: profile.main,
        worker: profile.worker ?? null,
        background: profile.background ?? null,
        set_as_default: false,
      });
      setEditingId(created.id);
      setCreating(false);
      notifySuccess(`已复制为「${created.name}」`);
    });

  const onCreate = () => {
    const main = seedMain();
    if (!main) {
      setActionError("暂无可用模型，请先接入服务商或等待平台目录加载");
      return;
    }
    setCreating(true);
    setEditingId(null);
  };

  const onSaveCreate = (draft: ProfileDraft) =>
    withPending(async () => {
      if (!draft.main) throw new Error("主模型必填");
      const created = await createLlmModelProfile({
        name: draft.name.trim() || "未命名组合",
        main: draft.main,
        worker: draft.worker,
        background: draft.background,
        set_as_default: false,
      } satisfies CreateLlmModelProfileInput);
      setCreating(false);
      setEditingId(null);
      notifySuccess(`已创建「${created.name}」`);
    });

  const onSaveEdit = (profile: LlmModelProfileView, draft: ProfileDraft) =>
    withPending(async () => {
      if (profile.kind !== "user") return;
      if (!draft.main) throw new Error("主模型必填");
      const name = draft.name.trim() || profile.name;
      await updateLlmModelProfile(profile.id, {
        name,
        main: draft.main,
        worker: draft.worker,
        background: draft.background,
      });
      setEditingId(null);
      notifySuccess(`已保存「${name}」`);
    });

  return (
    <section>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">模型组合</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            主模型必填；Worker / 后台可留空跟随。改定义后下一回合生效。
          </p>
        </div>
        <Button
          variant="neutral"
          size="sm"
          icon={<Plus size={14} />}
          disabled={pending}
          onClick={onCreate}
        >
          新建
        </Button>
      </div>

      {isLoading ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          加载组合…
        </div>
      ) : isError ? (
        <p className="mt-3 text-xs text-destructive">
          {modelConfigApiErrorMessage(error, "加载组合失败")}
        </p>
      ) : (
        <div className="mt-3 space-y-2">
          {creating && (
            <ProfileEditor
              title="新建组合"
              groups={groups}
              initial={{
                name: "未命名组合",
                main: seedMain(),
                worker: null,
                background: null,
              }}
              pending={pending}
              onCancel={() => setCreating(false)}
              onSave={(draft) => void onSaveCreate(draft)}
            />
          )}

          {manageable.map((profile) =>
            editingId === profile.id && profile.kind === "user" ? (
              <ProfileEditor
                key={profile.id}
                title={`编辑「${profile.name}」`}
                groups={groups}
                initial={{
                  name: profile.name,
                  main: profile.main,
                  worker: profile.worker ?? null,
                  background: profile.background ?? null,
                }}
                pending={pending}
                onCancel={() => setEditingId(null)}
                onSave={(draft) => void onSaveEdit(profile, draft)}
              />
            ) : (
              <ProfileListRow
                key={profile.id}
                profile={profile}
                summary={profileSlotSummary(profile, catalogModels)}
                pending={pending}
                onEdit={() => {
                  setCreating(false);
                  setEditingId(profile.id);
                }}
                onSetDefault={() => void onSetDefault(profile)}
                onCopy={() => void onCopy(profile)}
                onDelete={() => onDelete(profile)}
              />
            ),
          )}

          {manageable.length === 0 && !creating && (
            <p className="py-4 text-center text-xs text-muted-foreground">
              暂无组合
            </p>
          )}
        </div>
      )}

      {actionError && (
        <p className="mt-3 text-xs text-destructive">{actionError}</p>
      )}
    </section>
  );
}

type ProfileDraft = {
  name: string;
  main: ModelProfileSlot | null;
  worker: ModelProfileSlot | null;
  background: ModelProfileSlot | null;
};

function ProfileListRow({
  profile,
  summary,
  pending,
  onEdit,
  onSetDefault,
  onCopy,
  onDelete,
}: {
  profile: LlmModelProfileView;
  summary: string;
  pending: boolean;
  onEdit: () => void;
  onSetDefault: () => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const isUser = profile.kind === "user";
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2",
        profile.is_default ? "border-primary/40 bg-primary/5" : "border-border",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm text-foreground">{profile.name}</p>
            {profile.is_default && (
              <span className="rounded bg-primary/10 px-1 py-0.5 text-xs text-primary">
                默认组合
              </span>
            )}
            {profile.kind === "system" && (
              <span className="rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
                预置
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {summary}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {!profile.is_default && (
            <SimpleTooltip label="设为默认">
              <IconButton
                size="sm"
                aria-label="设为默认"
                disabled={pending}
                onClick={onSetDefault}
              >
                <Star size={14} />
              </IconButton>
            </SimpleTooltip>
          )}
          <SimpleTooltip label="复制">
            <IconButton
              size="sm"
              aria-label="复制"
              disabled={pending}
              onClick={onCopy}
            >
              <Copy size={14} />
            </IconButton>
          </SimpleTooltip>
          {isUser ? (
            <>
              <Button
                variant="neutral"
                size="sm"
                disabled={pending}
                onClick={onEdit}
              >
                编辑
              </Button>
              <SimpleTooltip label="删除">
                <IconButton
                  size="sm"
                  aria-label="删除"
                  disabled={pending}
                  onClick={onDelete}
                >
                  <Trash2 size={14} />
                </IconButton>
              </SimpleTooltip>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ProfileEditor({
  title,
  groups,
  initial,
  pending,
  onCancel,
  onSave,
}: {
  title: string;
  groups: DefaultProviderGroup[];
  initial: ProfileDraft;
  pending: boolean;
  onCancel: () => void;
  onSave: (draft: ProfileDraft) => void;
}) {
  const [name, setName] = useState(initial.name);
  const [main, setMain] = useState(initial.main);
  const [worker, setWorker] = useState(initial.worker);
  const [background, setBackground] = useState(initial.background);
  const [workerOpen, setWorkerOpen] = useState(!!initial.worker);
  const [bgOpen, setBgOpen] = useState(!!initial.background);

  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/20 px-3 py-3">
      <p className="text-sm font-medium text-foreground">{title}</p>
      <label className="block" htmlFor="profile-name">
        <span className="text-xs text-muted-foreground">名称</span>
        <input
          id="profile-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={pending}
          className="mt-1 h-8 w-full rounded-lg border border-input bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
        />
      </label>
      <label className="block" htmlFor="profile-main">
        <span className="text-xs text-muted-foreground">主模型（必填）</span>
        <ProviderModelSelect
          id="profile-main"
          groups={groups}
          value={pointerValue(main)}
          disabled={pending}
          onChange={(value) => setMain(decodePointer(value))}
        />
      </label>

      <OptionalSlot
        label="Worker 模型"
        hint="组队队员用；辩论用主模型。留空则跟随主模型。"
        open={workerOpen}
        onToggle={() => {
          setWorkerOpen((v) => {
            if (v) setWorker(null);
            return !v;
          });
        }}
        value={pointerValue(worker)}
        groups={groups}
        pending={pending}
        followLabel="跟随主模型"
        onChange={(value) => setWorker(decodePointer(value))}
      />

      <OptionalSlot
        label="后台任务模型"
        hint="标题、记忆等后台任务；留空则跟随主模型。"
        open={bgOpen}
        onToggle={() => {
          setBgOpen((v) => {
            if (v) setBackground(null);
            return !v;
          });
        }}
        value={pointerValue(background)}
        groups={groups}
        pending={pending}
        followLabel="跟随主模型"
        onChange={(value) => setBackground(decodePointer(value))}
      />

      <div className="flex justify-end gap-2 pt-1">
        <Button
          variant="neutral"
          size="sm"
          disabled={pending}
          onClick={onCancel}
        >
          取消
        </Button>
        <Button
          size="sm"
          disabled={pending || !main}
          icon={
            pending ? <Loader2 size={14} className="animate-spin" /> : undefined
          }
          onClick={() =>
            onSave({
              name,
              main,
              worker: workerOpen ? worker : null,
              background: bgOpen ? background : null,
            })
          }
        >
          保存
        </Button>
      </div>
    </div>
  );
}

function OptionalSlot({
  label,
  hint,
  open,
  onToggle,
  value,
  groups,
  pending,
  followLabel,
  onChange,
}: {
  label: string;
  hint: string;
  open: boolean;
  onToggle: () => void;
  value: string;
  groups: DefaultProviderGroup[];
  pending: boolean;
  followLabel: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-1 text-left text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>{label}</span>
        {!open && <span className="ml-1 opacity-70">（{followLabel}）</span>}
      </button>
      {open ? (
        <>
          <ProviderModelSelect
            groups={groups}
            value={value}
            disabled={pending}
            followLabel={followLabel}
            onChange={onChange}
          />
          <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
        </>
      ) : null}
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
