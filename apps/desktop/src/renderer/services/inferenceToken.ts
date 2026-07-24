import { BASE_URL, api } from "@/services/api";
import type { SidecarInference } from "@shared/sidecar-contract";

/**
 * 桌面侧的「云推理凭据」获取器（双模式工作区 §一.1 / Slice 4a）。
 *
 * sidecar 跑在用户机器上，但平台 LLM key **绝不下放本机**：引擎的 LLM 调用改指向云端推理代理
 * `POST /v1/inference/v1/chat/completions`，以一枚**作用域受限的短期令牌**（inference token）
 * 作 Bearer 鉴权。本模块负责拿这枚令牌并拼出 sidecar 需要的 `{baseUrl, apiKey}`：
 *
 * - `baseUrl` = `${BASE_URL}/v1/inference/v1`：`OpenAICompatibleProvider` 在其后拼 `/chat/completions`，
 *   命中代理路由 `/v1/inference/v1/chat/completions`（见服务端 `api/routes/inference/proxy.py`）。
 * - `apiKey` = 令牌本身（非平台 key）。
 * - `model` = 服务端按用户计费/BYOK 解析的 chat 模型名（与推理代理上游一致）。
 *
 * 令牌经 cookie 会话向 `POST /v1/inference/token` 兑换（与其余 API 同源鉴权）。令牌有 TTL
 * （服务端 `inference_token_expire_minutes`，默认 12h），故这里**缓存到临近过期再续铸**——
 * sidecar 每回合都会重读 `inference`，拿到当前令牌即可，无需每次发消息都打一次兑换。
 */

interface InferenceTokenResponse {
  token: string;
  expires_in_sec: number;
  model: string;
}

/** 已缓存的令牌与其绝对过期时刻（ms）。null = 尚未铸过 / 已失效。 */
let cached: { token: string; expiresAtMs: number; model: string } | null = null;

// 提前续铸的安全余量：在真正过期前 1 分钟就重铸，规避时钟偏移与「铸好到用上」之间的 TTL 损耗。
const RENEW_SKEW_MS = 60_000;

async function mint(): Promise<{
  token: string;
  expiresAtMs: number;
  model: string;
}> {
  const res = await api.post<InferenceTokenResponse>("/v1/inference/token");
  return {
    token: res.token,
    expiresAtMs: Date.now() + res.expires_in_sec * 1000,
    model: res.model,
  };
}

/**
 * 解析出一次本地回合可用的云推理凭据；取不到则返回 `null`。
 *
 * 取不到（如会话过期 / 服务端不可达）时由调用方决定降级——新回合可回退云链路，续跑则带
 * `undefined` 交由 sidecar 处理（dev 回退其自身配置；生产则以可重试的引擎错误失败，胜过把
 * 一个本机持久挂起帧误路由到必然 404 的云端续跑）。
 */
export async function resolveSidecarInference(): Promise<SidecarInference | null> {
  try {
    if (!cached || cached.expiresAtMs - RENEW_SKEW_MS <= Date.now()) {
      cached = await mint();
    }
    return {
      baseUrl: `${BASE_URL}/v1/inference/v1`,
      apiKey: cached.token,
      model: cached.model,
    };
  } catch (err) {
    console.error("[sidecar] 取推理令牌失败", err);
    cached = null;
    return null;
  }
}

/** 丢弃缓存令牌（登出时调），使下次回合在新会话下重新兑换。 */
export function clearSidecarInference(): void {
  cached = null;
}
