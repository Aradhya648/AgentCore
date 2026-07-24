/**
 * Audit inject-flow overlay — one implementation shared by every host. Builds the
 * data-inject overlay (⇢ edges + dimming) over a turn's structural edges and
 * reports whether any inject edge exists (toolbar toggle gate).
 */

import {
  type InjectGraphOverlay,
  buildInjectGraphOverlay,
} from "@/lib/causalInject";
import type { GraphEdge } from "@/stores/graph";
import { useMemo } from "react";

type CausalGraph = Parameters<typeof buildInjectGraphOverlay>[0];

export function useGraphInjectFlow({
  enabled,
  causalGraph,
  edges,
  litRunId,
  showAllInject,
}: {
  enabled: boolean;
  causalGraph: CausalGraph;
  /** Structural edges to overlay; null when there is no focused layout. */
  edges: GraphEdge[] | null;
  litRunId: string | null;
  showAllInject: boolean;
}): { injectOverlay: InjectGraphOverlay | null; injectFlowAvailable: boolean } {
  const injectOverlay = useMemo(
    () =>
      enabled && edges
        ? buildInjectGraphOverlay(causalGraph, edges, {
            focusRunId: litRunId,
            showAllInject,
          })
        : null,
    [enabled, causalGraph, edges, litRunId, showAllInject],
  );

  const injectFlowAvailable = useMemo(
    () =>
      enabled &&
      (causalGraph?.edges?.some((e) => e.kind === "inject") ?? false),
    [enabled, causalGraph],
  );

  return { injectOverlay, injectFlowAvailable };
}
