/**
 * AgentTown 启动器 IPC 契约 —— Desktop 写 `session.json` 并 spawn 独立 Unity 客户端 AgentTown（§8.2 / §10）。
 *
 * `session.json` 落 `%APPDATA%/AgentCore/session.json`（`app.getPath("appData")/AgentCore/`），
 * 供 AgentTown 冷启动读 token；Desktop 在登录 / 刷新后写入，登出时清除。
 */

/** 与 AgentTown 客户端规格 §8.2 对齐的会话文件形状。 */
export interface AgentTownSessionFile {
  api_base: string;
  access_token: string;
  refresh_token?: string;
  expires_at?: string;
}

/** 显式写入时 renderer 可只传 api_base，由主进程从 httpOnly cookie 补 token。 */
export type WriteSessionInput = {
  api_base: string;
  access_token?: string;
  refresh_token?: string;
  expires_at?: string;
};

export type AgentTownLaunchResult =
  | { ok: true }
  | {
      ok: false;
      reason: "not_found" | "missing_token" | "invalid_args" | "spawn_failed";
      message: string;
      /** Paths checked when reason is not_found (dev guidance). */
      candidates?: string[];
    };

export type WriteSessionResult =
  | { ok: true }
  | {
      ok: false;
      reason: "missing_token" | "invalid_args" | "write_failed";
      message: string;
    };

export const AGENTTOWN_CHANNELS = {
  writeSession: "agenttown:writeSession",
  launch: "agenttown:launch",
  clearSession: "agenttown:clearSession",
} as const;

export interface AgentTownApi {
  /** 写入或更新 session.json；未传 token 时主进程从 cookie jar 读取。 */
  writeSession: (input: WriteSessionInput) => Promise<WriteSessionResult>;
  /** 清除 session.json（登出）。 */
  clearSession: () => Promise<void>;
  /** 启动 AgentTown.exe，可选附带当前 run id。 */
  launch: (opts?: { runId?: string }) => Promise<AgentTownLaunchResult>;
}
