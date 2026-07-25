import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  patchConversationCache,
  useConversations,
} from "@/hooks/useConversations";
import { useLlmModelProfiles } from "@/hooks/useLlmModelProfiles";
import { useModels } from "@/hooks/useModels";
import { notifyError, notifySuccess } from "@/lib/toast";
import { setConversationModelProfile } from "@/services/conversations";
import {
  type LlmModelProfileView,
  profileSlotSummary,
  resolveDefaultProfile,
} from "@/services/llmModelProfiles";
import {
  clearLastUsedProfileId,
  getLastUsedProfileId,
  setLastUsedProfileId,
} from "@/services/models";
import type { Conversation } from "@/stores/conversation";
import { useConversationStore } from "@/stores/conversation";
import {
  Bot,
  Check,
  ChevronDown,
  Layers,
  Loader2,
  RotateCcw,
  Settings2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

/**
 * 输入框「模型组合」选择器 — 只选组合 +「跟随账号默认」，不做裸模型列表。
 *
 * 数据源：`GET /v1/users/me/llm-model-profiles`。选择即写：已有会话
 * `PATCH … model_profile_id`；新会话先记草稿 + last_profile_id，首发建会话时继承。
 * 传「跟随账号默认」清除覆盖（`null`）。次要一行只读摘要：主 · Worker。
 */

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2.5 pt-1.5 pb-0.5 text-xs font-medium text-muted-foreground">
      {children}
    </div>
  );
}

function ProfileRow({
  profile,
  selected,
  summary,
  onPick,
}: {
  profile: LlmModelProfileView;
  selected: boolean;
  summary: string;
  onPick: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onPick(profile.id)}
      aria-current={selected ? "true" : undefined}
      className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-1.5 text-left ${
        selected ? "bg-primary/10" : "hover:bg-accent/50"
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm text-foreground">
            {profile.name}
          </span>
          {profile.is_default && (
            <span className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-xs text-primary">
              默认
            </span>
          )}
          {profile.kind === "system" && (
            <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
              预置
            </span>
          )}
        </div>
        {summary && (
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {summary}
          </div>
        )}
      </div>
      {selected && <Check size={14} className="mt-0.5 shrink-0 text-primary" />}
    </button>
  );
}

/** Profiles shown in the picker: system + user (+ current implicit if attached). */
function pickerProfiles(
  all: LlmModelProfileView[],
  attachedId: string | null | undefined,
): LlmModelProfileView[] {
  return all.filter(
    (p) =>
      p.kind === "system" ||
      p.kind === "user" ||
      (p.kind === "implicit" && p.id === attachedId),
  );
}

