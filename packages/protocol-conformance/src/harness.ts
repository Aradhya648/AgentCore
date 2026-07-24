// Conformance harness — runs a frontend `fold` against the backend-exported golden
// vectors and reports ProjectedTurn drift (前端技术与架构 §十二).
//
// Vectors + golden are committed JSON under ./fixtures/, produced by the backend
// oracle (the single source: runtime/conformance/export.py). This package holds NO
// app code — each app runs its own `conformance` script that calls runConformance()
// with its fold, so the dependency points apps → this package (never the reverse).

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { SSEEvent } from "@agentcore/contract-types";
import type { ProjectedTurn } from "./projectedTurn";
import { isTurnFixture, type TurnFixtureWire } from "./fixtureKind";

/** A frontend's protocol fold under test: events[] → normalized ProjectedTurn. */
export type Fold = (events: SSEEvent[]) => ProjectedTurn;

/** One committed conformance case: a real-shaped event sequence + the backend
 * oracle's expected projection. */
export type Fixture = TurnFixtureWire;

const FIXTURES_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");

/** Load every committed turn-fold golden fixture (sorted by name for stable output). */
export function loadFixtures(): Fixture[] {
  let files: string[];
  try {
    files = readdirSync(FIXTURES_DIR).filter((f) => f.endsWith(".json"));
  } catch {
    throw new Error(
      `conformance: fixtures dir not found at ${FIXTURES_DIR} — run \`python -m agentcore.conformance.export\` (backend) to generate golden.`,
    );
  }
  return files
    .sort()
    .map((f) => JSON.parse(readFileSync(join(FIXTURES_DIR, f), "utf8")))
    .filter(isTurnFixture);
}

/** Structured comparison: the list of leaf field paths where `actual` diverges from
 * `golden`, each as `path: golden=… actual=…`. Empty ⇒ conformant. Designed for an
 * agent to read: it points at the exact diverging field/run/status, no other end to load. */
export function diffProjected(golden: unknown, actual: unknown): string[] {
  const out: string[] = [];
  walk(golden, actual, "", out);
  return out;
}

function walk(golden: unknown, actual: unknown, path: string, out: string[]): void {
  if (golden === actual) return;
  if (
    golden === null ||
    actual === null ||
    typeof golden !== "object" ||
    typeof actual !== "object"
  ) {
    if (!Object.is(golden, actual)) {
      out.push(`${path || "(root)"}: golden=${fmt(golden)} actual=${fmt(actual)}`);
    }
    return;
  }
  const goldArr = Array.isArray(golden);
  const actArr = Array.isArray(actual);
  if (goldArr !== actArr) {
    out.push(`${path || "(root)"}: golden=${fmt(golden)} actual=${fmt(actual)}`);
    return;
  }
  if (goldArr && actArr) {
    if (golden.length !== actual.length) {
      out.push(`${path}.length: golden=${golden.length} actual=${actual.length}`);
    }
    const n = Math.max(golden.length, actual.length);
    for (let i = 0; i < n; i++) walk(golden[i], actual[i], `${path}[${i}]`, out);
    return;
  }
  const g = golden as Record<string, unknown>;
  const a = actual as Record<string, unknown>;
  for (const key of new Set([...Object.keys(g), ...Object.keys(a)])) {
    walk(g[key], a[key], path ? `${path}.${key}` : key, out);
  }
}

function fmt(v: unknown): string {
  const s = JSON.stringify(v);
  if (s === undefined) return String(v);
  return s.length > 120 ? `${s.slice(0, 117)}…` : s;
}

export interface ConformanceResult {
  passed: number;
  failed: number;
}

/**
 * Run one fold against every fixture, print a single red/green report with
 * ProjectedTurn diffs, and set process.exitCode on any drift (CI gate). Returns the
 * tallies so a caller can aggregate multiple folds.
 */
export function runConformance(impl: { name: string; fold: Fold }): ConformanceResult {
  const fixtures = loadFixtures();
  let passed = 0;
  let failed = 0;
  console.log(`\nconformance · ${impl.name} · ${fixtures.length} vectors`);
  for (const fx of fixtures) {
    let diffs: string[];
    try {
      diffs = diffProjected(fx.projected, impl.fold(fx.events));
    } catch (e) {
      diffs = [`(threw) ${e instanceof Error ? e.stack ?? e.message : String(e)}`];
    }
    if (diffs.length === 0) {
      passed++;
      console.log(`  ✓ ${fx.name}`);
    } else {
      failed++;
      console.log(`  ✗ ${fx.name} — ${fx.description}`);
      for (const d of diffs.slice(0, 20)) console.log(`      ${d}`);
      if (diffs.length > 20) console.log(`      …(+${diffs.length - 20} more)`);
    }
  }
  console.log(`  ${failed === 0 ? "PASS" : "FAIL"} (${passed}/${fixtures.length})`);
  if (failed > 0) process.exitCode = 1;
  return { passed, failed };
}
