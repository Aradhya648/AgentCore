#!/usr/bin/env node
/**
 * Windows desktop release: bundle sidecar → electron-vite build → local package
 * → `gh release upload` (Mac-aligned; no electron-builder --publish).
 *
 *   pnpm -C apps/desktop release:win
 *   pnpm -C apps/desktop release:win -- --skip-draft   # draft already exists
 *
 * Prerequisites:
 *   - `gh auth login` with write access to Lawofall/AgentCore-releases
 *   - GH_TOKEN or `gh auth token` available
 *
 * Mirrors `.github/workflows/release-desktop.yml` Mac path:
 *   electron-builder --publish never → assert local assets → gh upload --clobber
 *   → parse `gh release view` asset list (missing → non-zero exit).
 *
 * See docs/05-平台与运维/部署与运维.md §7.6 — pre-create draft release.
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  REPO_ROOT,
  loadDeployEnv,
  run,
} from "../../../deploy/scripts/load-deploy-env.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));
const DESKTOP_DIR = join(__dir, "..");
const RELEASES_REPO = "Lawofall/AgentCore-releases";

const skipDraft = process.argv.includes("--skip-draft");

function readVersion() {
  const pkg = JSON.parse(
    readFileSync(join(DESKTOP_DIR, "package.json"), "utf8"),
  );
  return pkg.version;
}

function winAssetNames(version) {
  return [
    `AgentCore-${version}-win-x64.exe`,
    `AgentCore-${version}-win-x64.exe.blockmap`,
    "latest.yml",
  ];
}

function gh(args, { allowFail = false, capture = false } = {}) {
  const result = spawnSync("gh", args, {
    cwd: REPO_ROOT,
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
    encoding: capture ? "utf8" : undefined,
    shell: false,
    env: process.env,
  });
  if (!allowFail && result.status !== 0) {
    if (capture && result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  return capture
    ? {
        ok: result.status === 0,
        stdout: result.stdout ?? "",
        stderr: result.stderr ?? "",
      }
    : result.status === 0;
}

function ensureGhToken() {
  if (process.env.GH_TOKEN?.trim() || process.env.GITHUB_TOKEN?.trim()) return;
  const result = spawnSync("gh", ["auth", "token"], {
    encoding: "utf8",
    shell: false,
  });
  if (result.status === 0 && result.stdout?.trim()) {
    process.env.GH_TOKEN = result.stdout.trim();
    console.log("→ GH_TOKEN from gh auth token");
    return;
  }
  console.error("Missing GH_TOKEN — run `gh auth login` or export GH_TOKEN");
  process.exit(1);
}

function ensureDraftRelease(tag) {
  if (skipDraft) {
    console.log(
      `→ skip draft (--skip-draft); expecting ${tag} on ${RELEASES_REPO}`,
    );
    return;
  }
  console.log(`→ ensure draft release ${tag} on ${RELEASES_REPO}`);
  if (
    gh(["release", "view", tag, "--repo", RELEASES_REPO], { allowFail: true })
  ) {
    console.log(`  draft/release ${tag} already exists`);
    return;
  }
  gh([
    "release",
    "create",
    tag,
    "--repo",
    RELEASES_REPO,
    "--draft",
    "--title",
    tag,
    "--notes",
    "Desktop release (draft — publish after asset check).",
  ]);
}

function assertLocalAssets(releaseDir, version) {
  const names = winAssetNames(version);
  const paths = [];
  for (const name of names) {
    const path = join(releaseDir, name);
    if (!existsSync(path)) {
      console.error(`Missing local asset: ${path}`);
      process.exit(1);
    }
    paths.push(path);
  }
  console.log(`→ local assets ok: ${names.join(", ")}`);
  return paths;
}

function uploadAndVerify(tag, version, paths) {
  console.log(`→ gh release upload ${tag} --clobber`);
  gh([
    "release",
    "upload",
    tag,
    ...paths,
    "--repo",
    RELEASES_REPO,
    "--clobber",
  ]);

  const { stdout } = gh(
    ["release", "view", tag, "--repo", RELEASES_REPO, "--json", "assets"],
    { capture: true },
  );
  let assets;
  try {
    assets = JSON.parse(stdout).assets ?? [];
  } catch (err) {
    console.error(`Failed to parse gh release view JSON: ${err}`);
    process.exit(1);
  }
  const present = new Set(assets.map((a) => a.name));
  const required = winAssetNames(version);
  const missing = required.filter((name) => !present.has(name));
  if (missing.length > 0) {
    console.error(`Release ${tag} missing assets: ${missing.join(", ")}`);
    console.error(`Present: ${[...present].join(", ") || "(none)"}`);
    process.exit(1);
  }
  console.log(`✓ remote assets verified on ${tag}: ${required.join(", ")}`);
}

function main() {
  loadDeployEnv();
  ensureGhToken();

  const version = readVersion();
  const tag = `v${version}`;
  const releaseDir = join(DESKTOP_DIR, "release", version);

  console.log(`→ desktop release ${version} (Windows)`);
  ensureDraftRelease(tag);

  run("bundle:sidecar", "pnpm", ["bundle:sidecar"], { cwd: DESKTOP_DIR });
  run("electron-vite build", "pnpm", ["exec", "electron-vite", "build"], {
    cwd: DESKTOP_DIR,
  });
  // Mac-aligned: never publish via electron-builder (avoids #6676 / #2393).
  run(
    "electron-builder --win --publish never",
    "pnpm",
    ["exec", "electron-builder", "--win", "--publish", "never"],
    { cwd: DESKTOP_DIR, env: process.env },
  );

  const paths = assertLocalAssets(releaseDir, version);
  uploadAndVerify(tag, version, paths);

  // Brand CDN (R2) — user-facing downloads + electron-updater feed.
  run(
    "sync:release-cdn (desktop)",
    process.execPath,
    [
      join(REPO_ROOT, "deploy/scripts/sync-release-cdn.mjs"),
      "--desktop",
      releaseDir,
      "--version",
      version,
    ],
    { cwd: REPO_ROOT, env: process.env },
  );

  console.log("");
  console.log(`✓ Win release ${tag} built and uploaded to ${RELEASES_REPO}`);
  console.log(`  local: ${releaseDir}`);
  console.log(`  CDN: https://downloads.fashitianxia.xyz/desktop/`);
  console.log("");
  console.log("Win-only dev publish (optional):");
  console.log(
    `  gh release edit ${tag} --repo ${RELEASES_REPO} --draft=false --latest`,
  );
  console.log(
    "Then: pnpm -C apps/website deploy:pages (FALLBACK synced by bump-version desktop)",
  );
}

main();
