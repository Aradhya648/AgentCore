import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  patchConversationCache,
  useConversations,
} from "@/hooks/useConversations";
import { useModels } from "@/hooks/useModels";
import { notifyError, notifySuccess } from "@/lib/toast";
import { setConversationModel } from "@/services/conversations";
import {
  type ModelCapability,
  type ModelCatalog,
  type ModelCatalogItem,
  type ModelPriceCard,
  type ModelSelection,
  findCatalogItem,
  getLastUsedModel,
  modelItemKey,
  setLastUsedModel,
} from "@/services/models";
import type { Conversation } from "@/stores/conversation";
import { useConversationStore } from "@/stores/conversation";
import { useTurnModelStore } from "@/stores/turnModel";
import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  Eye,
  KeyRound,
  Loader2,
  Lock,
  type LucideIcon,
  RotateCcw,
  Search,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

/**
 * 输入框「模型选择器」(会话级模型切换) — 由只读徽章升级而来的下拉。
 *
 * 数据源**只**是模型目录 `GET /v1/users/me/models`（{@link useModels}），按来源分 BYOK /
 * 平台两大组：BYOK 组内**按服务商（provider_label）分组**（同一模型 id 可在多个服务商下
 * 重复出现，靠服务商标签消歧），平台组**扁平平铺**（不再按厂商分二级）；标注能力、上下文、
 * 单价；不可用模型置灰并引导「接入自己的 Key 解锁」。选择键为 `(id, origin, provider_id)` 三元组。
 *
 * 选择即写：已有会话 `PATCH /v1/conversations/{id}` 固定本会话模型（当前回合起生效），并把
 * 结果补进会话目录缓存；新会话（尚无 id）先记为草稿 + 落 last-used，等首发建会话时由
 * 输入框继承。传「跟随账号默认」清除覆盖。
 *
 * 仍如实回显 {@link useTurnModelStore} 记录的「上一回合实际运行模型」——会话无显式覆盖时，
 * 按钮优先显示真的跑过的模型（本机 sidecar dev 回退是唯一分叉点），分叉时 tooltip 点明。
 */

const CAPABILITY_META: Record<
  ModelCapability,
  { icon: LucideIcon; label: string }
> = {
  vision: { icon: Eye, label: "识图" },
  tools: { icon: Wrench, label: "工具" },
  reasoning: { icon: Brain, label: "推理" },
};
const CAPABILITY_ORDER: ModelCapability[] = ["vision", "tools", "reasoning"];
const KNOWN_CAPABILITIES = new Set<string>(CAPABILITY_ORDER);

const ORIGIN_GROUP_LABEL: Record<ModelCatalogItem["origin"], string> = {
  byok: "自带 Key",
  platform: "平台模型",
};

