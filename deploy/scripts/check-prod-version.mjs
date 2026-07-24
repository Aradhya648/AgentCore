#!/usr/bin/env node
import { loadDeployEnv, sshScript } from "./load-deploy-env.mjs";

loadDeployEnv();
sshScript([
  'curl -sf http://127.0.0.1:8000/version || curl -sf http://localhost:8000/version',
  'echo ""',
  'docker compose -p agentcore ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null | head -5',
].join("\n"));
