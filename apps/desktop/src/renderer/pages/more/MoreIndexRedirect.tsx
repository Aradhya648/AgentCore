import { useLlmProviders } from "@/hooks/useLlmProviders";
import { Navigate } from "react-router-dom";

/**
 * `/more` index 落点：platform 或已有平台/服务商 → 模型页；
 * byok 且无服务商、又无平台 → 服务商页（最短接 Key）。
 */
export function MoreIndexRedirect() {
  const { data, isLoading, isError } = useLlmProviders();

  if (isLoading) return null;
  if (isError || !data) {
    return <Navigate to="/more/model" replace />;
  }

  const hasProviders = data.providers.length > 0;
  const hasPlatform = data.platform_available;
  if (data.billing_mode === "platform" || hasPlatform || hasProviders) {
    return <Navigate to="/more/model" replace />;
  }
  return <Navigate to="/more/providers" replace />;
}
