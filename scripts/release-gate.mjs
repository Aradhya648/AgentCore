#!/usr/bin/env node
/**
 * Local release gate — isomorphic with `.github/workflows/ci.yml`, plus desktop
 * gaps (typecheck + conformance) that CI historically omitted.
 *
 *   pnpm release:gate                    # full run（发布验证必须全量）
 *   pnpm release:gate --from desktop     # 断点续跑：从 desktop 段开始
 *   pnpm release:gate --only backend     # 只跑单段（修复迭代用）
 *
 * Sections (in order): backend, contracts, desktop, mobile, admin.
 * When both contracts and desktop are enabled, they run in parallel child
 * processes (CI already splits them into separate jobs). Set
 * RELEASE_GATE_SERIAL=1 to force the old sequential order.
 * `--from`/`--only` are local iteration aids — a release still requires one
 * uninterrupted full pass.
 *
 * Any non-zero step fails the whole gate. Backend uses unit pytest
 * (`--ignore=tests/integration`) for local runnability; CI still runs full
 * pytest with Postgres.
 *
 * Contract drift (local): regen twice and require idempotence. Unlike CI's clean
 * checkout + `git diff` vs HEAD, a local WIP tree may already contain intentional
 * uncommitted artifact updates — those must still be committed before push; this
 * gate only proves regen is stable.
 */
import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import {
  createReadStream,
  existsSync,
  mkdirSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const GATE_SCRIPT = fileURLToPath(import.meta.url);
const ROOT = join(dirname(GATE_SCRIPT), "..");
const SERVER = join(ROOT, "apps", "server");

const CONTRACT_DRIFT_PATHS = [
  "apps/server/openapi.json",
  "packages/contract-rest-types/src/api.generated.ts",
  "packages/contract-types/src/eventTypes.generated.ts",
  "packages/contract-types/src/events.generated.ts",
  "packages/protocol-conformance/fixtures",
];

function run(label, cmd, args, opts = {}) {
  console.log(`\n→ ${label}`);
  const result = spawnSync(cmd, args, {
    cwd: opts.cwd ?? ROOT,
    stdio: "inherit",
    env: { ...process.env, ...opts.env },
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    console.error(`\n✗ release:gate FAILED — ${label}`);
    process.exit(result.status ?? 1);
  }
}

/** Run a long noisy command; keep full log on disk, only stream a short tail on failure.
 *
 * Inheriting megabytes of sim/LLM info logs into the agent terminal is slow enough on
 * Windows to trip pytest-timeout (60s) even when the test itself is fine.
 */
function runLogged(label, cmd, args, opts = {}) {
  console.log(`\n→ ${label}`);
  const logDir = join(tmpdir(), "agentcore-release-gate");
  mkdirSync(logDir, { recursive: true });
  const logPath = join(logDir, `${label.replace(/[^\w.-]+/g, "_")}.log`);
  const result = spawnSync(cmd, args, {
    cwd: opts.cwd ?? ROOT,
    encoding: "utf8",
    env: { ...process.env, ...opts.env },
    shell: process.platform === "win32",
    maxBuffer: 64 * 1024 * 1024,
  });
  const out = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  writeFileSync(logPath, out, "utf8");
  // Progress crumbs for the live terminal (last non-empty lines of pytest -q).
  const crumbs = out
    .split(/\r?\n/)
    .map((l) => l.trimEnd())
    .filter((l) => l && !l.includes("llm.request") && !l.includes("llm.response"));
  for (const line of crumbs.slice(-8)) console.log(line);
  console.log(`  (full log: ${logPath})`);
  if (result.status !== 0) {
    console.error(`\n✗ release:gate FAILED — ${label}`);
    console.error("--- log tail ---");
    console.error(crumbs.slice(-40).join("\n"));
    process.exit(result.status ?? 1);
  }
}

function section(title) {
  console.log(`\n══ ${title} ══`);
}

function listFiles(relPath) {
  const abs = join(ROOT, relPath);
  if (!existsSync(abs)) return [];
  const st = statSync(abs);
  if (st.isFile()) return [abs];
  const out = [];
  for (const name of readdirSync(abs)) {
    const child = join(abs, name);
    if (statSync(child).isDirectory()) {
      out.push(...listFiles(join(relPath, name)));
    } else {
      out.push(child);
    }
  }
  return out;
}

function hashFile(absPath) {
  return new Promise((resolve, reject) => {
    const h = createHash("sha256");
    const s = createReadStream(absPath);
    s.on("data", (chunk) => h.update(chunk));
    s.on("error", reject);
    s.on("end", () => resolve(h.digest("hex")));
  });
}

async function fingerprintContracts() {
  const files = CONTRACT_DRIFT_PATHS.flatMap(listFiles).sort();
  const parts = [];
  for (const f of files) {
    parts.push(`${f}\0${await hashFile(f)}`);
  }
  return createHash("sha256").update(parts.join("\n")).digest("hex");
}

function regenContracts() {
  run("gen-types", "node", ["scripts/gen-types.mjs"]);
  run("conformance export", "uv", ["run", "python", "-m", "agentcore.conformance.export"], {
    cwd: SERVER,
  });
}

async function assertContractIdempotent() {
  console.log("\n→ contract regen idempotence");
  const first = await fingerprintContracts();
  regenContracts();
  const second = await fingerprintContracts();
  if (first !== second) {
    console.error("\n✗ release:gate FAILED — contract regen not idempotent");
    console.error("  First and second regen produced different artifacts.");
    process.exit(1);
  }
  const porcelain = spawnSync(
    "git",
    ["status", "--porcelain", "--", ...CONTRACT_DRIFT_PATHS],
    { cwd: ROOT, encoding: "utf8", shell: process.platform === "win32" },
  );
  const dirty = (porcelain.stdout || "").trim();
  if (dirty) {
    console.log(
      "  note: contract artifacts differ from HEAD — include them in the release commit:",
    );
    console.log(
      dirty
        .split("\n")
        .map((l) => `    ${l}`)
        .join("\n"),
    );
  } else {
    console.log("  contract artifacts match HEAD");
  }
}

const SECTION_ORDER = ["backend", "contracts", "desktop", "mobile", "admin"];

function parseSectionArgs(argv) {
  let from = null;
  let only = null;
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === "--from" && argv[i + 1]) from = argv[++i];
    else if (argv[i] === "--only" && argv[i + 1]) only = argv[++i];
  }
  for (const [flag, value] of [["--from", from], ["--only", only]]) {
    if (value && !SECTION_ORDER.includes(value)) {
      console.error(`${flag} ${value}: unknown section (${SECTION_ORDER.join(", ")})`);
      process.exit(2);
    }
  }
  if (from && only) {
    console.error("--from and --only are mutually exclusive");
    process.exit(2);
  }
  return { from, only };
}

