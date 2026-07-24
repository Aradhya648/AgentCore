/** Brand hue invariant (color-tokens.mdc). */
export const BRAND_HUE = 255;

/** Semantic token names shared across desktop Tailwind + mobile usage CSS. */
export const SEMANTIC_TOKEN_NAMES = [
  "background",
  "foreground",
  "primary",
  "success",
  "warning",
  "destructive",
  "muted",
  "accent",
  "border",
] as const;

export type SemanticTokenName = (typeof SEMANTIC_TOKEN_NAMES)[number];
