#!/usr/bin/env bash
# Deprecated entrypoint — use `pnpm sync:logs` (node scripts/sync-prod-logs.mjs).
# Kept so old muscle-memory `bash scripts/sync-prod-logs.sh` still works.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec node "$SCRIPT_DIR/sync-prod-logs.mjs" "$@"