function sectionEnabled(name, { from, only }) {
  if (only) return name === only;
  if (from) return SECTION_ORDER.indexOf(name) >= SECTION_ORDER.indexOf(from);
  return true;
}

/** Spawn a nested `release:gate --only <section>` so contracts ∥ desktop can
 *  overlap wall-clock without blocking the parent on spawnSync. */
function runSectionChild(only) {
  return new Promise((resolve, reject) => {
    console.log(`\n↗ parallel child: --only ${only}`);
    const child = spawn(
      process.execPath,
      [GATE_SCRIPT, "--only", only],
      {
        cwd: ROOT,
        stdio: "inherit",
        env: { ...process.env, RELEASE_GATE_SERIAL: "1" },
        shell: false,
      },
    );
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0) resolve();
      else {
        reject(
          new Error(
            `release:gate --only ${only} failed (code=${code}, signal=${signal})`,
          ),
        );
      }
    });
  });
}

async function runContractsSection() {
  section("contracts");
  regenContracts();
  run("story-packs check", "pnpm", ["gen:story-packs:check"]);
  await assertContractIdempotent();
}

function runDesktopSection() {
  section("desktop");
  run("desktop lint", "pnpm", ["--filter", "agentcore-desktop", "lint"]);
  run("desktop typecheck", "pnpm", ["--filter", "agentcore-desktop", "typecheck"]);
  run("desktop test", "pnpm", [
    "--filter",
    "agentcore-desktop",
    "exec",
    "vitest",
    "run",
  ]);
  run("desktop conformance", "pnpm", ["--filter", "agentcore-desktop", "conformance"]);
  run("desktop shoot", "pnpm", ["--filter", "agentcore-desktop", "shoot"], {
    env: { SHOOT_FRAMES: "3" },
  });
  run("desktop smoke:webapp:ci", "pnpm", [
    "--filter",
    "agentcore-desktop",
    "smoke:webapp:ci",
  ]);
}

