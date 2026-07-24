import { statusAccentText } from "@/components/ui/tone-presets";
import type { DebateUserInterjection } from "@/types/events";
import { UserRound } from "lucide-react";
import type { DebateSideModel } from "../model";

export function UserInterjection({
  interjection,
  sides,
}: {
  interjection: DebateUserInterjection;
  sides: DebateSideModel[];
}) {
  const nameBySideKey = new Map(sides.map((s) => [s.sideKey, s.name]));
  const target = interjection.target_key
    ? (nameBySideKey.get(interjection.target_key) ?? interjection.target_key)
    : null;
  const status = interjection.answered ? "✓ 已被承接" : "已发送 · 未及回应";
  const statusClass = interjection.answered
    ? statusAccentText.success
    : "text-muted-foreground";

  return (
    <div className="flex justify-end py-2">
      <div className="max-w-[90%] border-r-[3px] border-border pr-3 text-right">
        <div className="flex items-center justify-end gap-1.5 text-xs text-muted-foreground">
          <UserRound size={13} />
          <span>你</span>
          <span>·</span>
          <span>{target ? `定向 ${target}` : "全场"}</span>
          <span>·</span>
          <span className={statusClass}>{status}</span>
        </div>
        <p className="mt-1 text-sm text-foreground">{interjection.ask}</p>
      </div>
    </div>
  );
}
