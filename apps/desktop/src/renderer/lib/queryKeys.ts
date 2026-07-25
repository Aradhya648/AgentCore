/**
 * Central registry of React Query keys. Keeping every key here (rather than
 * inline string arrays at each call site) lets a mutation invalidate exactly the
 * queries it affects without guessing the shape, and makes the cached REST
 * surface discoverable in one place as more resources migrate onto React Query.
 */
export const conversationKeys = {
  all: ["conversations"] as const,
  /** Folders + conversations in one trip (`GET /v1/conversations/grouped`). */
  grouped: ["conversations", "grouped"] as const,
  /** Archived conversations (`GET /v1/conversations?archived=true`) — the
   * on-demand「已归档」view, separate from the live grouped cache. */
  archived: ["conversations", "archived"] as const,
  /** 项目协作时间线（`GET /v1/folders/{id}/collaboration-timeline`）。 */
  collaborationTimeline: (folderId: string) =>
    ["collaboration-timeline", folderId] as const,
};

export const workspaceKeys = {
  all: ["workspaces"] as const,
  /** The user's workspaces (= folders, cloud + local) for the 文件 hub rail
   * (`GET /v1/workspaces`). */
  list: ["workspaces", "list"] as const,
};

/** 多人共享空间（`/v1/shared-spaces`）— 列表 / 邀请 / 成员 / 流水 / 会话挂载. */
export const sharedSpaceKeys = {
  all: ["shared-spaces"] as const,
  list: ["shared-spaces", "list"] as const,
  pendingInvites: ["shared-spaces", "pending-invites"] as const,
  detail: (spaceId: string) => ["shared-spaces", "detail", spaceId] as const,
  members: (spaceId: string) => ["shared-spaces", "members", spaceId] as const,
  events: (spaceId: string) => ["shared-spaces", "events", spaceId] as const,
  mounts: (conversationId: string) =>
    ["shared-spaces", "mounts", conversationId] as const,
};

/** 设置·模型配置的服务商列表（`GET /v1/users/me/llm-providers`）。 */
export const llmProviderKeys = {
  all: ["llm-providers"] as const,
  /** The user's BYOK provider list + deployment caps. */
  list: ["llm-providers", "list"] as const,
};

/** 账号模型组合（`GET /v1/users/me/llm-model-profiles`）。 */
export const llmModelProfileKeys = {
  all: ["llm-model-profiles"] as const,
  list: ["llm-model-profiles", "list"] as const,
};

/** 槽位编辑用的模型目录（`GET /v1/users/me/models`）。 */
export const modelKeys = {
  all: ["models"] as const,
  /** The user's selectable model catalog + current account model. */
  catalog: ["models", "catalog"] as const,
};
