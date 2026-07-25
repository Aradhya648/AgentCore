import type { HTMLAttributes } from "react";

export type BrandMarkSize = "sm" | "md" | "lg";
export type BrandMarkLayout = "inline" | "stack";

const MARK_PX: Record<BrandMarkSize, number> = {
  sm: 18,
  md: 28,
  lg: 36,
};

const WORD_CLASS: Record<BrandMarkSize, string> = {
  sm: "text-sm font-semibold tracking-tight",
  md: "text-xl font-semibold tracking-tight",
  lg: "text-xl font-semibold tracking-tight",
};

/**
 * Shared product mark + AgentCore wordmark.
 * Display font (`font-brand`) applies to the Latin wordmark only; CJK copy nearby stays on the system stack.
 */
export function BrandMark({
  size = "md",
  layout = "inline",
  showWordmark = true,
  className = "",
  ...rest
}: {
  size?: BrandMarkSize;
  layout?: BrandMarkLayout;
  showWordmark?: boolean;
  className?: string;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`inline-flex items-center ${
        layout === "stack" ? "flex-col gap-2" : "gap-2"
      } ${className}`}
      {...rest}
    >
      <BrandMarkIcon
        size={MARK_PX[size]}
        title={showWordmark ? undefined : "AgentCore"}
      />
      {showWordmark && (
        <span className={`font-brand ${WORD_CLASS[size]}`}>AgentCore</span>
      )}
    </div>
  );
}

/** Standalone SVG mark (three linked nodes — collaboration). Inherits size; fill uses `text-primary`. */
export function BrandMarkIcon({
  size = 24,
  className = "",
  title,
}: {
  size?: number;
  className?: string;
  /** Accessible name when shown alone; omit beside a visible wordmark. */
  title?: string;
}) {
  const mark = (
    <>
      <circle cx="16" cy="8" r="3.25" fill="currentColor" />
      <circle cx="8" cy="23" r="3.25" fill="currentColor" />
      <circle cx="24" cy="23" r="3.25" fill="currentColor" />
      <path
        d="M14.2 10.6 9.8 20.4M17.8 10.6 22.2 20.4M11.2 23h9.6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </>
  );
  const svgClass = `shrink-0 text-primary ${className}`;

  if (!title) {
    return (
      // biome-ignore lint/a11y/noSvgWithoutTitle: decorative companion mark; visible wordmark provides the name
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={svgClass}
        aria-hidden
      >
        {mark}
      </svg>
    );
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={svgClass}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      {mark}
    </svg>
  );
}
