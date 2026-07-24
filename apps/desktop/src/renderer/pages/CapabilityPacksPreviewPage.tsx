import { PageContainer } from "@/components/layout/PageContainer";
import { CapabilityPackCard } from "@/components/tools/CapabilityPackCard";
import { CAPABILITY_PACK_PREVIEW_SCENES } from "@/preview/capabilityPackScenes";
import { FlaskConical } from "lucide-react";
import { useSearchParams } from "react-router-dom";

/**
 * Hidden preview (`#/preview/capability-packs`) for 能力包纯展示离线自检。
 * Deep-link: `#/preview/capability-packs?s=pack-listed`.
 */
export function CapabilityPacksPreviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scenes = CAPABILITY_PACK_PREVIEW_SCENES;
  const requested = searchParams.get("s");
  const current = scenes.find((s) => s.id === requested) ?? scenes[0] ?? null;
  const selected = current?.id ?? null;

  const select = (id: string) => setSearchParams({ s: id }, { replace: true });

  return (
    <div
      className="flex h-full min-h-0 w-full"
      data-preview-capability-packs={selected ?? ""}
    >
      <aside className="flex w-80 shrink-0 flex-col border-r border-border">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <FlaskConical size={18} className="shrink-0 text-primary" />
          <div className="min-h-0 min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold text-foreground">
              能力包 · 预览
            </h1>
            <p className="text-xs text-muted-foreground">
              {scenes.length} 个场景 · 离线自检
            </p>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <ul className="space-y-0.5">
            {scenes.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => select(s.id)}
                  className={`w-full rounded-lg px-3 py-2.5 text-left ${
                    selected === s.id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  }`}
                >
                  <span className="block truncate text-sm font-medium">
                    {s.title}
                  </span>
                  <span className="mt-0.5 block truncate text-xs opacity-80">
                    {s.intent}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContainer width="canvas" className="py-8">
          <h2 className="font-medium text-foreground text-sm">能力包</h2>
          <p className="mt-1 mb-3 text-muted-foreground text-xs">
            本部署已上架的垂直领域能力；包内技能已对全体用户生效，按需注入对话。
          </p>
          {current && (
            <div data-testid="capability-packs">
              <CapabilityPackCard pack={current.pack} />
            </div>
          )}
        </PageContainer>
      </div>
    </div>
  );
}
