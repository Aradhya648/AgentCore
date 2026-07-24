#!/usr/bin/env node
/**
 * Build + deploy website to Cloudflare Pages (direct-upload).
 *
 *   pnpm -C apps/website deploy:pages
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  loadDeployEnv,
  run,
  runWranglerPagesDeploy,
} from "../../../deploy/scripts/load-deploy-env.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dir, "..");
const PROJECT = "agentcore-website";

loadDeployEnv();

run("pnpm build", "pnpm", ["build"], { cwd: ROOT });
runWranglerPagesDeploy(PROJECT, join(ROOT, "out"));

console.log("✓ Deploy complete — verify https://fashitianxia.xyz/download/");
