import { ApiError } from "@/services/api";
import { QueryClient } from "@tanstack/react-query";

/**
 * The app-wide React Query client (REST 数据层). Exported as a singleton so
 * imperative, non-React callers (the SSE turn pipeline, the composer's
 * create-conversation path) can read/write the same cache the hooks render from
 * — `queryClient.getQueryData` / `setQueryData` — instead of a parallel store.
 *
 * Defaults mirror the app's needs: a 4xx {@link ApiError} is a permanent client
 * error, so it is never retried; transport / 5xx failures get a couple of tries.
 * Window-focus refetch is off — Electron windows blur constantly and the data is
 * driven optimistically, so a focus refetch would only cause flicker.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false;
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});
