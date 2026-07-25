#!/usr/bin/env node
/**
 * Sync desktop / Android release assets to the brand download host (self-hosted nginx).
 *
 *   pnpm sync:release-cdn --desktop <dir> --version <ver>
 *   pnpm sync:release-cdn --android <apkPath> --version <ver>
 *   pnpm sync:release-cdn --from-github              # bootstrap from published GH
 *   pnpm sync:release-cdn --from-github --desktop-only
 *   pnpm sync:release-cdn --from-github --android-only
 *   pnpm sync:release-cdn --install-nginx            # one-time nginx site on :8092
 *
 * Env (deploy/.env.deploy.local):
 *   DEPLOY_SSH_*                 (same as deploy:web / admin)
 *   AGENTCORE_DOWNLOADS_BASE     (optional; default https://downloads.fashitianxia.xyz)
 *   AGENTCORE_DOWNLOADS_HOST     (optional; nginx server_name / tunnel hostname)
 *   AGENTCORE_DOWNLOADS_ROOT     (optional; remote dir, default /opt/agentcore/downloads)
 *
 * Prerequisites: downloads-remote-install + Cloudflare Tunnel Public Hostname — §7.6b.
 */
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  REPO_ROOT,
  loadDeployEnv,
  requireEnv,
  run,
  scp,
  sshScript,
} from "./load-deploy-env.mjs";
import {
  DOWNLOADS_ANDROID_PREFIX,
  DOWNLOADS_DESKTOP_PREFIX,
  RELEASES_REPO,
  androidApkFilename,
  artifactUrlsForVersion,
  buildAndroidLatestJson,
  buildDesktopLatestJson,
  cdnUrl,
  macDmgFilename,
  winInstallerFilename,
} from "../../apps/website/functions/_lib/downloadsCdn.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  /** @type {Record<string, string | boolean>} */
  const out = {
    desktopDir: "",
    androidPath: "",
    version: "",
    fromGithub: false,
    desktopOnly: false,
    androidOnly: false,
    installNginx: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--desktop" && argv[i + 1]) out.desktopDir = argv[++i];
    else if (a === "--android" && argv[i + 1]) out.androidPath = argv[++i];
    else if (a === "--version" && argv[i + 1]) out.version = argv[++i];
    else if (a === "--from-github") out.fromGithub = true;
    else if (a === "--desktop-only") out.desktopOnly = true;
    else if (a === "--android-only") out.androidOnly = true;
    else if (a === "--install-nginx") out.installNginx = true;
    else if (a === "--help" || a === "-h") out.help = true;
  }
  return out;
}

function downloadsRoot() {
  return (
    process.env.AGENTCORE_DOWNLOADS_ROOT?.trim() || "/opt/agentcore/downloads"
  );
}

function downloadsHost() {
  return (
    process.env.AGENTCORE_DOWNLOADS_HOST?.trim() || "downloads.fashitianxia.xyz"
  );
}

/** Upload one local file to remote absolute path (creates parent dirs). */
function putRemoteFile(localPath, remoteAbsPath) {
  const remoteDir = dirname(remoteAbsPath).replace(/\\/g, "/");
  const tmpName = `ac-dl-${Date.now()}-${basename(localPath)}`;
  const tmpRemote = `/tmp/${tmpName}`;
  console.log(`→ scp ${basename(localPath)} → ${remoteAbsPath}`);
  scp(localPath, tmpRemote);
  sshScript(`set -euo pipefail
mkdir -p "${remoteDir}"
mv -f "${tmpRemote}" "${remoteAbsPath}"
`);
}

