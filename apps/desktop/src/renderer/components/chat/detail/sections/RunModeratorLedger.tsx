import { Button } from "@/components/ui";
import { MessagesSquare } from "lucide-react";
import type { ModeratorLedger } from "../debateModerator";
import { Section } from "./shared";

/**
 * 辩论主持人侧面板 L1「主持台账」：焦点 + 小结时间线；收场补开场白与收敛归因。
 * 进行中不渲染记分/比分。发言全文 / 质询 / 记分详情归属辩论室。
 */
export function RunModeratorLedger({
  ledger,
  onOpenDebateRoom,
}: {
  ledger: ModeratorLedger;
  onOpenDebateRoom?: () => void;
}) {
  return (
    <Section
      title="主持台账"
      action={
        onOpenDebateRoom ? (
          <Button
            variant="ghost"
            className="h-auto px-0 py-0 text-xs text-primary hover:bg-transparent"
            icon={<MessagesSquare size={12} />}
            onClick={onOpenDebateRoom}
          >
            打开辩论室
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-2 rounded-lg bg-muted p-3 text-xs leading-relaxed">
        {ledger.settled && ledger.opening && (
          <p className="text-foreground">
            <span className="text-muted-foreground">开场 · </span>
            {ledger.opening}
          </p>
        )}

        <ol className="space-y-2">
          {ledger.rounds.map((round) => (
            <li key={round.roundNo} className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground">
                  {round.roundNo > 0 ? `第 ${round.roundNo} 轮` : "本场"}
                </span>
                {round.inFlight && <span className="text-primary">进行中</span>}
              </div>
              {round.focus ? (
                <p className="text-foreground">
                  <span className="text-muted-foreground">焦点 · </span>
                  {round.focus}
                </p>
              ) : round.inFlight ? (
                <p className="text-muted-foreground">等待焦点…</p>
              ) : null}
              {round.summary ? (
                <p className="text-muted-foreground">
                  <span className="text-foreground/80">小结 · </span>
                  {round.summary}
                </p>
              ) : null}
            </li>
          ))}
        </ol>

        {ledger.settled && ledger.stopLabel && (
          <p className="border-t border-border/60 pt-2 text-foreground">
            <span className="text-muted-foreground">收场 · </span>
            {ledger.stopLabel}
          </p>
        )}
      </div>
    </Section>
  );
}
