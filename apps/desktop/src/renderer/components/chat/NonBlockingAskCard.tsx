import { DecisionCard } from "@/components/ui";
import type { NonBlockingAskDisplay } from "@/stores/conversation";

export function NonBlockingAskCard({ ask }: { ask: NonBlockingAskDisplay }) {
  return (
    <DecisionCard tone="primary" animate className="overflow-hidden p-0">
      <div className="space-y-3 px-3 pb-3 pt-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-primary">
            顺便确认下（已按默认继续）
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {ask.question}
          </p>
          {ask.context && (
            <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
              {ask.context}
            </p>
          )}
        </div>

        {ask.assumptions.length > 0 && (
          <div className="rounded-lg bg-muted/20 px-2.5 py-2">
            <p className="text-xs font-medium text-muted-foreground">
              默认方案
            </p>
            <div className="mt-1 space-y-0.5">
              {ask.assumptions.map((a) => (
                <div key={a.id} className="flex gap-1.5 text-xs">
                  <span className="w-14 shrink-0 text-muted-foreground">
                    {a.label}
                  </span>
                  <span className="min-w-0 flex-1 whitespace-pre-wrap text-foreground">
                    {a.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {ask.questions.map((q) => (
          <div key={q.id} className="min-w-0">
            <p className="whitespace-pre-wrap text-sm text-foreground">
              {q.prompt}
            </p>
            {q.kind !== "text" && q.options.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {q.options.map((opt) => (
                  <li key={opt.label}>
                    · {opt.label}
                    {opt.recommended ? "（推荐）" : ""}
                    {q.default && opt.label === q.default ? "（默认）" : ""}
                  </li>
                ))}
              </ul>
            )}
            {q.kind === "text" && q.default && (
              <p className="mt-1 text-xs text-muted-foreground">
                默认：{q.default}
              </p>
            )}
          </div>
        ))}

        <p className="text-xs text-muted-foreground">
          不回复我就按默认继续；若要改口，在下方输入框说明即可。
        </p>
      </div>
    </DecisionCard>
  );
}