/** Upload every file under localDir into remoteAbsDir (flat). */
function putRemoteDirFiles(localDir, remoteAbsDir, names) {
  const staging = mkdtempSync(join(tmpdir(), "ac-cdn-up-"));
  const tarball = join(staging, "assets.tgz");
  try {
    const list = names.filter((n) => existsSync(join(localDir, n)));
    if (list.length === 0) return [];
    run(
      `tar ${list.length} assets`,
      "tar",
      ["-czf", tarball, "-C", localDir, ...list],
    );
    scp(tarball, "/tmp/ac-downloads-assets.tgz");
    sshScript(`set -euo pipefail
mkdir -p "${remoteAbsDir}"
tar xzf /tmp/ac-downloads-assets.tgz -C "${remoteAbsDir}"
rm -f /tmp/ac-downloads-assets.tgz
`);
    return list;
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

async function fetchJson(url) {
  const res = await fetch(url, {
    headers: {
      "User-Agent": "agentcore-sync-release-cdn",
      Accept: "application/json",
    },
  });
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return res.json();
}

async function downloadTo(url, dest) {
  const res = await fetch(url, {
    headers: { "User-Agent": "agentcore-sync-release-cdn" },
    redirect: "follow",
  });
  if (!res.ok) throw new Error(`download ${url} → HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  writeFileSync(dest, buf);
  return dest;
}

/**
 * Merge desktop latest.json: keep the other platform's filename when only
 * win or mac is being synced this run.
 */
async function mergeDesktopLatestJson(nextPartial) {
  const url = cdnUrl(`${DOWNLOADS_DESKTOP_PREFIX}/latest.json`);
  try {
    const prev = await fetchJson(url);
    return buildDesktopLatestJson({
      version: nextPartial.version || prev.version,
      winFilename: nextPartial.winFilename || prev.winFilename,
      macFilename:
        nextPartial.macFilename !== undefined
          ? nextPartial.macFilename
          : prev.macFilename || "",
      releaseNotesUrl: nextPartial.releaseNotesUrl || prev.releaseNotesUrl,
    });
  } catch {
    return buildDesktopLatestJson(nextPartial);
  }
}

function collectDesktopNames(version, desktopDir) {
  const winName = winInstallerFilename(version);
  const macName = macDmgFilename(version);
  const macZip = `AgentCore-${version}-mac-arm64.zip`;
  const candidates = [
    winName,
    `${winName}.blockmap`,
    "latest.yml",
    macName,
    `${macName}.blockmap`,
    macZip,
    `${macZip}.blockmap`,
    "latest-mac.yml",
  ];
  const present = candidates.filter((n) => existsSync(join(desktopDir, n)));
  return {
    present,
    hasWin: present.includes(winName),
    hasMac: present.includes(macName),
    winName,
    macName: present.includes(macName) ? macName : "",
  };
}

function syncDesktopDir(version, desktopDir) {
  if (!existsSync(desktopDir)) {
    console.error(`desktop dir not found: ${desktopDir}`);
    process.exit(1);
  }
  const flags = collectDesktopNames(version, desktopDir);
  if (flags.present.length === 0) {
    console.error(`No desktop assets found under ${desktopDir}`);
    process.exit(1);
  }
  if (!flags.hasWin && !flags.hasMac) {
    console.error(
      `Expected win and/or mac installer in ${desktopDir}; got: ${flags.present.join(", ")}`,
    );
    process.exit(1);
  }
  const root = downloadsRoot();
  putRemoteDirFiles(
    desktopDir,
    `${root}/${DOWNLOADS_DESKTOP_PREFIX}`,
    flags.present,
  );
  return flags;
}

async function writeDesktopManifest(version, { hasWin, hasMac, winName, macName }) {
  const manifest = await mergeDesktopLatestJson({
    version,
    ...(hasWin ? { winFilename: winName } : {}),
    ...(hasMac ? { macFilename: macName } : {}),
    releaseNotesUrl: artifactUrlsForVersion(version).releaseNotesUrl,
  });

  if (!manifest.winFilename) {
    console.error("desktop latest.json missing winFilename after merge");
    process.exit(1);
  }

  const tmpDir = mkdtempSync(join(tmpdir(), "ac-cdn-"));
  const tmp = join(tmpDir, "latest.json");
  writeFileSync(tmp, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  putRemoteFile(tmp, `${downloadsRoot()}/${DOWNLOADS_DESKTOP_PREFIX}/latest.json`);
  rmSync(tmpDir, { recursive: true, force: true });
  console.log(`✓ desktop latest.json → v${manifest.version}`);
  console.log(`  win: ${manifest.winFilename}`);
  console.log(`  mac: ${manifest.macFilename || "(none)"}`);
  return manifest;
}

async function syncAndroidFile(version, apkPath) {
  if (!existsSync(apkPath)) {
    console.error(`APK not found: ${apkPath}`);
    process.exit(1);
  }
  const name = basename(apkPath);
  const expected = androidApkFilename(version);
  if (name !== expected) {
    console.warn(`⚠ APK name ${name} ≠ expected ${expected} — uploading as ${name}`);
  }
  const root = downloadsRoot();
  putRemoteFile(apkPath, `${root}/${DOWNLOADS_ANDROID_PREFIX}/${name}`);
  const manifest = buildAndroidLatestJson({ version, filename: name });
  const tmpDir = mkdtempSync(join(tmpdir(), "ac-cdn-"));
  const tmp = join(tmpDir, "latest.json");
  writeFileSync(tmp, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  putRemoteFile(tmp, `${root}/${DOWNLOADS_ANDROID_PREFIX}/latest.json`);
  rmSync(tmpDir, { recursive: true, force: true });
  console.log(`✓ android latest.json → v${version} (${name})`);
  return manifest;
}

/**
 * Desktop "latest" on GitHub is NOT always /releases/latest (Android tags can win).
 * Prefer newest non-draft tag `v*` that has a win exe or latest.yml.
 */
async function fetchLatestDesktopGithubRelease() {
  const releases = await fetchJson(
    `https://api.github.com/repos/${RELEASES_REPO}/releases?per_page=30`,
  );
  if (!Array.isArray(releases)) throw new Error("GitHub releases list invalid");
  for (const release of releases) {
    if (release.draft) continue;
    const tag = String(release.tag_name ?? "");
    if (!/^v\d/i.test(tag) || tag.startsWith("android-")) continue;
    const assets = release.assets ?? [];
    const hasDesktop = assets.some(
      (a) =>
        /-win-x64\.exe$/i.test(a.name) ||
        a.name === "latest.yml" ||
        /-mac-arm64\.dmg$/i.test(a.name),
    );
    if (!hasDesktop) continue;
    return release;
  }
  throw new Error("No published desktop release found on GitHub");
}

async function syncFromGithub({ desktopOnly, androidOnly }) {
  const tmpRoot = mkdtempSync(join(tmpdir(), "ac-cdn-gh-"));
  try {
    if (!androidOnly) {
      const latest = await fetchLatestDesktopGithubRelease();
      const version = String(latest.tag_name).replace(/^v/, "");
      const assets = latest.assets ?? [];
      const dir = join(tmpRoot, "desktop");
      const { mkdirSync } = await import("node:fs");
      mkdirSync(dir, { recursive: true });
      const want = new Set([
        winInstallerFilename(version),
        `${winInstallerFilename(version)}.blockmap`,
        "latest.yml",
        macDmgFilename(version),
        `${macDmgFilename(version)}.blockmap`,
        `AgentCore-${version}-mac-arm64.zip`,
        `AgentCore-${version}-mac-arm64.zip.blockmap`,
        "latest-mac.yml",
      ]);
      for (const asset of assets) {
        if (!want.has(asset.name)) continue;
        console.log(`→ download GH ${asset.name}`);
        await downloadTo(asset.browser_download_url, join(dir, asset.name));
      }
      const flags = syncDesktopDir(version, dir);
      await writeDesktopManifest(version, flags);
    }

    if (!desktopOnly) {
      const releases = await fetchJson(
        `https://api.github.com/repos/${RELEASES_REPO}/releases?per_page=30`,
      );
      if (!Array.isArray(releases)) throw new Error("GitHub releases list invalid");
      let found = null;
      for (const release of releases) {
        if (release.draft) continue;
        const apk = (release.assets ?? []).find((a) =>
          /-android\.apk$/i.test(a.name),
        );
        if (!apk) continue;
        const tag = String(release.tag_name ?? "");
        const version = tag.startsWith("android-v")
          ? tag.slice("android-v".length)
          : tag.replace(/^v/, "");
        found = { version, apk };
        break;
      }
      if (!found) {
        console.warn("⚠ no published Android APK on GitHub — skip android sync");
      } else {
        const dest = join(tmpRoot, found.apk.name);
        console.log(`→ download GH ${found.apk.name}`);
        await downloadTo(found.apk.browser_download_url, dest);
        await syncAndroidFile(found.version, dest);
      }
    }
  } finally {
    rmSync(tmpRoot, { recursive: true, force: true });
  }
}

function installNginxRemote() {
  requireEnv("DEPLOY_SSH_HOST");
  const conf = join(REPO_ROOT, "deploy/nginx/downloads.conf");
  if (!existsSync(conf)) {
    console.error(`missing ${conf}`);
    process.exit(1);
  }
  scp(conf, "/tmp/downloads.conf");
  const script = readFileSync(
    join(REPO_ROOT, "deploy/scripts/downloads-remote-install.sh"),
    "utf8",
  );
  const host = downloadsHost();
  sshScript(`export DOWNLOADS_HOST=${JSON.stringify(host)}
${script}`);
}

async function main() {
  loadDeployEnv();
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(`Usage:
  pnpm sync:release-cdn --install-nginx
  pnpm sync:release-cdn --desktop <dir> --version <ver>
  pnpm sync:release-cdn --android <apk> --version <ver>
  pnpm sync:release-cdn --from-github [--desktop-only|--android-only]
`);
    process.exit(0);
  }

  // Touch SSH early so missing keys fail before long GH downloads.
  requireEnv("DEPLOY_SSH_HOST");
  requireEnv("DEPLOY_SSH_USER");

  if (args.installNginx) {
    installNginxRemote();
    return;
  }

  if (args.fromGithub) {
    console.log(`→ sync from GitHub → ${downloadsRoot()} @ ${downloadsHost()}`);
    await syncFromGithub({
      desktopOnly: Boolean(args.desktopOnly),
      androidOnly: Boolean(args.androidOnly),
    });
    console.log(`✓ CDN sync complete → ${cdnUrl("")}`);
    return;
  }

  if (!args.desktopDir && !args.androidPath) {
    console.error(
      "usage: pnpm sync:release-cdn --desktop <dir> --version <ver>\n" +
        "       pnpm sync:release-cdn --android <apk> --version <ver>\n" +
        "       pnpm sync:release-cdn --from-github\n" +
        "       pnpm sync:release-cdn --install-nginx",
    );
    process.exit(1);
  }
  if (!args.version) {
    console.error("Missing --version");
    process.exit(1);
  }

  if (args.desktopDir) {
    const flags = syncDesktopDir(args.version, args.desktopDir);
    await writeDesktopManifest(args.version, flags);
  }
  if (args.androidPath) {
    await syncAndroidFile(args.version, args.androidPath);
  }
  console.log(`✓ CDN sync complete → ${cdnUrl("")}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
