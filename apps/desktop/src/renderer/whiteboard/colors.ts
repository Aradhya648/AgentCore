/**
 * Canvas needs concrete color strings, but the project forbids hardcoded colors
 * (color-tokens.mdc). So we read the semantic OKLCH tokens off the live DOM at runtime
 * and hand the renderer a palette, re-reading on theme toggle. The values are
 * `oklch(...)` strings, which Chromium (Electron) accepts as canvas fill/stroke.
 */

export interface Palette {
  background: string;
  foreground: string;
  card: string;
  border: string;
  primary: string;
  primaryForeground: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  warning: string;
  success: string;
  destructive: string;
}

const FALLBACK: Palette = {
  background: "oklch(1 0 0)",
  foreground: "oklch(0.15 0.01 255)",
  card: "oklch(1 0 0)",
  border: "oklch(0.92 0.008 255)",
  primary: "oklch(0.55 0.18 255)",
  primaryForeground: "oklch(0.985 0.01 255)",
  muted: "oklch(0.97 0.006 255)",
  mutedForeground: "oklch(0.55 0.02 255)",
  accent: "oklch(0.96 0.012 255)",
  warning: "oklch(0.66 0.15 65)",
  success: "oklch(0.55 0.14 152)",
  destructive: "oklch(0.58 0.22 27)",
};

/** Read a custom property; resolve simple `var(--x)` aliases against `background` so a
 * token like `--card: var(--background)` returns a concrete color even if the engine
 * runs before the browser resolves nested vars. */
function readVar(
  styles: CSSStyleDeclaration,
  name: string,
  fallback: string,
  background: string,
): string {
  const raw = styles.getPropertyValue(name).trim();
  if (!raw) return fallback;
  if (raw.includes("var(")) return background;
  return raw;
}

/** Content color swatches for the selection style panel — the 8 evenly-spaced identity
 * hues (`--agent-1..8`), read off the live theme so they track light/dark. These are
 * user-applied CONTENT colors (stored on elements), distinct from the chrome {@link Palette}. */
const SWATCH_FALLBACK = [
  "oklch(0.58 0.14 20)",
  "oklch(0.58 0.14 65)",
  "oklch(0.58 0.14 110)",
  "oklch(0.58 0.14 155)",
  "oklch(0.58 0.14 200)",
  "oklch(0.58 0.14 245)",
  "oklch(0.58 0.14 290)",
  "oklch(0.58 0.14 335)",
];

export function readSwatches(): string[] {
  if (
    typeof document === "undefined" ||
    typeof getComputedStyle !== "function"
  ) {
    return [...SWATCH_FALLBACK];
  }
  const s = getComputedStyle(document.documentElement);
  return SWATCH_FALLBACK.map((fallback, i) => {
    const v = s.getPropertyValue(`--agent-${i + 1}`).trim();
    return v || fallback;
  });
}

export function readPalette(): Palette {
  if (
    typeof document === "undefined" ||
    typeof getComputedStyle !== "function"
  ) {
    return { ...FALLBACK };
  }
  const s = getComputedStyle(document.documentElement);
  const background =
    s.getPropertyValue("--background").trim() || FALLBACK.background;
  const foreground =
    s.getPropertyValue("--foreground").trim() || FALLBACK.foreground;
  return {
    background,
    foreground,
    card: readVar(s, "--card", FALLBACK.card, background),
    border: readVar(s, "--border", FALLBACK.border, background),
    primary: readVar(s, "--primary", FALLBACK.primary, background),
    primaryForeground: readVar(
      s,
      "--primary-foreground",
      FALLBACK.primaryForeground,
      background,
    ),
    muted: readVar(s, "--muted", FALLBACK.muted, background),
    mutedForeground: readVar(
      s,
      "--muted-foreground",
      FALLBACK.mutedForeground,
      background,
    ),
    accent: readVar(s, "--accent", FALLBACK.accent, background),
    warning: readVar(s, "--warning", FALLBACK.warning, background),
    success: readVar(s, "--success", FALLBACK.success, background),
    destructive: readVar(s, "--destructive", FALLBACK.destructive, background),
  };
}
