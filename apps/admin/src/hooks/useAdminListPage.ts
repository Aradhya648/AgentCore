import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * List page in URL (`?page=N`) so drill-in → back keeps the roster page.
 * page≤1 clears the param; updates use replace to avoid history spam.
 */
export function useAdminListPage(): [number, (page: number) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("page"));
  const page = Number.isFinite(raw) && raw >= 1 ? Math.floor(raw) : 1;

  const setPage = useCallback(
    (next: number) => {
      setSearchParams(
        (prev) => {
          const sp = new URLSearchParams(prev);
          if (next <= 1) sp.delete("page");
          else sp.set("page", String(next));
          return sp;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return [page, setPage];
}
