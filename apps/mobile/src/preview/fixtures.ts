import type { SSEEvent } from "@agentcore/contract-types";

export interface PreviewFixture {
  name: string;
  description: string;
  events: SSEEvent[];
}

interface RawFixture {
  name: string;
  description: string;
  events: SSEEvent[];
}

// Committed conformance vectors double as offline preview scenarios (same source as
// `pnpm conformance`). Drop a new JSON under packages/protocol-conformance/fixtures/
// and it appears here automatically.
const modules = import.meta.glob(
  "../../../../packages/protocol-conformance/fixtures/*.json",
  { eager: true },
) as Record<string, { default: RawFixture }>;

export const PREVIEW_FIXTURES: PreviewFixture[] = Object.entries(modules)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([, mod]) => ({
    name: mod.default.name,
    description: mod.default.description,
    events: mod.default.events,
  }));
