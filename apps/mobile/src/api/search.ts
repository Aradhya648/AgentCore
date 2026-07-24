// Global keyword search for the mobile client (对话管理 · 跨会话搜索; 全局搜索 Tier 1).
//
// One query fans out over the user's own conversations (title) and messages (content).
// Folders are out of scope on mobile (no folder surface). REST DTOs track OpenAPI.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type SearchItem = Schemas["SearchItem"];
export type SearchSection = Schemas["SearchSection"];
type SearchResponse = Schemas["SearchResponse"];

/** Search conversations + messages by keyword. Empty sections are omitted by the backend;
 *  an empty array means no hits. */
export async function search(q: string): Promise<SearchSection[]> {
  const res = await apiFetch(
    `/v1/search?q=${encodeURIComponent(q)}&types=conversation,message`,
  );
  if (!res.ok) throw new Error(`搜索失败 (${res.status})`);
  const data = (await res.json()) as SearchResponse;
  return data.sections;
}
