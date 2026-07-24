#!/usr/bin/env bash
#
# AgentCore 全量数据库备份（部署与运维.md §7.7「备份与恢复策略」）。
#
# pg_dump 整库 → gzip 落 BACKUP_DIR，保留最近 N 份（轮转）。只备 PostgreSQL
# （不可重建的主数据）：Redis 是缓存丢了自愈、SearXNG 无状态，均不备。DATA_DIR 下
# 的长期记忆文件 / 工作区为文件系统数据，不在 pg_dump 覆盖内（需另行文件级备份）。
#
# 与 deploy-server.sh 的「迁移前快照」（pre-deploy-*.sql.gz）区分：本脚本产
# backup-*.sql.gz，轮转只清自己的前缀、不动迁移快照。配 systemd timer / cron 定时跑。
#
# 用法：
#   backup.sh                       # 一次全量备份 + 轮转
#
# 配置（可经环境或 $AGENTCORE_HOME/.env 覆盖，部署与运维.md §8.2）：
#   AGENTCORE_HOME   部署根目录          （默认 /opt/agentcore）
#   BACKUP_DIR       备份落点            （默认 $AGENTCORE_HOME/backups）
#   BACKUP_KEEP      保留最近几份        （默认 14，轮转删更旧的 backup-*）
#   COMPOSE_PROJECT  compose 项目名      （默认 agentcore）
#   ENV_FILE         compose env 文件    （默认 $REPO_DIR/deploy/config/production.env）
#   PG_USER / PG_DB  库用户 / 库名       （默认 agentcore / agentcore）

set -euo pipefail

AGENTCORE_HOME="${AGENTCORE_HOME:-/opt/agentcore}"
# 根 .env：与 deploy-server.sh 同源约定（运维级变量）。
if [[ -f "$AGENTCORE_HOME/.env" ]]; then
  set -a; . "$AGENTCORE_HOME/.env"; set +a
fi
REPO_DIR="${REPO_DIR:-$AGENTCORE_HOME/repo}"
BACKUP_DIR="${BACKUP_DIR:-$AGENTCORE_HOME/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-agentcore}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/deploy/config/production.env}"
PG_USER="${PG_USER:-agentcore}"
PG_DB="${PG_DB:-agentcore}"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[31m[error]\033[0m %s\n' "$*" >&2; }

COMPOSE_FILES=(
  -f "$REPO_DIR/deploy/docker-compose.server.yml"
  -f "$REPO_DIR/deploy/docker-compose.app.yml"
)
dc() { docker compose -p "$COMPOSE_PROJECT" "${COMPOSE_FILES[@]}" --env-file "$ENV_FILE" "$@"; }

[[ -f "$ENV_FILE" ]] || { err "env file not found: $ENV_FILE（从 production.env.example 复制并填值）"; exit 1; }
mkdir -p "$BACKUP_DIR"

ts="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/backup-$ts.sql.gz"
tmp="$out.partial"

log "AgentCore DB backup → $(basename "$out")"

# pipefail 保证 pg_dump 失败时整条管道失败（gzip 不掩盖）。先写 .partial、成功才改名，
# 避免被中断的半截文件冒充完整备份。
if ! dc exec -T postgres pg_dump -U "$PG_USER" "$PG_DB" | gzip >"$tmp"; then
  err "pg_dump 失败（postgres 容器是否在跑？compose 项目=$COMPOSE_PROJECT）"
  rm -f "$tmp"
  exit 1
fi

# 完整性：gzip -t + 非空校验，损坏/空即弃，不留垃圾。
if ! gzip -t "$tmp" 2>/dev/null || [[ ! -s "$tmp" ]]; then
  err "备份产物损坏或为空，丢弃：$tmp"
  rm -f "$tmp"
  exit 1
fi
mv "$tmp" "$out"
log "备份完成：$(basename "$out")（$(du -h "$out" | cut -f1)）"

# ── 轮转：只清本脚本前缀 backup-*.sql.gz，保留最近 BACKUP_KEEP 份（文件名时间序）──
mapfile -t backups < <(ls -1 "$BACKUP_DIR"/backup-*.sql.gz 2>/dev/null | sort)
total=${#backups[@]}
if (( total > BACKUP_KEEP )); then
  prune=$(( total - BACKUP_KEEP ))
  log "轮转：共 $total 份 > 保留 $BACKUP_KEEP，删最旧 $prune 份"
  for ((i = 0; i < prune; i++)); do
    rm -f "${backups[i]}" && warn "removed $(basename "${backups[i]}")"
  done
fi
