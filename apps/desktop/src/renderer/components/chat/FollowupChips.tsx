import { Button } from "@/components/ui";
import { useComposerDraftStore } from "@/stores/composer";
import { Sparkles } from "lucide-react";

/**
 * CEO→用户「下一步推荐」: the just-finished turn's 2-4 predicted next steps, rendered as
 * one-click chips pinned just ABOVE the composer (see {@link ChatView}). Clicking a chip fills
 * the suggestion into the composer (via {@link useComposerDraftStore}) so the user can
 * review / edit before sending — same 回填 channel the non-blocking ask card uses, in
 * its default `append` mode: post-turn the composer is usually empty (so the chip text
 * just lands), and if the user HAS typed something the chip stacks on a new line rather
 * than clobbering it.
 *
 * Tied to the latest finished assistant turn (the caller gates on that); a「what now」
 * affordance that belongs where you type and stays put regardless of scroll — transport-
 * only, so a new turn or a refresh retires it. Renders nothing for an empty list.
 */
export function FollowupChips({ followups }: { followups: string[] }) {
  const fill = useComposerDraftStore((s) => s.fill);
  if (followups.length === 0) return null;

  return (
    <div className="px-4 pb-2">
      <div className="mb-1.5 flex items-center gap-1 text-xs text-muted-foreground">
        <Sparkles size={12} className="shrink-0" />
        <span>下一步</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {followups.map((text) => (
          <Button
            key={text}
            variant="neutral"
            className="h-auto whitespace-normal border border-border bg-card py-1 text-left text-muted-foreground hover:border-primary/40 hover:text-foreground"
            onClick={() => fill(text)}
          >
            {text}
          </Button>
        ))}
      </div>
    </div>
  );
}
