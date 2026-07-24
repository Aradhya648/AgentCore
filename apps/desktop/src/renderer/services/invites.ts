import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** Invite lifecycle state (generated from backend `InviteResponse.status`). */
export type InviteStatus = Schemas["InviteResponse"]["status"];

/** Client-facing invite (camelCase) for the admin invite list. */
export interface Invite {
  id: string;
  code: string;
  status: InviteStatus;
  createdAt: string;
  expiresAt: string | null;
  usedAt: string | null;
}

/** Server invite payload (`/auth/invites`), generated from OpenAPI. */
type BackendInvite = Schemas["InviteResponse"];

function toInvite(i: BackendInvite): Invite {
  return {
    id: i.id,
    code: i.code,
    status: i.status,
    createdAt: i.created_at,
    expiresAt: i.expires_at,
    usedAt: i.used_at,
  };
}

/** Mint a single-use invite code (admin only). */
export async function createInvite(expiresInDays?: number): Promise<Invite> {
  return toInvite(
    await api.post<BackendInvite>("/v1/auth/invites", {
      expires_in_days: expiresInDays ?? null,
    }),
  );
}

type InviteListResponse = Schemas["InviteListResponse"];

/** List recently issued invite codes (admin only). */
export async function listInvites(): Promise<Invite[]> {
  const res = await api.get<InviteListResponse>("/v1/auth/invites");
  return res.data.map(toInvite);
}
