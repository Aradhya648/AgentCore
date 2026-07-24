#!/usr/bin/env node
/**
 * Build + deploy the WEB CLIENT (the desktop renderer run in a plain browser — form A,
 * P1 多端：web = 「云工作区」一等入口) to the production server, served SAME-ORIGIN at
 * app.fashitianxia.xyz/ — the API is on the same Nginx at /api, so the SPA gets
 * first-party cookies and zero CORS. Mirrors apps/admin's server (scp + Nginx) deploy.
 *
 *   pnpm -C apps/desktop deploy:web
 *
 * Repeatable FILE SYNC only: build dist-web, publish index.html (Nginx try_files target),
 * tar, scp to the server, extract to /opt/agentcore/web/dist, and reload nginx. It does
 * NOT touch the Nginx config: the one-time wiring (a `location /` serving that dir with
 * SPA try_files, MERGED into the EXISTING app. server block that already proxies /api +
 * /storage — that block lives on the machine, not in this repo) is a manual step. See
 * deploy/nginx/app-web.conf and docs/05-平台与运维/部署与运维.md §二.
 *
 * SSH creds come from deploy/.env.deploy.local (DEPLOY_SSH_*). Deps are assumed installed
 * (run `pnpm install` first on a fresh clone — skipped to avoid the electron postinstall).
 * VITE_API_URL is pinned same-origin by apps/desktop/.env.production, so no override here.
 */
import { copyFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import {
  REPO_ROOT,
  assertBackendContractSatisfied,
  loadDeployEnv,
  run,
  scp,
  sshScript,
} from "../../../deploy/scripts/load-deploy-env.mjs";

// Same-origin API the built SPA calls (pinned in apps/desktop/.env.production).
const API_URL = "https://app.fashitianxia.xyz/api";
const WEB_ROOT = "/opt/agentcore/web";
const DESKTOP_DIR = join(REPO_ROOT, "apps/desktop");
const DIST = join(DESKTOP_DIR, "dist-web");
const TARBALL = join(REPO_ROOT, "web-dist.tgz");

loadDeployEnv();

// Guard against shipping a frontend newer than the live backend (前后端版本漂移) —
// runs before the build so a mismatch fails fast (see the 记忆·主题 404 incident).
await assertBackendContractSatisfied({ apiBaseUrl: API_URL });

run("pnpm --filter agentcore-desktop build:webapp", "pnpm", [
  "--filter",
  "agentcore-desktop",
  "build:webapp",
]);

// Nginx `try_files … /index.html` needs a root document named index.html; the multi-entry
// renderer build emits index.webapp.html (asset refs are absolute, so the copy is safe).
copyFileSync(join(DIST, "index.webapp.html"), join(DIST, "index.html"));
console.log("→ prepared dist-web (index.html)");

run("tar web dist", "tar", ["-czf", TARBALL, "-C", DESKTOP_DIR, "dist-web"]);
scp(TARBALL, "/tmp/web-dist.tgz");

sshScript(`set -euo pipefail
WEB_ROOT="${WEB_ROOT}"
mkdir -p "$WEB_ROOT/dist"
rm -rf "$WEB_ROOT/dist"
mkdir -p "$WEB_ROOT/dist"
tar xzf /tmp/web-dist.tgz -C "$WEB_ROOT/dist" --strip-components=1
rm -f /tmp/web-dist.tgz
echo "web static → $WEB_ROOT/dist ($(find "$WEB_ROOT/dist" -type f | wc -l) files)"
sudo nginx -t
sudo systemctl reload nginx
CODE="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: app.fashitianxia.xyz' http://127.0.0.1/ || true)"
echo "nginx reloaded; local probe app.fashitianxia.xyz/ → HTTP $CODE"
`);

unlinkSync(TARBALL);
console.log(
  "✓ Web client deploy complete — verify https://app.fashitianxia.xyz/",
);
