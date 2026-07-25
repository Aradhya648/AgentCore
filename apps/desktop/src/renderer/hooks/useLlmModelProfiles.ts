import { llmModelProfileKeys } from "@/lib/queryKeys";
import {
  type LlmModelProfileListResponse,
  listLlmModelProfiles,
} from "@/services/llmModelProfiles";
import { useQuery } from "@tanstack/react-query";

/** Cached 账号模型组合列表（输入框选择器 + 设置·模型配置）。 */
export function useLlmModelProfiles() {
  return useQuery<LlmModelProfileListResponse>({
    queryKey: llmModelProfileKeys.list,
    queryFn: listLlmModelProfiles,
    staleTime: 60_000,
    refetchOnMount: "always",
  });
}