export function ModelPicker({ disabled }: { disabled?: boolean }) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const conversations = useConversations();
  const {
    data: profileList,
    isLoading,
    isError,
    refetch,
  } = useLlmModelProfiles();
  const { data: catalog } = useModels();
  const navigate = useNavigate();

  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  /** New-chat draft: unset → fall back to last-used; follow → explicit account default; profile → pick. */
  const [draft, setDraft] = useState<
    { kind: "unset" } | { kind: "follow" } | { kind: "profile"; id: string }
  >({ kind: "unset" });
  const rootRef = useRef<HTMLDivElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on conversation switch
  useEffect(() => {
    setDraft({ kind: "unset" });
  }, [conversationId]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const catalogModels = useMemo(() => catalog?.models ?? [], [catalog]);
  const profiles = profileList?.data ?? [];
  const accountDefault = resolveDefaultProfile(profileList);

  const activeConv = conversationId
    ? conversations.find((c: Conversation) => c.id === conversationId)
    : undefined;
  const overrideId = activeConv?.modelProfileId?.trim() || null;

  const isNewChat = !conversationId;
  const lastUsedId = getLastUsedProfileId();
  const validLastUsed =
    lastUsedId && profiles.some((p) => p.id === lastUsedId)
      ? lastUsedId
      : undefined;
  const suggestionId = isNewChat
    ? draft.kind === "profile"
      ? draft.id
      : draft.kind === "follow"
        ? null
        : (validLastUsed ?? null)
    : null;

  /** Explicit pick (override / draft / last-used); null = follow account default. */
  const selectedId = overrideId ?? suggestionId;
  const followingDefault = !selectedId;

  const displayProfile = useMemo(() => {
    if (selectedId) {
      return profiles.find((p) => p.id === selectedId) ?? accountDefault;
    }
    return accountDefault;
  }, [selectedId, profiles, accountDefault]);

  const visibleProfiles = useMemo(
    () => pickerProfiles(profiles, overrideId),
    [profiles, overrideId],
  );

  const systemProfiles = visibleProfiles.filter((p) => p.kind === "system");
  const userProfiles = visibleProfiles.filter(
    (p) => p.kind === "user" || p.kind === "implicit",
  );

  const summary = displayProfile
    ? profileSlotSummary(displayProfile, catalogModels)
    : "";

  const applyProfile = async (profileId: string) => {
    if (disabled || pending) return;
    setLastUsedProfileId(profileId);
    setOpen(false);
    if (!conversationId) {
      setDraft({ kind: "profile", id: profileId });
      return;
    }
    setPending(true);
    try {
      const saved = await setConversationModelProfile(
        conversationId,
        profileId,
      );
      patchConversationCache(conversationId, {
        modelProfileId: saved.modelProfileId ?? null,
      });
      const name = profiles.find((p) => p.id === profileId)?.name ?? profileId;
      notifySuccess(`已切换为「${name}」`);
    } catch (e) {
      notifyError(e, "切换模型组合失败");
    } finally {
      setPending(false);
    }
  };

  const clearOverride = async () => {
    if (disabled || pending) return;
    setOpen(false);
    if (!conversationId) {
      setDraft({ kind: "follow" });
      clearLastUsedProfileId();
      return;
    }
    setPending(true);
    try {
      const saved = await setConversationModelProfile(conversationId, null);
      patchConversationCache(conversationId, {
        modelProfileId: saved.modelProfileId ?? null,
      });
      notifySuccess("已跟随账号默认组合");
    } catch (e) {
      notifyError(e, "重置模型组合失败");
    } finally {
      setPending(false);
    }
  };

  if (isLoading && !displayProfile) {
    return (
      <span className="inline-flex h-8 items-center gap-1 px-2 text-xs text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
      </span>
    );
  }

  const label = displayProfile?.name ?? "选择组合";
  const tooltip = followingDefault
    ? "跟随账号默认组合（当前回合起生效）"
    : "切换本会话使用的模型组合（当前回合起生效）";

  return (
    <div ref={rootRef} className="relative shrink-0">
      <SimpleTooltip label={tooltip}>
        <button
          type="button"
          disabled={disabled || pending}
          onClick={() => setOpen((v) => !v)}
          aria-label={`模型组合：${label}`}
          aria-expanded={open}
          className={`inline-flex min-h-8 max-w-48 flex-col items-start justify-center gap-0 rounded-lg px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground ${
            disabled || pending ? "cursor-not-allowed opacity-60" : ""
          }`}
        >
          <span className="inline-flex max-w-full items-center gap-1">
            {pending ? (
              <Loader2 size={14} className="shrink-0 animate-spin" />
            ) : (
              <Bot size={14} className="shrink-0" />
            )}
            <span className="truncate font-mono">{label}</span>
            <ChevronDown size={12} className="shrink-0 opacity-60" />
          </span>
          {summary && (
            <span className="max-w-full truncate pl-[18px] text-xs opacity-70">
              {summary}
            </span>
          )}
        </button>
      </SimpleTooltip>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1 flex max-h-[22rem] w-72 flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-lg">
          <div className="min-h-0 flex-1 overflow-y-auto p-1">
            {isError ? (
              <div className="px-2.5 py-3 text-xs">
                <p className="text-destructive">加载模型组合失败</p>
                <button
                  type="button"
                  onClick={() => void refetch()}
                  className="mt-1 text-primary hover:underline"
                >
                  重试
                </button>
              </div>
            ) : visibleProfiles.length === 0 ? (
              <div className="px-2.5 py-4 text-xs text-muted-foreground">
                暂无可用组合
              </div>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => void clearOverride()}
                  aria-current={followingDefault ? "true" : undefined}
                  className={`mb-1 flex w-full items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-left text-sm ${
                    followingDefault
                      ? "bg-primary/10 text-foreground"
                      : "text-muted-foreground hover:bg-accent/50"
                  }`}
                >
                  <RotateCcw size={13} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate">跟随账号默认</span>
                  {accountDefault && (
                    <span className="truncate text-xs opacity-70">
                      {accountDefault.name}
                    </span>
                  )}
                  {followingDefault && (
                    <Check size={14} className="shrink-0 text-primary" />
                  )}
                </button>

                {systemProfiles.length > 0 && (
                  <div>
                    <GroupLabel>系统预置</GroupLabel>
                    {systemProfiles.map((p) => (
                      <ProfileRow
                        key={p.id}
                        profile={p}
                        selected={selectedId === p.id}
                        summary={profileSlotSummary(p, catalogModels)}
                        onPick={applyProfile}
                      />
                    ))}
                  </div>
                )}

                {userProfiles.length > 0 && (
                  <div>
                    <GroupLabel>我的组合</GroupLabel>
                    {userProfiles.map((p) => (
                      <ProfileRow
                        key={p.id}
                        profile={p}
                        selected={selectedId === p.id}
                        summary={profileSlotSummary(p, catalogModels)}
                        onPick={applyProfile}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              setOpen(false);
              navigate("/more/model");
            }}
            className="flex items-center gap-1.5 border-t border-border px-2.5 py-2 text-left text-xs text-primary hover:bg-accent/40"
          >
            <Settings2 size={13} className="shrink-0" />
            管理组合…
            <Layers size={12} className="ml-auto shrink-0 opacity-60" />
          </button>
        </div>
      )}
    </div>
  );
}
