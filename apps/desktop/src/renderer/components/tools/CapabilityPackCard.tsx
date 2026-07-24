import { CatalogIconShell } from "@/components/ui";
import { catalogCategoryColorVar } from "@/lib/catalogColors";
import type { CapabilityPack } from "@/services/capabilities";
import { Layers } from "lucide-react";
import { SkillCard } from "./SkillCard";

/**
 * One capability-pack tile in the 能力图鉴: name / summary / nested skills.
 * Display-only — deployment gate decides availability; no user toggle.
 */
export function CapabilityPackCard({ pack }: { pack: CapabilityPack }) {
  const packColor = catalogCategoryColorVar("skill");

  return (
    <div
      data-capability-pack={pack.id}
      className="rounded-xl border border-border bg-card p-4"
    >
      <div className="flex items-start gap-3">
        <CatalogIconShell
          colorVar={packColor}
          className="mt-0.5 size-8 rounded-lg"
        >
          <Layers size={14} />
        </CatalogIconShell>
        <div className="min-w-0 flex-1">
          <h3 className="font-medium text-foreground text-sm">{pack.name}</h3>
          <p className="mt-1 text-muted-foreground text-xs">{pack.summary}</p>
        </div>
      </div>

      {pack.skills.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-muted-foreground text-xs">包内技能</p>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {pack.skills.map((skill) => (
              <SkillCard key={skill.name} skill={skill} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
