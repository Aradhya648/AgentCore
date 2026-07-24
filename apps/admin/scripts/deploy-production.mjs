#!/usr/bin/env node
/**
 * Build + deploy admin console to production server via SSH.
 *
 *   pnpm -C apps/admin deploy:production
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

const APP_HOST = process.env.AGENTCORE_APP_HOST || "app.example.com";
const OFFICE_HOST = process.env.AGENTCORE_OFFICE_HOST || "office.example.com";
const API_URL =
  process.env.AGENTCORE_APP_API_URL ||
  process.env.VITE_API_URL ||
  `https://${APP_HOST}/api`;
const TARBALL = join(REPO_ROOT, "admin-dist.tgz");
const NGINX_CONF = join(REPO_ROOT, "deploy/nginx/office-admin.conf");
const REMOTE_SCRIPT = join(REPO_ROOT, "deploy/scripts/admin-remote-install.sh");

loadDeployEnv();

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

sshScript(readFileSync(REMOTE_SCRIPT, "utf8"));

unlinkSync(TARBALL);

console.log(`✓ Admin deploy complete — verify https://${OFFICE_HOST}/`);
