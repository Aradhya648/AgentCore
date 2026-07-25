import { BrandMark } from "@/components/brand/BrandMark";
import { Button } from "@/components/ui";

interface ServiceUnavailablePageProps {
  reason: string;
  onRetry: () => void;
}

/**
 * Shown when the backend can't be reached on startup (e.g. the database is
 * down), in place of a login form that would just fail. Mirrors LoginPage's
 * centered, minimal layout so the boot experience stays consistent.
 */
export function ServiceUnavailablePage({
  reason,
  onRetry,
}: ServiceUnavailablePageProps) {
  return (
    <div className="flex h-full w-full items-center justify-center bg-background p-6">
      <div className="w-full max-w-sm text-center">
        <BrandMark
          size="md"
          layout="stack"
          className="w-full items-center text-foreground"
        />
        <p className="mt-2 text-sm text-muted-foreground">服务暂时不可用</p>
        <p className="mt-4 text-sm text-destructive">{reason}</p>
        <Button className="mt-6 h-10 w-full" onClick={onRetry}>
          重试
        </Button>
      </div>
    </div>
  );
}
