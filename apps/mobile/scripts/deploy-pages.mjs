#!/usr/bin/env node
/**
 * Build + deploy mobile web SPA to Cloudflare Pages.
 *
 *   pnpm -C apps/mobile deploy:pages
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
const API_URL = "https://app.fashitianxia.xyz/api";

loadDeployEnv();

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

console.log("✓ Mobile deploy complete — verify https://m.fashitianxia.xyz/");
