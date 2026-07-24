import { hasAgentTownLauncher } from "@/lib/capabilities";
import { BASE_URL } from "@/services/api";

export { hasAgentTownLauncher };

/**
 * 将当前 cookie 会话同步到 `%APPDATA%/AgentCore/session.json`（best-effort）。
 * 登录成功、冷启动 bootstrap、token 刷新后调用；失败静默（不阻断主流程）。
 */
export async function persistAgentTownSession(): Promise<void> {
  if (!hasAgentTownLauncher()) return;
  try {
    await window.agentTownApi?.writeSession({ api_base: BASE_URL });
  } catch (err) {
    console.warn("[agenttown] persist session failed", err);
  }
}

/** 登出时清除 session.json（best-effort）。 */
export async function clearAgentTownSession(): Promise<void> {
  if (!hasAgentTownLauncher()) return;
  try {
    await window.agentTownApi?.clearSession();
  } catch (err) {
    console.warn("[agenttown] clear session failed", err);
  }
}
