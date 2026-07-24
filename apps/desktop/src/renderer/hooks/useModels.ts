import { modelKeys } from "@/lib/queryKeys";
import { type ModelCatalog, getModels } from "@/services/models";
import { useQuery } from "@tanstack/react-query";

/** Cached model catalog for the chat model picker (源自 `GET /v1/users/me/models`). */
export function useModels() {
  return useQuery<ModelCatalog>({
    queryKey: modelKeys.catalog,
    queryFn: getModels,
    staleTime: 60_000,
  });
}
