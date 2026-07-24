import { statusPillInline } from "@/components/ui/tone-presets";
import type { DebateConsensusMapItem, DebateSideInfo } from "@/types/events";
import { GitBranch, Map as MapIcon, Target, Users } from "lucide-react";
import type { ReactNode } from "react";
import { SideIdentity } from "../SideChip";
import { debateSideColorVar } from "../model";

/**
 * 圆桌产物：共识 / 分歧地图（按子题组织，crux 标注）。
 * 升级并替代旧「观点光谱」区；无 consensus_map 时由调用方回退 SidePointsGrid。
 */
export function ConsensusMap({
  items,
  sides,
  subtopics,
  strongestPoints,
  leaning,
  recommendation,
}: {
  items: DebateConsensusMapItem[];
  sides: DebateSideInfo[];
  subtopics?: string[] | null;
  strongestPoints?: Record<string, string>;
  leaning?: string;
  recommendation?: string;
}) {
  if (items.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <MapIcon size={15} className="text-muted-foreground" />
        共识 / 分歧地图
      </h3>
      {subtopics && subtopics.length > 0 && (
        <p className="text-xs text-muted-foreground">
          子题轴：{subtopics.join(" · ")}
        </p>
      )}
      <ul className="space-y-3">
        {items.map((item) => {
          const consensus = item.consensus ?? [];
          const divergences = item.divergences ?? [];
          return (
            <li
              key={item.topic}
              className="rounded-lg border border-border bg-card/40 p-3"
            >
              <h4 className="text-sm font-medium text-foreground">
                {item.topic}
              </h4>
              {consensus.length > 0 && (
                <MapBlock
                  icon={<Users size={13} />}
                  label="共识"
                  tone="success"
                  lines={consensus}
                />
              )}
              {divergences.length > 0 && (
                <MapBlock
                  icon={<GitBranch size={13} />}
                  label="分歧"
                  tone="muted"
                  lines={divergences}
                />
              )}
              {item.crux && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-foreground">
                  <Target
                    size={13}
                    className="mt-0.5 shrink-0 text-muted-foreground"
                  />
                  <span>
                    <span className={statusPillInline.primary}>crux</span>
                    <span className="ml-1.5">{item.crux}</span>
                  </span>
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {strongestPoints && Object.keys(strongestPoints).length > 0 && (
        <div>
          <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
            各视角核心主张
          </h4>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {sides.map((s) => (
              <div key={s.key} className="border-l-2 border-border pl-2.5">
                <SideIdentity
                  name={s.name}
                  colorVar={debateSideColorVar(s.key, s.name)}
                />
                <p className="mt-1 text-sm text-foreground">
                  {strongestPoints[s.key] ?? "—"}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
      {leaning && (
        <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
          <h4 className="mb-1 text-xs font-medium text-muted-foreground">
            综合观察
          </h4>
          <p className="text-sm text-foreground">{leaning}</p>
          {recommendation && (
            <p className="mt-1.5 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">建议：</span>
              {recommendation}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function MapBlock({
  icon,
  label,
  tone,
  lines,
}: {
  icon: ReactNode;
  label: string;
  tone: "success" | "muted";
  lines: string[];
}) {
  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
        {icon}
        <span className={statusPillInline[tone]}>{label}</span>
      </div>
      <ul className="space-y-1">
        {lines.map((line) => (
          <li key={line} className="text-sm text-foreground">
            {line}
          </li>
        ))}
      </ul>
    </div>
  );
}
