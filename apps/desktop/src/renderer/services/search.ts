import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** Grouped keyword-search results (`GET /v1/search`). */
export type SearchResponse = Schemas["SearchResponse"];
/** One entity-type group within a {@link SearchResponse}. */
export type SearchSection = Schemas["SearchSection"];
/** One hit; field meaning depends on its section `type` (see backend schema). */
export type SearchItem = Schemas["SearchItem"];
/** The entity types Tier 1 searches. */
export type SearchSectionType = SearchSection["type"];

export interface SearchOptions {
  /** Per-section cap (backend default 8, max 20). */
  limit?: number;
  /** Restrict to a subset of entity types (default = all). */
  types?: SearchSectionType[];
  /** 时间过滤: only hits updated at/after this ISO 8601 instant. */
  updatedAfter?: string;
  /** 项目过滤: scope conversation/message hits to one folder (drops the folder
   *  section server-side). */
  folderId?: string;
}

/**
 * Run a global keyword search over the user's conversations, messages and
 * folders (全局搜索 Tier 1). Owner-scoped server-side; empty sections are omitted.
 *
 * Stale-response ordering is the caller's concern — the command palette guards
 * with a per-keystroke sequence id rather than aborting (debounced + min 1 char
 * keeps the request count low).
 *
 * {@link SearchOptions.updatedAfter} / {@link SearchOptions.folderId} are the
 * 搜索结果过滤 facets (时间 / 项目): applied server-side so the per-section cap is
 * spent on matching rows rather than filtered-away ones.
 */
export async function searchAll(
  query: string,
  opts: SearchOptions = {},
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.types?.length) params.set("types", opts.types.join(","));
  if (opts.updatedAfter) params.set("updated_after", opts.updatedAfter);
  if (opts.folderId) params.set("folder_id", opts.folderId);
  return api.get<SearchResponse>(`/v1/search?${params.toString()}`);
}
