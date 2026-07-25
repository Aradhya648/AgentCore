#!/usr/bin/env node
/**
 * Build + deploy mobile web SPA to Cloudflare Pages.
 *
 *   pnpm -C apps/mobile deploy:pages
 *
 * API URL：优先 AGENTCORE_APP_API_URL / VITE_API_URL / AGENTCORE_APP_HOST；
 * 未覆盖时由 apps/mobile/.env.production 烘焙（与桌面端同口径）。
 * 须先 loadDeployEnv()，再解析主机——否则 deploy/.env.deploy.local 里的
 * AGENTCORE_* 不会生效。
 */
import { join } from "node:path";
import {
  REPO_ROOT,
  assertBackendContractSatisfied,
  cfEnv,
  loadDeployEnv,
  run,
  runWranglerPagesDeploy,
} from "../../../deploy/scripts/load-deploy-env.mjs";

const PROJECT = "agentcore-mobile";

loadDeployEnv();

const APP_HOST = process.env.AGENTCORE_APP_HOST || "app.fashitianxia.xyz";
const MOBILE_HOST = process.env.AGENTCORE_MOBILE_HOST || "m.fashitianxia.xyz";
const API_URL =
  process.env.AGENTCORE_APP_API_URL ||
  process.env.VITE_API_URL ||
  `https://${APP_HOST}/api`;

await assertBackendContractSatisfied({ apiBaseUrl: API_URL });

const deployEnv = {
  ...cfEnv(),
  VITE_API_URL: API_URL,
};

run(
  "pnpm install (mobile workspace)",
  "pnpm",
  ["install", "--frozen-lockfile", "--filter", "agentcore-mobile..."],
  { env: deployEnv },
);

run(
  "pnpm --filter agentcore-mobile build",
  "pnpm",
  ["--filter", "agentcore-mobile", "build"],
  { env: deployEnv },
);

runWranglerPagesDeploy(PROJECT, join(REPO_ROOT, "apps/mobile/dist"));

console.log(`✓ Mobile deploy complete — verify https://${MOBILE_HOST}/`);
