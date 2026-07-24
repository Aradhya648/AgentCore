import {
  type ModelCatalog,
  type ModelCatalogItem,
  type ModelPick,
  catalogCurrentPick,
  modelDisplayLabel,
  modelPickKey,
  picksEqual,
  useModels,
} from "@/api/models";
import { Modal } from "@/components/Modal";
import { MODEL_CONFIG_PATH } from "@/lib/errors";
// 会话级模型切换 · 选择器 (touch-native bottom sheet, 对齐桌面 ModelPicker 能力).
//
// Lists the user's catalog grouped by credential origin (平台模型 / 自带 Key); the BYOK group
// is sub-grouped by SERVICE PROVIDER (provider_label); the platform group is flat (no
// per-vendor sub-headers). The
// selection key is (id, origin, provider_id) — the same model id can appear under several
// providers, disambiguated by its provider group. Platform rows carry a「平台额度」badge when
// needed to distinguish them. An unavailable model taps through to 模型配置; when the
// conversation already overrides the account model, a「跟随账号默认」row clears it.
import { Check, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

const CAPABILITY_LABELS: Record<string, string> = {
  vision: "视觉",
  tools: "工具",
  reasoning: "推理",
};

// Platform 为主 (F7): 平台组置顶; BYOK「自带 Key」组仅在配 key 后由目录带出, 排其后。
const ORIGIN_SECTIONS: { origin: ModelCatalogItem["origin"]; title: string }[] =
  [
    { origin: "platform", title: "平台模型" },
    { origin: "byok", title: "自带 Key" },
  ];

/** Compact context-window label (128000 → 128K, 1000000 → 1M). Null when unknown. */
function formatContext(tokens: number | null | undefined): string | null {
  if (!tokens || tokens <= 0) return null;
  if (tokens >= 1_000_000) {
    const m = tokens / 1_000_000;
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
  return `${tokens}`;
}

/** One-line price hint (输入 = cache_miss, 输出 = output; USD / 1M). Null when unpriced. */
function formatPrice(price: ModelCatalogItem["price"]): string | null {
  if (!price) return null;
  const input = price.cache_miss?.trim();
  const output = price.output?.trim();
  if (!input && !output) return null;
  return `输入 $${input ?? "—"} / 输出 $${output ?? "—"} /1M`;
}

/** A titled sub-group of catalog rows (a provider for BYOK, a vendor for platform). */
type ModelGroup = { key: string; title: string; items: ModelCatalogItem[] };

/** Group BYOK rows by their service provider (provider_id, titled by provider_label),
 *  preserving first-seen order. This is what disambiguates the same model id across providers. */
function groupByProvider(items: ModelCatalogItem[]): ModelGroup[] {
  const groups = new Map<string, ModelGroup>();
  for (const item of items) {
    const key = item.provider_id ?? `vendor:${item.vendor}`;
    const title = item.provider_label ?? item.vendor;
    const g = groups.get(key);
    if (g) g.items.push(item);
    else groups.set(key, { key, title, items: [item] });
  }
  return [...groups.values()];
}

/** Platform rows as one flat group — no per-vendor sub-headers (first-seen order).
 *  The operator's platform set is a small curated list, so the「平台模型」origin header
 *  is enough (avoids a redundant「平台模型 › 平台中转」nesting). Empty title = no sub-header. */
function groupFlat(items: ModelCatalogItem[]): ModelGroup[] {
  return items.length ? [{ key: "platform", title: "", items }] : [];
}

function showFreeTierBadge(
  catalog: ModelCatalog,
  item: ModelCatalogItem,
  duplicateIds: Set<string>,
): boolean {
  if (item.origin !== "platform") return false;
  return !catalog.byok_configured || duplicateIds.has(item.id);
}

export function ModelPicker({
  conversationModel,
  onSelect,
  onClose,
}: {
  /** The conversation's current model override (null = following the account model). */
  conversationModel: ModelPick | null;
  /** A concrete (id, origin) pick to override with, or null to clear back to the account model. */
  onSelect: (pick: ModelPick | null) => void;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  // Revalidate on open so availability reflects a key just added in 模型配置.
  const { data, loading, error } = useModels({ force: true });

  const duplicateIds = useMemo(() => {
    const seen = new Map<string, Set<ModelCatalogItem["origin"]>>();
    for (const item of data?.models ?? []) {
      const origins = seen.get(item.id) ?? new Set();
      origins.add(item.origin);
      seen.set(item.id, origins);
    }
    return new Set(
      [...seen.entries()]
        .filter(([, origins]) => origins.size > 1)
        .map(([id]) => id),
    );
  }, [data]);

  const sections = useMemo(() => {
    if (!data) return [];
    return ORIGIN_SECTIONS.map(({ origin, title }) => {
      const items = data.models.filter((m) => m.origin === origin);
      return {
        origin,
        title,
        groups: origin === "byok" ? groupByProvider(items) : groupFlat(items),
      };
    }).filter((s) => s.groups.length > 0);
  }, [data]);

  const override = conversationModel;
  const hasOverride = override !== null;
  const effectivePick = override ?? catalogCurrentPick(data);

  function pickUnavailable() {
    onClose();
    navigate(MODEL_CONFIG_PATH);
  }

  const currentLabel = data ? modelDisplayLabel(data, null) : null;

  return (
    <Modal className="sheet model-sheet" onClose={onClose} label="选择模型">
      <div className="sheet-title">选择模型</div>

      <div className="model-list">
        {loading && !data && <p className="muted hint">加载中…</p>}
        {error && !data && <p className="error hint">{error}</p>}

        {data && (
          <>
            {hasOverride && (
              <button
                type="button"
                className="model-row"
                onClick={() => onSelect(null)}
              >
                <div className="model-row-main">
                  <span className="model-name">跟随账号默认模型</span>
                  <span className="model-sub muted">
                    清除本会话的模型选择
                    {currentLabel ? ` · 当前 ${currentLabel}` : ""}
                  </span>
                </div>
              </button>
            )}

            {sections.map(({ origin, title, groups }) => (
              <div key={origin} className="model-origin-section">
                <div className="model-origin-title">{title}</div>
                {groups.map((group) => (
                  <div key={`${origin}-${group.key}`} className="model-group">
                    {group.title && (
                      <div className="model-group-title">{group.title}</div>
                    )}
                    {group.items.map((item) => {
                      const pick: ModelPick =
                        item.origin === "byok" && item.provider_id
                          ? {
                              id: item.id,
                              origin: item.origin,
                              providerId: item.provider_id,
                            }
                          : { id: item.id, origin: item.origin };
                      const selected = picksEqual(pick, effectivePick);
                      const caps = item.capabilities ?? [];
                      const context = formatContext(item.context_length);
                      const price = formatPrice(item.price);
                      const freeTier = showFreeTierBadge(
                        data,
                        item,
                        duplicateIds,
                      );
                      return (
                        <button
                          key={modelPickKey(pick)}
                          type="button"
                          data-testid={`model-row-${item.id}-${item.origin}${
                            item.origin === "byok" && item.provider_id
                              ? `-${item.provider_id}`
                              : ""
                          }`}
                          className={`model-row${selected ? " model-row-selected" : ""}${
                            item.available ? "" : " model-row-disabled"
                          }`}
                          aria-disabled={!item.available}
                          onClick={() =>
                            item.available ? onSelect(pick) : pickUnavailable()
                          }
                        >
                          <div className="model-row-main">
                            <span className="model-name-row">
                              <span className="model-name">
                                {item.display_name}
                              </span>
                              {freeTier && (
                                <span className="model-free-tier">
                                  平台额度
                                </span>
                              )}
                            </span>
                            {(caps.length > 0 || context) && (
                              <div className="model-tags">
                                {caps.map((cap) => (
                                  <span key={cap} className="model-cap">
                                    {CAPABILITY_LABELS[cap] ?? cap}
                                  </span>
                                ))}
                                {context && (
                                  <span className="model-meta">
                                    {context} 上下文
                                  </span>
                                )}
                              </div>
                            )}
                            {price && (
                              <span className="model-price muted">{price}</span>
                            )}
                            {!item.available && (
                              <span className="model-locked">
                                需配置 API Key · 去配置
                              </span>
                            )}
                          </div>
                          {selected ? (
                            <Check
                              size={18}
                              className="model-check"
                              aria-hidden
                            />
                          ) : !item.available ? (
                            <ChevronRight
                              size={16}
                              className="muted"
                              aria-hidden
                            />
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            ))}

            {sections.length === 0 && (
              <button
                type="button"
                className="model-row"
                onClick={pickUnavailable}
              >
                <div className="model-row-main">
                  <span className="model-name">接入自己的 Key 解锁更多</span>
                  <span className="model-sub muted">
                    暂无可用模型 · 去模型配置添加服务商
                  </span>
                </div>
                <ChevronRight size={16} className="muted" aria-hidden />
              </button>
            )}
          </>
        )}
      </div>

      <button
        type="button"
        className="sheet-item sheet-cancel"
        onClick={onClose}
      >
        取消
      </button>
    </Modal>
  );
}
