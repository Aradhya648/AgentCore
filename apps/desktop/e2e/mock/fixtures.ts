/**
 * Load real conformance vector fixtures (never hand-write SSE events).
 * §八: runtime segment boundaries are decided in `scripts.ts` by event type.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = resolve(
  here,
  "../../../../packages/protocol-conformance/fixtures",
);

export interface ConformanceEvent {
  type: string;
  payload?: Record<string, unknown>;
  timestamp?: string;
}

export interface ConformanceFixture {
  name: string;
  description?: string;
  events: ConformanceEvent[];
}

const cache = new Map<string, ConformanceFixture>();

export function loadFixture(name: string): ConformanceFixture {
  const hit = cache.get(name);
  if (hit) return hit;
  const raw = readFileSync(resolve(FIXTURES_DIR, `${name}.json`), "utf8");
  const parsed = JSON.parse(raw) as ConformanceFixture;
  if (parsed.name !== name) {
    throw new Error(
      `Fixture name mismatch: file ${name}.json reports name=${parsed.name}`,
    );
  }
  if (!Array.isArray(parsed.events) || parsed.events.length === 0) {
    throw new Error(`Fixture ${name} has no events`);
  }
  cache.set(name, parsed);
  return parsed;
}
