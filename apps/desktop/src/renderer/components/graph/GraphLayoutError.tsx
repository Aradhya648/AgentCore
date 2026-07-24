import { AlertTriangle } from "lucide-react";
import { LAYOUT_FAILURE_USER_MESSAGE } from "./layoutFailure";

/** 协作图 ELK 布局失败的可见错误态（无重试——不做自愈）。 */
export function GraphLayoutError({
  detail,
}: {
  /** 技术细节（Error.message）；用户主文案固定。 */
  detail?: string | null;
}) {
  return (
    <div
      className="flex h-full w-full items-center justify-center p-6"
      role="alert"
    >
      <div className="flex max-w-sm flex-col items-center gap-3 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <AlertTriangle size={20} />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium text-foreground">协作图布局失败</p>
          <p className="text-xs text-muted-foreground">
            {LAYOUT_FAILURE_USER_MESSAGE}
          </p>
          {detail && detail !== LAYOUT_FAILURE_USER_MESSAGE && (
            <p className="mt-1 break-words text-xs text-destructive/80">
              {detail}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