/** Context window as a compact display hint (`128000` → `128K`). */
function formatContext(n?: number | null): string | null {
  if (!n || n <= 0) return null;
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}K`;
  return `${n}`;
}

/** Compact「输入/输出」price (USD per 1M tokens); null when unpriced. */
function formatPrice(p?: ModelPriceCard | null): string | null {
  if (!p) return null;
  const input = p.cache_miss?.trim();
  const output = p.output?.trim();
  if (!input && !output) return null;
  return `$${input ?? "—"}/$${output ?? "—"}`;
}

function resolveConversationSelection(
  conv: Conversation | undefined,
  catalog: ModelCatalog | undefined,
): ModelSelection | undefined {
  const id = conv?.model?.trim();
  if (!id) return undefined;
  if (conv?.modelOrigin) {
    return {
      id,
      origin: conv.modelOrigin,
      providerId: conv.modelProviderId ?? null,
    };
  }
  // Legacy rows without an origin: infer from the catalog (prefer the available one).
  const matches = catalog?.models.filter((m) => m.id === id) ?? [];
  const preferred = matches.find((m) => m.available) ?? matches[0];
  return preferred
    ? {
        id,
        origin: preferred.origin,
        providerId: preferred.provider_id ?? null,
      }
    : undefined;
}

function selectionsEqual(
  a: ModelSelection | undefined,
  b: ModelSelection | undefined,
): boolean {
  return (
    !!a &&
    !!b &&
    a.id === b.id &&
    a.origin === b.origin &&
    (a.providerId ?? null) === (b.providerId ?? null)
  );
}

function CapabilityIcons({ capabilities }: { capabilities?: string[] }) {
  const caps = (capabilities ?? []).filter((c) =>
    KNOWN_CAPABILITIES.has(c),
  ) as ModelCapability[];
  if (caps.length === 0) return null;
  return (
    <span className="flex items-center gap-0.5">
      {CAPABILITY_ORDER.filter((c) => caps.includes(c)).map((c) => {
        const { icon: Icon, label } = CAPABILITY_META[c];
        return (
          <span key={c} title={label} className="text-muted-foreground">
            <Icon size={12} />
          </span>
        );
      })}
    </span>
  );
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-2.5 pt-1.5 pb-0.5 text-xs font-medium text-muted-foreground">
      {children}
    </div>
  );
}

function ModelRow({
  item,
  selected,
  showPlatformBadge,
  onPick,
}: {
  item: ModelCatalogItem;
  selected: boolean;
  showPlatformBadge?: boolean;
  onPick: (sel: ModelSelection) => void;
}) {
  const ctx = formatContext(item.context_length);
  const price = formatPrice(item.price);
  const unavailable = item.available === false;
  return (
    <button
      type="button"
      onClick={() =>
        onPick({
          id: item.id,
          origin: item.origin,
          providerId: item.provider_id ?? null,
        })
      }
      aria-current={selected ? "true" : undefined}
      className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-1.5 text-left ${
        selected ? "bg-primary/10" : "hover:bg-accent/50"
      } ${unavailable ? "opacity-60" : ""}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm text-foreground">
            {item.display_name}
          </span>
          <CapabilityIcons capabilities={item.capabilities} />
          {showPlatformBadge && (
            <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
              平台额度
            </span>
          )}
          {unavailable && (
            <Lock size={11} className="shrink-0 text-muted-foreground" />
          )}
        </div>
        {(unavailable || ctx || price) && (
          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
            {unavailable ? (
              <span>接入自己的 Key 解锁</span>
            ) : (
              <>
                {ctx && <span title="上下文长度">{ctx}</span>}
                {price && (
                  <span title="输入 / 输出，每百万 token（USD）">{price}</span>
                )}
              </>
            )}
          </div>
        )}
      </div>
      {selected && <Check size={14} className="mt-0.5 shrink-0 text-primary" />}
    </button>
  );
}

/** Sort rows available-first then alphabetically by display name. */
function sortRows(items: ModelCatalogItem[]): ModelCatalogItem[] {
  return [...items].sort((a, b) => {
    if (a.available !== b.available) return a.available ? -1 : 1;
    return a.display_name.localeCompare(b.display_name);
  });
}

/** Group a section's rows by a key (BYOK: 服务商 provider_label),
 * available-first then alpha within each group, groups sorted by label. */
function groupItems(
  items: ModelCatalogItem[],
  keyOf: (m: ModelCatalogItem) => string,
): [string, ModelCatalogItem[]][] {
  const map = new Map<string, ModelCatalogItem[]>();
  for (const m of items) {
    const key = keyOf(m);
    const arr = map.get(key) ?? [];
    arr.push(m);
    map.set(key, arr);
  }
  for (const [key, arr] of map) {
    map.set(key, sortRows(arr));
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

/** BYOK 组按服务商分组：provider_label 优先，缺省回落厂商名。 */
function byokGroupKey(m: ModelCatalogItem): string {
  return m.provider_label?.trim() || m.vendor;
}

export function ModelPicker({ disabled }: { disabled?: boolean }) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const conversations = useConversations();
  const { data: catalog, isLoading, isError, refetch } = useModels();
  const lastTurnModel = useTurnModelStore((s) =>
    conversationId ? s.byConversation[conversationId] : undefined,
  );
  const navigate = useNavigate();

  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [query, setQuery] = useState("");
  const [draftSelection, setDraftSelection] = useState<ModelSelection | null>(
    null,
  );
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on conversation switch
  useEffect(() => {
    setDraftSelection(null);
    setQuery("");
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

  useEffect(() => {
    if (open) requestAnimationFrame(() => searchRef.current?.focus());
  }, [open]);

  const models = useMemo(() => catalog?.models ?? [], [catalog]);
  const byKey = useMemo(
    () => new Map(models.map((m) => [modelItemKey(m), m])),
    [models],
  );

  const idsWithBothOrigins = useMemo(() => {
    const byId = new Map<string, Set<string>>();
    for (const m of models) {
      const set = byId.get(m.id) ?? new Set();
      set.add(m.origin);
      byId.set(m.id, set);
    }
    return new Set(
      [...byId.entries()]
        .filter(([, origins]) => origins.size > 1)
        .map(([id]) => id),
    );
  }, [models]);

  const activeConv = conversationId
    ? conversations.find((c) => c.id === conversationId)
    : undefined;
  const overrideSelection = resolveConversationSelection(activeConv, catalog);

  const isNewChat = !conversationId;
  const lastUsed = getLastUsedModel() ?? undefined;
  const validLastUsed =
    lastUsed && findCatalogItem(models, lastUsed)?.available !== false
      ? lastUsed
      : undefined;
  const suggestion = isNewChat ? (draftSelection ?? validLastUsed) : undefined;

  const accountDefault: ModelSelection | undefined = catalog?.current
    ? {
        id: catalog.current.id,
        origin: catalog.current.origin,
        providerId: catalog.current.provider_id ?? null,
      }
    : undefined;

  const selectedSelection =
    overrideSelection ?? suggestion ?? accountDefault ?? undefined;

  const displaySelection = useMemo((): ModelSelection | undefined => {
    if (overrideSelection) return overrideSelection;
    if (lastTurnModel) {
      const matches = models.filter((m) => m.id === lastTurnModel);
      const preferred =
        matches.find((m) => m.available) ??
        matches.find((m) => m.origin === "byok") ??
        matches[0];
      if (preferred) {
        return {
          id: preferred.id,
          origin: preferred.origin,
          providerId: preferred.provider_id ?? null,
        };
      }
      return { id: lastTurnModel, origin: "byok", providerId: null };
    }
    return suggestion ?? accountDefault;
  }, [overrideSelection, lastTurnModel, models, suggestion, accountDefault]);

  const displayItem = displaySelection
    ? findCatalogItem(models, displaySelection)
    : undefined;
  const diverged =
    !!lastTurnModel &&
    (!selectedSelection || lastTurnModel !== selectedSelection.id);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models;
    return models.filter(
      (m) =>
        m.display_name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.vendor.toLowerCase().includes(q),
    );
  }, [models, query]);

  const originSections = useMemo(() => {
    // Platform 为主 (F7): 平台组置顶且**扁平平铺**——运营方精选的小集合无需再按厂商分二级，
    // 顶层「平台模型」已足够（避免「平台模型 › 平台中转」这类冗余嵌套）。BYOK 组仅在配服务商后
    // 由目录带出、排其后，组内**按服务商 provider_label 分组**（同 id 跨服务商靠服务商标签消歧）。
    const platform = filtered.filter((m) => m.origin === "platform");
    const byok = filtered.filter((m) => m.origin === "byok");
    const sections: {
      origin: ModelCatalogItem["origin"];
      grouped: boolean;
      groups: [string, ModelCatalogItem[]][];
    }[] = [];
    if (platform.length > 0) {
      sections.push({
        origin: "platform",
        grouped: false,
        groups: [["platform", sortRows(platform)]],
      });
    }
    if (byok.length > 0) {
      sections.push({
        origin: "byok",
        grouped: true,
        groups: groupItems(byok, byokGroupKey),
      });
    }
    return sections;
  }, [filtered]);

  const hasLocked = models.some((m) => m.available === false);
  const showUnlockCta = !catalog?.byok_configured || hasLocked;

  const applyModel = async (sel: ModelSelection) => {
    if (disabled || pending) return;
    const item = findCatalogItem(models, sel);
    if (item && item.available === false) {
      setOpen(false);
      navigate("/more/model");
      return;
    }
    setLastUsedModel(sel);
    setOpen(false);
    if (!conversationId) {
      setDraftSelection(sel);
      return;
    }
    setPending(true);
    try {
      const saved = await setConversationModel(conversationId, sel);
      patchConversationCache(conversationId, {
        model: saved.model ?? null,
        modelOrigin: saved.modelOrigin ?? null,
        modelProviderId: saved.modelProviderId ?? null,
      });
      notifySuccess(`已切换为「${item?.display_name ?? sel.id}」`);
    } catch (e) {
      notifyError(e, "切换模型失败");
    } finally {
      setPending(false);
    }
  };

  const clearOverride = async () => {
    if (disabled || pending || !conversationId) return;
    setOpen(false);
    setPending(true);
    try {
      const saved = await setConversationModel(conversationId, null);
      patchConversationCache(conversationId, {
        model: saved.model ?? null,
        modelOrigin: saved.modelOrigin ?? null,
        modelProviderId: saved.modelProviderId ?? null,
      });
      notifySuccess("已跟随账号默认模型");
    } catch (e) {
      notifyError(e, "重置模型失败");
    } finally {
      setPending(false);
    }
  };

  if (isLoading && !displaySelection) {
    return (
      <span className="inline-flex h-8 items-center gap-1 px-2 text-xs text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
      </span>
    );
  }

  const label = displayItem?.display_name ?? displaySelection?.id ?? "选择模型";
  const tooltip = diverged
    ? `本会话上一回合实际运行：${lastTurnModel}`
    : "切换本会话使用的模型（当前回合起生效）";

  const isRowSelected = (item: ModelCatalogItem) =>
    selectionsEqual(selectedSelection, {
      id: item.id,
      origin: item.origin,
      providerId: item.provider_id ?? null,
    });

  // A platform row whose id also exists under BYOK: mark it「平台额度」so the user can
  // tell「跑在平台额度」from「跑在自己的 key」for the same model (F8: 平台额度, 非「免费」).
  const showPlatformBadge = (item: ModelCatalogItem) =>
    item.origin === "platform" && idsWithBothOrigins.has(item.id);

  return (
    <div ref={rootRef} className="relative shrink-0">
      <SimpleTooltip label={tooltip}>
        <button
          type="button"
          disabled={disabled || pending}
          onClick={() => setOpen((v) => !v)}
          aria-label={`模型：${label}`}
          aria-expanded={open}
          className={`inline-flex h-8 max-w-40 items-center gap-1 rounded-lg px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground ${
            disabled || pending ? "cursor-not-allowed opacity-60" : ""
          }`}
        >
          {pending ? (
            <Loader2 size={14} className="shrink-0 animate-spin" />
          ) : (
            <Bot size={14} className="shrink-0" />
          )}
          <span className="truncate font-mono">{label}</span>
          <ChevronDown size={12} className="shrink-0 opacity-60" />
        </button>
      </SimpleTooltip>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1 flex max-h-[22rem] w-72 flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-lg">
          <div className="flex items-center gap-1.5 border-b border-border px-2.5 py-2">
            <Search size={14} className="shrink-0 text-muted-foreground" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索模型…"
              className="w-full bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-1">
            {isError ? (
              <div className="px-2.5 py-3 text-xs">
                <p className="text-destructive">加载模型列表失败</p>
                <button
                  type="button"
                  onClick={() => void refetch()}
                  className="mt-1 text-primary hover:underline"
                >
                  重试
                </button>
              </div>
            ) : models.length === 0 ? (
              <div className="px-2.5 py-4 text-xs text-muted-foreground">
                暂无可用模型
              </div>
            ) : (
              <>
                {overrideSelection && (
                  <button
                    type="button"
                    onClick={() => void clearOverride()}
                    className="mb-1 flex w-full items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent/50"
                  >
                    <RotateCcw size={13} className="shrink-0" />
                    <span>跟随账号默认</span>
                    {accountDefault && (
                      <span className="truncate font-mono text-xs opacity-70">
                        {byKey.get(modelItemKey(accountDefault))
                          ?.display_name ?? accountDefault.id}
                      </span>
                    )}
                  </button>
                )}

                {originSections.map(({ origin, grouped, groups }) => (
                  <div key={origin}>
                    <GroupLabel>{ORIGIN_GROUP_LABEL[origin]}</GroupLabel>
                    {groups.map(([groupName, items]) => (
                      <div key={`${origin}-${groupName}`}>
                        {grouped && <GroupLabel>{groupName}</GroupLabel>}
                        {items.map((m) => (
                          <ModelRow
                            key={modelItemKey(m)}
                            item={m}
                            selected={isRowSelected(m)}
                            showPlatformBadge={showPlatformBadge(m)}
                            onPick={applyModel}
                          />
                        ))}
                      </div>
                    ))}
                  </div>
                ))}

                {query.trim() && filtered.length === 0 && (
                  <div className="px-2.5 py-3 text-xs text-muted-foreground">
                    没有匹配的模型
                  </div>
                )}
              </>
            )}
          </div>

          {showUnlockCta && (
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                navigate("/more/model");
              }}
              className="flex items-center gap-1.5 border-t border-border px-2.5 py-2 text-left text-xs text-primary hover:bg-accent/40"
            >
              <KeyRound size={13} className="shrink-0" />
              接入自己的 Key 解锁更多
            </button>
          )}
        </div>
      )}
    </div>
  );
}
