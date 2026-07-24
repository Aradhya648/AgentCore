#!/usr/bin/env bash
# Sync production AI logs to local for analysis.
#
# Usage:
#   pnpm sync:logs                    # sync both events + DB export
#   pnpm sync:logs --events-only      # sync only the event log file
#   pnpm sync:logs --export-only      # sync only the DB export
#
# Prerequisites:
#   - SSH access to the production server (configure SSH_HOST below or set env)
#   - Server must have LOG_FILE set and export_conversations.py run periodically
#
# Configuration (env vars or edit defaults below):
#   AGENTCORE_SSH    SSH target (default: root@<server-ip>)
#   AGENTCORE_HOME   Remote deployment root (default: /opt/agentcore)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SSH_HOST="${AGENTCORE_SSH:-root@your-server-ip}"
REMOTE_HOME="${AGENTCORE_HOME:-/opt/agentcore}"
LOCAL_EXPORT_DIR="$REPO_ROOT/logs/prod-export"

SYNC_EVENTS=true
SYNC_EXPORT=true

for arg in "$@"; do
    case "$arg" in
        --events-only)
            SYNC_EXPORT=false
            ;;
        --export-only)
            SYNC_EVENTS=false
            ;;
        -h|--help)
            sed -n '1,16p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--events-only | --export-only]" >&2
            exit 1
            ;;
    esac
done

if [[ "$SSH_HOST" == *"your-server-ip"* ]]; then
    echo "Error: set AGENTCORE_SSH to your production server (e.g. root@1.2.3.4)." >&2
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "Error: rsync is required but not found in PATH." >&2
    exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
    echo "Error: ssh is required but not found in PATH." >&2
    exit 1
fi

mkdir -p "$LOCAL_EXPORT_DIR"

if [[ "$SYNC_EVENTS" == "true" ]]; then
    echo "Syncing event log (+ rotation backups)..."
    # Remote glob (expanded by the remote shell) pulls prod.jsonl plus its
    # RotatingFileHandler backups prod.jsonl.1…N — without them, anything the
    # server already rotated out would silently vanish from local analysis.
    rsync -avz --progress \
        "$SSH_HOST:$REMOTE_HOME/logs/prod.jsonl*" \
        "$LOCAL_EXPORT_DIR/"
    # Local layout keeps the historical events.jsonl name (downstream scripts
    # default to it; log_stats/log_timeline auto-discover events.jsonl.N
    # backups next to it — observability/query/jsonl.discover_log_files).
    mv -f "$LOCAL_EXPORT_DIR/prod.jsonl" "$LOCAL_EXPORT_DIR/events.jsonl"
    for backup in "$LOCAL_EXPORT_DIR"/prod.jsonl.*; do
        [[ -f "$backup" ]] || continue
        suffix="${backup##*.}"
        if [[ "$suffix" =~ ^[0-9]+$ ]]; then
            mv -f "$backup" "$LOCAL_EXPORT_DIR/events.jsonl.$suffix"
        fi
    done
fi

if [[ "$SYNC_EXPORT" == "true" ]]; then
    echo "Running DB export on server..."
    ssh "$SSH_HOST" "cd $REMOTE_HOME && uv run python apps/server/scripts/export_conversations.py --days 7 --output data/export"
    echo "Syncing export files..."
    rsync -avz --progress \
        "$SSH_HOST:$REMOTE_HOME/data/export/" \
        "$LOCAL_EXPORT_DIR/"
fi

echo ""
echo "Done. Analyze with:"
echo "  cd apps/server"
echo "  uv run python scripts/log_stats.py --file ../../logs/prod-export/events.jsonl"
echo "  uv run python scripts/log_timeline.py --export-dir ../../logs/prod-export --recent"
echo "  uv run python scripts/log_timeline.py --export-dir ../../logs/prod-export <conv_id>"
