#!/usr/bin/env node
/**
 * Regenerate all committed frontend contract artifacts from backend sources.
 *
 *   1. OpenAPI → packages/contract-rest-types/src/api.generated.ts
 *   2. EventType enum → packages/contract-types/src/eventTypes.generated.ts
 *   3. SSE payload models → packages/contract-types/src/events.generated.ts
 *   4. InteractionKind + wire table → packages/contract-types/src/interactionKinds.generated.ts
 *   5. ErrorCode → packages/contract-types/src/errorCodes.generated.ts
 *
 * CI runs this then `git diff --exit-code` to block silent drift.
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SERVER = join(ROOT, "apps", "server");

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd: opts.cwd ?? ROOT, shell: process.platform === "win32" });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

console.log("gen:types — dump OpenAPI …");
run("uv", ["run", "python", "scripts/dump_openapi.py"], { cwd: SERVER });

console.log("gen:types — dump SSE event type union …");
run("uv", ["run", "python", "scripts/dump_sse_event_types.py"], { cwd: SERVER });

console.log("gen:types — dump SSE payload types …");
run("uv", ["run", "python", "scripts/dump_sse_payload_types.py"], { cwd: SERVER });

console.log("gen:types — dump InteractionKind + wire table …");
run("uv", ["run", "python", "scripts/dump_interaction_kinds.py"], { cwd: SERVER });

console.log("gen:types — dump ErrorCode catalog …");
run("uv", ["run", "python", "scripts/dump_error_codes.py"], { cwd: SERVER });

console.log("gen:types — openapi-typescript …");
run("pnpm", ["-C", join(ROOT, "packages", "contract-rest-types"), "gen"]);

console.log("gen:types — validate SSE contract alignment …");
run("uv", ["run", "python", "scripts/validate_sse_contract.py"], { cwd: SERVER });

console.log("gen:types — done");
