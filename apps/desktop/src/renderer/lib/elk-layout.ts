/**
 * Re-export shim — implementation lives in `@agentcore/graph-layout`
 * (shared with promo precompute; no desktop `@/` runtime deps).
 */
export {
  NODE_SPACING_EMBED,
  NODE_SPACING_COMFORT,
  nodeSpacingForFitMode,
  COMPOUND_LAYER_SPACING,
  computeLayout,
  EMBED_MIN_HEIGHT,
  EMBED_MAX_HEIGHT,
  EMBED_DEFAULT_COL_WIDTH,
  workerGraphShape,
  estimateBbox,
  fitWidthBox,
  NODE_WIDTH,
  NODE_HEIGHT,
  buildNodeSizeMap,
  type LayoutResult,
  type GroupLayout,
  type SubTeamInput,
  type LayoutBookends,
  type GraphShape,
  type FitWidthBox,
  type NodeSizeMap,
} from "@agentcore/graph-layout";
