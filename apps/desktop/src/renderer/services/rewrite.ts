import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** 选区改写入参（后端 schema，snake_case）。 */
export type RewriteRequest = Schemas["RewriteRequest"];
/** 选区改写结果（`{ rewritten }`）。 */
export type RewriteResponse = Schemas["RewriteResponse"];

/** {@link rewriteSelection} 的入参（camelCase，前端友好）。 */
export interface RewriteParams {
  /** 选中文本（被改写的那段）。 */
  selection: string;
  /** 自由文本指令（如「改得更正式」）。 */
  instruction: string;
  /** 选区前的上下文（只读语境，默认空）。 */
  contextBefore?: string;
  /** 选区后的上下文（只读语境，默认空）。 */
  contextAfter?: string;
}

/**
 * 让后端按指令改写一段选区（`POST /v1/files/assist/rewrite`）。
 *
 * 无状态、不落库：只把选区 + 指令 + 前后文当文本发过去，拿回改写版由调用方套
 * merge view 逐块评审——后端从不碰文件本身（无路径）。失败抛 {@link ApiError}
 * （如 402 LLM_KEY_REQUIRED：未配 DeepSeek key），由调用方提示。
 */
export async function rewriteSelection(p: RewriteParams): Promise<string> {
  const res = await api.post<RewriteResponse>("/v1/files/assist/rewrite", {
    selection: p.selection,
    instruction: p.instruction,
    context_before: p.contextBefore ?? "",
    context_after: p.contextAfter ?? "",
  } satisfies RewriteRequest);
  return res.rewritten;
}
