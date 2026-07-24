#!/usr/bin/env node
/**
 * Materialize town story-pack canonical → Unity StreamingAssets + backend package data.
 *
 * Canonical SoT: packages/town-story-packs/demo-story-packs.json
 *   → apps/town/Assets/StreamingAssets/Fixtures/demo-story-packs.json
 *   → apps/server/agentcore/simulation/data/demo-story-packs.json
 *
 * Usage:
 *   node scripts/sync-story-packs.mjs          # write both outputs
 *   node scripts/sync-story-packs.mjs --check  # fail if outputs ≠ canonical
 *
 * CI: contracts job runs --check (or sync + git diff) to block dual-source drift.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const CANONICAL = join(ROOT, "packages", "town-story-packs", "demo-story-packs.json");
const UNITY_OUT = join(
  ROOT,
  "apps",
  "town",
  "Assets",
  "StreamingAssets",
  "Fixtures",
  "demo-story-packs.json",
);
const BACKEND_OUT = join(
  ROOT,
  "apps",
  "server",
  "agentcore",
  "simulation",
  "data",
  "demo-story-packs.json",
);

const checkOnly = process.argv.includes("--check");

function normalizeJsonText(raw) {
  // Canonicalize via parse+stringify so whitespace-only drift is ignored in --check
  // when comparing semantic equality; writes always use stable indent-2 + trailing newline.
  const parsed = JSON.parse(raw);
  return JSON.stringify(parsed, null, 2) + "\n";
}

function readCanonical() {
  if (!existsSync(CANONICAL)) {
    console.error(`gen:story-packs — missing canonical: ${CANONICAL}`);
    process.exit(1);
  }
  const raw = readFileSync(CANONICAL, "utf8");
  try {
    return normalizeJsonText(raw);
  } catch (e) {
    console.error(`gen:story-packs — canonical JSON invalid: ${e.message}`);
    process.exit(1);
  }
}

function assertSame(label, path, expected) {
  if (!existsSync(path)) {
    console.error(`gen:story-packs — missing ${label}: ${path}`);
    process.exit(1);
  }
  const actual = normalizeJsonText(readFileSync(path, "utf8"));
  if (actual !== expected) {
    console.error(`gen:story-packs — drift: ${label} ≠ canonical`);
    console.error(`  expected: ${CANONICAL}`);
    console.error(`  actual:   ${path}`);
    console.error("  Fix: pnpm gen:story-packs");
    process.exit(1);
  }
}

const text = readCanonical();

if (checkOnly) {
  assertSame("Unity StreamingAssets", UNITY_OUT, text);
  assertSame("backend package data", BACKEND_OUT, text);
  console.log("gen:story-packs — check ok (canonical ↔ Unity ↔ backend)");
  process.exit(0);
}

mkdirSync(dirname(UNITY_OUT), { recursive: true });
mkdirSync(dirname(BACKEND_OUT), { recursive: true });
writeFileSync(UNITY_OUT, text, "utf8");
writeFileSync(BACKEND_OUT, text, "utf8");
// Keep canonical formatting identical to outputs.
writeFileSync(CANONICAL, text, "utf8");

console.log("gen:story-packs — wrote Unity StreamingAssets + backend simulation/data");
