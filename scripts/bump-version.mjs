#!/usr/bin/env node
/**
 * Bump semver for an independent release track (API / desktop / mobile / admin / website).
 *
 *   node scripts/bump-version.mjs desktop patch
 *   node scripts/bump-version.mjs api minor
 *   node scripts/bump-version.mjs mobile 0.2.0
 *   node scripts/bump-version.mjs --dry-run desktop patch
 *
 * Tracks do NOT bump together — each artifact has its own semver (部署与运维 §7.1).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { syncAndroidVersion } from "../apps/mobile/scripts/sync-android-version.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dir, "..");

const TRACKS = {
  api: {
    label: "API (pyproject.toml)",
    path: join(ROOT, "apps/server/pyproject.toml"),
    read: readPyprojectVersion,
    write: writePyprojectVersion,
  },
  desktop: {
    label: "Desktop",
    path: join(ROOT, "apps/desktop/package.json"),
    read: readPackageVersion,
    write: writePackageVersion,
  },
  mobile: {
    label: "Mobile web",
    path: join(ROOT, "apps/mobile/package.json"),
    read: readPackageVersion,
    write: writePackageVersion,
  },
  admin: {
    label: "Admin console",
    path: join(ROOT, "apps/admin/package.json"),
    read: readPackageVersion,
    write: writePackageVersion,
  },
  website: {
    label: "Website",
    path: join(ROOT, "apps/website/package.json"),
    read: readPackageVersion,
    write: writePackageVersion,
  },
};

function parseArgs(argv) {
  let dryRun = false;
  const rest = [];
  for (const arg of argv) {
    if (arg === "--dry-run") dryRun = true;
    else rest.push(arg);
  }
  if (rest.length !== 2) {
    printHelp();
    process.exit(1);
  }
  const [trackName, bumpArg] = rest;
  const track = TRACKS[trackName];
  if (!track) {
    console.error(`Unknown track: ${trackName}`);
    printHelp();
    process.exit(1);
  }
  return { track: trackName, trackConfig: track, bumpArg, dryRun };
}

function printHelp() {
  console.log(`Usage: node scripts/bump-version.mjs [--dry-run] <track> <patch|minor|major|x.y.z>

Tracks: ${Object.keys(TRACKS).join(", ")}

Examples:
  node scripts/bump-version.mjs desktop patch   # 0.3.2 → 0.3.3
  node scripts/bump-version.mjs api minor       # 0.1.0 → 0.2.0
  node scripts/bump-version.mjs mobile 0.2.0    # explicit version`);
}

function parseSemver(version) {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)(?:-.+)?$/);
  if (!match) {
    throw new Error(`Invalid semver: ${version}`);
  }
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function nextVersion(current, bumpArg) {
  if (/^\d+\.\d+\.\d+(?:-.+)?$/.test(bumpArg)) {
    return bumpArg.split("-")[0];
  }
  const [major, minor, patch] = parseSemver(current);
  switch (bumpArg) {
    case "patch":
      return `${major}.${minor}.${patch + 1}`;
    case "minor":
      return `${major}.${minor + 1}.0`;
    case "major":
      return `${major + 1}.0.0`;
    default:
      throw new Error(`Unknown bump: ${bumpArg} (use patch|minor|major|x.y.z)`);
  }
}

function readPackageVersion(filePath) {
  const pkg = JSON.parse(readFileSync(filePath, "utf8"));
  if (!pkg.version) throw new Error(`No version field in ${filePath}`);
  return pkg.version;
}

function writePackageVersion(filePath, version) {
  const pkg = JSON.parse(readFileSync(filePath, "utf8"));
  pkg.version = version;
  writeFileSync(filePath, `${JSON.stringify(pkg, null, 2)}\n`, "utf8");
}

function readPyprojectVersion(filePath) {
  const text = readFileSync(filePath, "utf8");
  const match = text.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error(`No version = "..." in ${filePath}`);
  return match[1];
}

function writePyprojectVersion(filePath, version) {
  const text = readFileSync(filePath, "utf8");
  const next = text.replace(
    /^version\s*=\s*"[^"]+"/m,
    `version = "${version}"`,
  );
  if (next === text) throw new Error(`Failed to update version in ${filePath}`);
  writeFileSync(filePath, next, "utf8");
}

/** Website download fallback — must track desktop semver (部署与运维 §7.6). */
const DESKTOP_FALLBACK_FILES = [
  join(ROOT, "apps/website/functions/api/desktop-release.mjs"),
  join(ROOT, "apps/website/scripts/fetch-release.mjs"),
];

function syncDesktopFallbackVersion(version, { dryRun = false } = {}) {
  for (const filePath of DESKTOP_FALLBACK_FILES) {
    const text = readFileSync(filePath, "utf8");
    if (!/const FALLBACK_VERSION = "[^"]+"/.test(text)) {
      throw new Error(`No FALLBACK_VERSION const in ${filePath}`);
    }
    const next = text.replace(
      /const FALLBACK_VERSION = "[^"]+"/,
      `const FALLBACK_VERSION = "${version}"`,
    );
    if (next === text) {
      console.log(`  FALLBACK_VERSION already ${version} in ${filePath}`);
      continue;
    }
    if (dryRun) {
      console.log(`  would sync FALLBACK_VERSION → ${version} in ${filePath}`);
      continue;
    }
    writeFileSync(filePath, next, "utf8");
    console.log(`✓ Synced FALLBACK_VERSION → ${version} in ${filePath}`);
  }
}

function main() {
  const { track, trackConfig, bumpArg, dryRun } = parseArgs(process.argv.slice(2));
  const current = trackConfig.read(trackConfig.path);
  const next = nextVersion(current, bumpArg);

  console.log(`${trackConfig.label}: ${current} → ${next}${dryRun ? " (dry-run)" : ""}`);

  if (dryRun) {
    if (track === "desktop") syncDesktopFallbackVersion(next, { dryRun: true });
    if (track === "mobile") {
      console.log(`  would sync android versionName/versionCode → ${next}`);
    }
    return;
  }

  trackConfig.write(trackConfig.path, next);
  console.log(`✓ Updated ${trackConfig.path}`);

  if (track === "desktop") {
    syncDesktopFallbackVersion(next);
  }

  // APK versionName/versionCode live in android/app/build.gradle; keep in lockstep
  // with apps/mobile/package.json so release:android isn't the only writer.
  if (track === "mobile") {
    syncAndroidVersion(next);
  }
}

main();
