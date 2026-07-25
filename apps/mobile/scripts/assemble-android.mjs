#!/usr/bin/env node
/**
 * Sync package.json version into Gradle, then `assembleRelease`.
 * Requires android/keystore.properties for a signed release APK.
 *
 *   pnpm -C apps/mobile android:assemble
 */
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { run } from "../../../deploy/scripts/load-deploy-env.mjs";
import { syncAndroidVersion } from "./sync-android-version.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));
const ANDROID_DIR = join(__dir, "..", "android");

const keystoreProps = join(ANDROID_DIR, "keystore.properties");
if (!existsSync(keystoreProps)) {
  console.error(
    "Missing android/keystore.properties — refusing unsigned release assemble.",
  );
  console.error(
    "Copy keystore.properties.example → keystore.properties and fill in values.",
  );
  process.exit(1);
}

syncAndroidVersion();

const gradlew = process.platform === "win32" ? "gradlew.bat" : "./gradlew";
run("gradle assembleRelease", gradlew, ["assembleRelease"], {
  cwd: ANDROID_DIR,
});
