/**
 * Soft outdated-client gate (部署与运维.md §7.6): compare local build to
 * `GET /updates/policy`.min_desktop_version. Empty min / `dev` builds never count
 * as outdated.
 */

function semverParts(version: string): [number, number, number] {
  const core = (version.split("-")[0] ?? version).trim();
  const bits = core.split(".").map((x) => {
    const n = Number.parseInt(x, 10);
    return Number.isFinite(n) ? n : 0;
  });
  return [bits[0] ?? 0, bits[1] ?? 0, bits[2] ?? 0];
}

/** Negative when `a < b`, 0 when equal, positive when `a > b` (major.minor.patch). */
export function compareSemver(a: string, b: string): number {
  const pa = semverParts(a);
  const pb = semverParts(b);
  for (let i = 0; i < 3; i++) {
    const av = pa[i] ?? 0;
    const bv = pb[i] ?? 0;
    if (av !== bv) return av < bv ? -1 : 1;
  }
  return 0;
}

/**
 * Whether the local desktop build should show the soft outdated banner.
 * `clientVersion()==="dev"` and empty/null min never trigger.
 */
export function isDesktopVersionOutdated(
  localVersion: string,
  minDesktopVersion: string | null | undefined,
): boolean {
  const min = minDesktopVersion?.trim();
  if (!min) return false;
  if (localVersion === "dev") return false;
  return compareSemver(localVersion, min) < 0;
}
