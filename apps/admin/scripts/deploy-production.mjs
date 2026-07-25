#!/usr/bin/env node
/**
 * Build + deploy admin console to production server via SSH.
 *
 *   pnpm -C apps/admin deploy:production
 *
 * API URL：优先 AGENTCORE_APP_API_URL / VITE_API_URL / AGENTCORE_APP_HOST；
 * 未覆盖时由 apps/admin/.env.production 烘焙（与桌面端同口径）。
 * 须先 loadDeployEnv()，再解析主机——否则 deploy/.env.deploy.local 里的
 * AGENTCORE_* 不会生效。
 */
import { readFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import {
  REPO_ROOT,
  assertBackendContractSatisfied,
  loadDeployEnv,
  run,
  scp,
  sshScript,
} from "../../../deploy/scripts/load-deploy-env.mjs";

loadDeployEnv();

const APP_HOST = process.env.AGENTCORE_APP_HOST || "app.fashitianxia.xyz";
const OFFICE_HOST =
  process.env.AGENTCORE_OFFICE_HOST || "office.fashitianxia.xyz";
const API_URL =
  process.env.AGENTCORE_APP_API_URL ||
  process.env.VITE_API_URL ||
  `https://${APP_HOST}/api`;
const TARBALL = join(REPO_ROOT, "admin-dist.tgz");
const NGINX_CONF = join(REPO_ROOT, "deploy/nginx/office-admin.conf");
const REMOTE_SCRIPT = join(REPO_ROOT, "deploy/scripts/admin-remote-install.sh");

// Guard against shipping a frontend newer than the live backend (前后端版本漂移).
await assertBackendContractSatisfied({ apiBaseUrl: API_URL });

const buildEnv = {
  ...process.env,
  VITE_API_URL: API_URL,
  ORIGIN: `https://${OFFICE_HOST}`,
  OFFICE_HOST,
};

run(
  "pnpm install (admin workspace)",
  "pnpm",
  ["install", "--frozen-lockfile", "--filter", "agentcore-admin..."],
  { env: buildEnv },
);

run("pnpm build (admin)", "pnpm", ["--filter", "agentcore-admin", "build"], {
  env: buildEnv,
});

run("tar admin dist", "tar", ["-czf", TARBALL, "-C", "apps/admin", "dist"]);

scp(TARBALL, "/tmp/admin-dist.tgz");
scp(NGINX_CONF, "/tmp/office-admin.conf");

const deployDir = process.env.AGENTCORE_DEPLOY_DIR?.trim() || "";
const deployDirExport = deployDir
  ? `export AGENTCORE_DEPLOY_DIR=${JSON.stringify(deployDir)}\n`
  : "";

sshScript(
  [
    deployDirExport.trimEnd(),
    `export ORIGIN=${JSON.stringify(`https://${OFFICE_HOST}`)}`,
    `export OFFICE_HOST=${JSON.stringify(OFFICE_HOST)}`,
    readFileSync(REMOTE_SCRIPT, "utf8"),
  ]
    .filter(Boolean)
    .join("\n"),
);

unlinkSync(TARBALL);

console.log(`✓ Admin deploy complete — verify https://${OFFICE_HOST}/`);
