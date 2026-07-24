import { llmProviderKeys } from "@/lib/queryKeys";
import {
  type LlmProvidersResponse,
  listLlmProviders,
} from "@/services/llmProviders";
import { useQuery } from "@tanstack/react-query";

/** Cached BYOK 服务商列表 + 账号默认指针 + 部署能力（设置·模型配置 单一数据源）。 */
export function useLlmProviders() {
  return useQuery<LlmProvidersResponse>({
    queryKey: llmProviderKeys.list,
    queryFn: listLlmProviders,
    staleTime: 60_000,
    refetchOnMount: "always",
  });
}
