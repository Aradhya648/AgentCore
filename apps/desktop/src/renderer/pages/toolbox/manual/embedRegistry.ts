import { type ComponentType, type LazyExoticComponent, lazy } from "react";

/**
 * embed block 的 key → 懒加载组件注册表。
 *
 * 真组件零 props；内容源只存字符串 key。后续 `embeds/` 预览组件
 *（ManualDebateScoreboardPreview 等）在此追加即可，勿在内容源里写 JSX。
 */
export type EmbedComponent = LazyExoticComponent<ComponentType>;

export const EMBED_REGISTRY: Record<string, EmbedComponent> = {
  HeroGraph: lazy(() =>
    import("@/components/manual/MechanismContent").then((m) => ({
      default: m.HeroGraph,
    })),
  ),
  GraphLegend: lazy(() =>
    import("@/components/manual/MechanismContent").then((m) => ({
      default: m.GraphLegend,
    })),
  ),
  MechanismScenarios: lazy(() =>
    import("@/components/manual/MechanismContent").then((m) => ({
      default: m.MechanismScenarios,
    })),
  ),
  ManualDebateScoreboardPreview: lazy(() =>
    import("./embeds").then((m) => ({
      default: m.ManualDebateScoreboardPreview,
    })),
  ),
  ManualDebateFinalePreview: lazy(() =>
    import("./embeds").then((m) => ({
      default: m.ManualDebateFinalePreview,
    })),
  ),
  ManualCheckpointCardPreview: lazy(() =>
    import("./embeds").then((m) => ({
      default: m.ManualCheckpointCardPreview,
    })),
  ),
  ManualApprovalCardPreview: lazy(() =>
    import("./embeds").then((m) => ({
      default: m.ManualApprovalCardPreview,
    })),
  ),
};

export function resolveEmbed(key: string): EmbedComponent | undefined {
  return EMBED_REGISTRY[key];
}
