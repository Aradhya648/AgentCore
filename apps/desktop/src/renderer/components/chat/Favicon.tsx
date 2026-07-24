import { BASE_URL } from "@/services/api";
import { useState } from "react";

/**
 * URL of the backend favicon proxy for a domain. The proxy fetches the site's
 * icon server-side (relaxed TLS + `<link rel=icon>` discovery + caching), which is
 * far more reliable than the renderer hitting `https://{site}/favicon.ico` directly
 * — a China-hosted client fails the TLS handshake for many `*.gov.cn` sites. A
 * resolvable icon comes back as image bytes; an unresolvable one as 404, so the
 * `<img>` `onError` fallback still applies.
 */
export function faviconUrl(domain: string): string {
  return `${BASE_URL}/v1/favicon?domain=${encodeURIComponent(domain)}`;
}

/**
 * A site favicon avatar with a graceful fallback. Loads the icon via the backend
 * proxy ({@link faviconUrl}); on load failure (or when the host is unparseable) it
 * falls back to a neutral letter chip. Used by source cards and the inline `[n]`
 * citation hover so a reader recognizes a source at a glance.
 */
export function Favicon({
  site,
  title,
  size = 16,
  className = "",
}: {
  /** Display hostname (sans leading www.); empty when the URL had no host. */
  site?: string;
  /** Fallback letter source when there's no host. */
  title?: string;
  size?: number;
  /** Extra classes on the avatar wrapper (e.g. an overlap ring). */
  className?: string;
}) {
  const domain = site?.trim();
  // Track the domain whose favicon failed (not a bare bool) so a re-rendered chip
  // pointing at a *different* source retries the image instead of staying blank.
  const [failedDomain, setFailedDomain] = useState<string | null>(null);

  const letter = (domain || title || "?").charAt(0).toUpperCase();
  const showImg = !!domain && failedDomain !== domain;

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-medium text-muted-foreground ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      {showImg ? (
        <img
          src={faviconUrl(domain)}
          alt=""
          loading="lazy"
          onError={() => setFailedDomain(domain)}
          className="size-full object-contain"
        />
      ) : (
        letter
      )}
    </span>
  );
}