async function main() {
  const filter = parseSectionArgs(process.argv);
  const partial = filter.from || filter.only;
  console.log(
    `release:gate — local CI isomorphic gate${
      partial ? ` (PARTIAL: ${filter.only ? `only ${filter.only}` : `from ${filter.from}`} — 发布仍需全量绿)` : ""
    }`,
  );

  if (sectionEnabled("backend", filter)) {
    section("backend");
    run("ruff check", "uv", ["run", "ruff", "check", "."], { cwd: SERVER });
    run("mypy", "uv", ["run", "mypy"], { cwd: SERVER });
    // Migration head ↔ ORM metadata (offline). Catches DROP COLUMN/TABLE while
    // models/code still reference the old schema — the 2026-07-20 class of 500s.
    run(
      "schema gate",
      "uv",
      ["run", "python", "scripts/check_schema_gate.py"],
      { cwd: SERVER },
    );
    // Workspace hide rules are dual-sourced (Python _paths ↔ desktop
    // workspaceIgnore). Fail loudly when only one side is edited.
    run(
      "workspace ignore parity",
      "uv",
      ["run", "python", "scripts/check_workspace_ignore_parity.py"],
      { cwd: SERVER },
    );
    // `-n auto` (pytest-xdist): wall-clock cut for ~5k unit tests; integration
    // stays serial/excluded here (shared DB). Override with PYTEST_XDIST_N=0 to
    // force single-process when hunting order flakes.
    const xdistN = process.env.PYTEST_XDIST_N ?? "auto";
    const pytestArgs = [
      "run",
      "pytest",
      "--ignore=tests/integration",
      "--tb=short",
      "-q",
    ];
    if (xdistN !== "0" && xdistN !== "false") {
      pytestArgs.push("-n", xdistN);
    }
    runLogged("pytest (unit)", "uv", pytestArgs, {
      cwd: SERVER,
      env: { LOG_LEVEL: "WARNING" },
    });
  }

  const doContracts = sectionEnabled("contracts", filter);
  const doDesktop = sectionEnabled("desktop", filter);
  // Nested --only children set RELEASE_GATE_SERIAL to avoid re-entrant parallel.
  const parallelContractsDesktop =
    doContracts &&
    doDesktop &&
    !filter.only &&
    process.env.RELEASE_GATE_SERIAL !== "1";

  if (parallelContractsDesktop) {
    section("contracts ∥ desktop");
    console.log(
      "  (parallel children; set RELEASE_GATE_SERIAL=1 for sequential)",
    );
    // One upfront regen so desktop typecheck rarely races the contracts child's
    // first gen-types. Idempotence still re-regens inside the contracts child —
    // if that flakes, use RELEASE_GATE_SERIAL=1 (CI uses separate checkouts).
    regenContracts();
    await Promise.all([runSectionChild("contracts"), runSectionChild("desktop")]);
  } else {
    if (doContracts) await runContractsSection();
    if (doDesktop) runDesktopSection();
  }

  if (sectionEnabled("mobile", filter)) {
    section("mobile");
    run("mobile lint", "pnpm", ["--filter", "agentcore-mobile", "lint"]);
    run("mobile typecheck", "pnpm", ["--filter", "agentcore-mobile", "typecheck"]);
    run("mobile conformance", "pnpm", ["--filter", "agentcore-mobile", "conformance"]);
  }

  if (sectionEnabled("admin", filter)) {
    section("admin");
    run("admin typecheck", "pnpm", ["--filter", "agentcore-admin", "typecheck"]);
  }

  console.log(
    partial
      ? `\n✓ release:gate PARTIAL passed (${filter.only ? `only ${filter.only}` : `from ${filter.from}`}) — 发布前仍需完整 pnpm release:gate`
      : "\n✓ release:gate passed",
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
