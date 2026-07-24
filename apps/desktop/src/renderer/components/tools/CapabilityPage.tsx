import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui";
import type { Capabilities } from "@/services/capabilities";
import { ChevronLeft, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useCapabilities } from "./useCapabilities";

/** Shared shell for the 能力 sub-pages (工具 / AI 提示词): back-to-工具箱 link,
 * page title + intro, and the loading / error / ready states around the shared
 * capability fetch. The page supplies a render function that gets the loaded data. */
export function CapabilityPage({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: ReactNode;
  children: (data: Capabilities) => ReactNode;
}) {
  const navigate = useNavigate();
  const { data, status, reload } = useCapabilities();

  return (
    <PageContainer width="canvas">
      <Button
        variant="ghost"
        onClick={() => navigate("/toolbox")}
        className="mb-4 h-auto gap-1 px-0 py-0 text-sm text-muted-foreground hover:text-foreground"
        icon={<ChevronLeft size={16} />}
      >
        工具箱
      </Button>

      <h1 className="font-semibold text-foreground text-xl">{title}</h1>
      <p className="mt-1 text-muted-foreground text-sm">{subtitle}</p>

      <div className="mt-6">
        {status === "loading" && (
          <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground text-sm">
            <Loader2 size={16} className="animate-spin" />
            加载中…
          </div>
        )}
        {status === "error" && (
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-border border-dashed py-16 text-center">
            <p className="text-muted-foreground text-sm">能力列表加载失败</p>
            <Button onClick={() => reload()}>重试</Button>
          </div>
        )}
        {status === "ready" && data && children(data)}
      </div>
    </PageContainer>
  );
}
