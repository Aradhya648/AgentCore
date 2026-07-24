import { api } from "@/services/api";

export interface VersionInfo {
  version: string;
  gitSha: string;
  builtAt: string;
}

export interface UpdatesPolicy {
  enabled: boolean;
  /** Soft floor for desktop; null when unset (no outdated banner). */
  minDesktopVersion: string | null;
}

// Hand-written on purpose: `/version` has no response_model, so the generated
// type is an untyped `{ [k]: string }` dict — this local shape is the precise contract.
interface BackendVersion {
  version: string;
  git_sha: string;
  built_at: string;
}

interface BackendUpdatesPolicy {
  enabled: boolean;
  min_desktop_version: string | null;
}

/**
 * Build provenance from the backend `/version` probe (semantic version + git
 * SHA + build time). `gitSha` / `builtAt` are "unknown" on an un-stamped build.
 */
export async function fetchVersion(): Promise<VersionInfo> {
  const v = await api.get<BackendVersion>("/version");
  return { version: v.version, gitSha: v.git_sha, builtAt: v.built_at };
}

/**
 * Desktop update policy (`GET /updates/policy`): kill switch + soft minimum
 * version. Unauthenticated on the server; used by the Electron shell for the
 * outdated soft banner (部署与运维.md §7.6).
 */
export async function fetchUpdatesPolicy(): Promise<UpdatesPolicy> {
  const p = await api.get<BackendUpdatesPolicy>("/updates/policy");
  return {
    enabled: p.enabled !== false,
    minDesktopVersion: p.min_desktop_version ?? null,
  };
}
