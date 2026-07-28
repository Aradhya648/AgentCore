import type { ConversationHydratePhase } from "@/components/chat/ConversationHydrateOverlay";
import { defaultTurnDetailView } from "@/components/graph/planCapabilities";
import type { Execution } from "@/stores/execution";
import type { TurnDetailView } from "@/stores/ui";

/**
 * Resolve the TurnDetailPage tab from URL + execution signals.
 * Call only after {@link isDebateViewPending} is false so `view=debate` never
 * falls through to graph while debate-ness is still unknown (闪图).
 */
export function resolveTurnDetailView(args: {
  requestedView: TurnDetailView | null;
  debate: boolean;
  showCompare: boolean;
  execution: Pick<Execution, "acts"> | null | undefined;
}): TurnDetailView {
  const { requestedView, debate, showCompare, execution } = args;
  if (requestedView === "compare" && showCompare) return "compare";
  if (requestedView === "debate" && debate) return "debate";
  if (requestedView === "graph") return "graph";
  return defaultTurnDetailView(execution, debate);
}

/**
 * `?view=debate` cold open: hold body (reuse hydrate overlay) until we can tell
 * whether the turn is a debate. Avoids graph → debate flash.
 */
export function isDebateViewPending(args: {
  requestedView: TurnDetailView | null;
  debate: boolean;
  hydratePhase: ConversationHydratePhase;
  /** Turn message carries an execution journal that still needs projection. */
  hasJournalToProject: boolean;
  hasExecution: boolean;
}): boolean {
  if (args.requestedView !== "debate") return false;
  if (args.debate) return false;
  if (args.hydratePhase === "loading") return true;
  if (args.hydratePhase === "error") return false;
  // ready: wait only while journal exists but runtime not projected yet
  return args.hasJournalToProject && !args.hasExecution;
}
