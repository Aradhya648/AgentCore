#!/usr/bin/env node
/**
 * Write apps/mobile/package.json version into android/app/build.gradle
 * (versionName + versionCode = major*1_000_000 + minor*1_000 + patch).
 *
 *   pnpm -C apps/mobile android:sync-version
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dir = dirname(fileURLToPath(import.meta.url));
const MOBILE_DIR = join(__dir, "..");
const GRADLE_PATH = join(MOBILE_DIR, "android", "app", "build.gradle");

export function readMobileVersion() {
  const pkg = JSON.parse(
    readFileSync(join(MOBILE_DIR, "package.json"), "utf8"),
  );
  return String(pkg.version);
}

/** @param {string} version */
export function versionCodeFromSemver(version) {
  const core = (version.split("-")[0] ?? version).trim();
  const bits = core.split(".").map((x) => {
    const n = Number.parseInt(x, 10);
    return Number.isFinite(n) ? n : 0;
  });
  const major = bits[0] ?? 0;
  const minor = bits[1] ?? 0;
  const patch = bits[2] ?? 0;
  return major * 1_000_000 + minor * 1_000 + patch;
}

/** @param {string} [version] */
export function syncAndroidVersion(version = readMobileVersion()) {
  const versionCode = versionCodeFromSemver(version);
  let gradle = readFileSync(GRADLE_PATH, "utf8");
  if (!/versionCode\s+\d+/.test(gradle) || !/versionName\s+"[^"]*"/.test(gradle)) {
    console.error(
      `Could not find versionCode / versionName in ${GRADLE_PATH}`,
    );
    process.exit(1);
  }
  gradle = gradle.replace(/versionCode\s+\d+/, `versionCode ${versionCode}`);
  gradle = gradle.replace(
    /versionName\s+"[^"]*"/,
    `versionName "${version}"`,
  );
  writeFileSync(GRADLE_PATH, gradle, "utf8");
  console.log(
    `→ android versionName=${version} versionCode=${versionCode}`,
  );
  return { version, versionCode };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  syncAndroidVersion();
}
