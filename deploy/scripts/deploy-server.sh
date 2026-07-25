#!/usr/bin/env bash
#
# AgentCore 一键部署 / 回退脚本（部署与运维.md §三 CI/CD）。
#
#   git checkout <sha> → pull 镜像 → 起基础设施 → 迁移前 DB 快照 →
#   停 api → alembic upgrade head → schema gate → compose up → /readyz → 记 SHA
#
# 用法：
#   deploy-server.sh [<sha>|<tag>|latest]    # 缺省 latest（= origin/<branch> HEAD）
#
# 正向部署传新 SHA；回退传旧 SHA（镜像在 ACR 秒级切换，回退自动跳过正向迁移，
# 库需对齐时从 backups/ 手动恢复——见 §7.7）。
#
# 配置（可经环境或 $AGENTCORE_HOME/.env 覆盖，部署与运维.md §8.2）：
#   AGENTCORE_HOME   部署根目录            （默认 /opt/agentcore）
#   GIT_BRANCH       latest 解析的分支      （默认 master，对齐 ci.yml / 仓库主干）
#   IMAGE_REGISTRY   ACR 仓库（含命名空间） （compose 拉取用）
#   ACR_USERNAME/ACR_PASSWORD   ACR 登录凭据（缺省则跳过 docker login）
#   HEALTH_URL       健康检查地址          （默认 http://127.0.0.1:8000/readyz）
#   SKIP_SNAPSHOT=1  跳过迁移前 DB 快照（应急用）

set -euo pipefail

# ── 自更新防护：先把自己拷到临时副本再 exec，避免 git checkout 中途改写本脚本
#    导致运行中的 shell 读到半截内容（部署与运维.md §三）。──
if [[ "${_DEPLOY_REEXEC:-}" != "1" ]]; then
  _self_tmp="$(mktemp)"
  cp "$0" "$_self_tmp"
  chmod +x "$_self_tmp"
  export _DEPLOY_REEXEC=1
  exec "$_self_tmp" "$@"
fi
trap 'rm -f "$0"' EXIT  # 此处 $0 是临时副本

# ── 分段计时（量化各阶段耗时）──
SECONDS=0
_stage_last=0
stage() { printf '  [+%4ds | %3ds] %s\n' "$SECONDS" "$((SECONDS - _stage_last))" "$1"; _stage_last=$SECONDS; }
log()   { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn()  { printf '\033[33m[warn]\033[0m %s\n' "$*" >&2; }
err()   { printf '\033[31m[error]\033[0m %s\n' "$*" >&2; }

# ── 配置 ──
AGENTCORE_HOME="${AGENTCORE_HOME:-/opt/agentcore}"
# 根 .env：ACR 凭据 + 镜像标签等部署级变量（非应用密钥）。
if [[ -f "$AGENTCORE_HOME/.env" ]]; then
  set -a; . "$AGENTCORE_HOME/.env"; set +a
fi
REPO_DIR="${REPO_DIR:-$AGENTCORE_HOME/repo}"
BACKUP_DIR="${BACKUP_DIR:-$AGENTCORE_HOME/backups}"
SHA_FILE="${SHA_FILE:-$AGENTCORE_HOME/.last-deployed-sha}"
GIT_BRANCH="${GIT_BRANCH:-master}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/deploy/config/production.env}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-agentcore}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/readyz}"
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-3}"
TARGET_REF="${1:-latest}"

COMPOSE_FILES=(
  -f "$REPO_DIR/deploy/docker-compose.server.yml"
  -f "$REPO_DIR/deploy/docker-compose.app.yml"
)
# gVisor 灰度：GVISOR_ENABLED=true 时自动叠 sandbox 层（seccomp/apparmor + mem_limit）。
# 只开 env 不叠层 → 沙箱起不来，启动期健康探测失败不拒启（fail-safe）：打
# sandbox.cloud_health_failed warning、执行类整类不装配、能力行如实显示未装配。
# 脚本自动叠层正是为免此降级，与 部署与运维.md §云端执行灰度 口径一致。
_gvisor_on=0
if [[ -f "$ENV_FILE" ]] && grep -Eq '^[[:space:]]*GVISOR_ENABLED[[:space:]]*=[[:space:]]*(true|1|yes|True|TRUE)[[:space:]]*$' "$ENV_FILE"; then
  _gvisor_on=1
  _sandbox_yml="$REPO_DIR/deploy/docker-compose.sandbox.yml"
  if [[ -f "$_sandbox_yml" ]]; then
    COMPOSE_FILES+=(-f "$_sandbox_yml")
  else
    err "GVISOR_ENABLED=true 但缺少 $_sandbox_yml"
    exit 1
  fi
fi
dc() { docker compose -p "$COMPOSE_PROJECT" "${COMPOSE_FILES[@]}" --env-file "$ENV_FILE" "$@"; }

[[ -f "$ENV_FILE" ]] || { err "env file not found: $ENV_FILE（从 production.env.example 复制并填值）"; exit 1; }

log "AgentCore deploy — ref=$TARGET_REF branch=$GIT_BRANCH home=$AGENTCORE_HOME"
if [[ "$_gvisor_on" -eq 1 ]]; then
  log "gVisor sandbox overlay ON（docker-compose.sandbox.yml）"
fi

# ── 1. 解析目标 SHA（latest=分支 HEAD；否则解析 tag/短 SHA 为具体提交）──
cd "$REPO_DIR"
git fetch --quiet --tags --prune origin
if [[ "$TARGET_REF" == "latest" ]]; then
  TARGET_SHA="$(git rev-parse "origin/$GIT_BRANCH")"
else
  TARGET_SHA="$(git rev-parse "${TARGET_REF}^{commit}")"
fi
SHORT_SHA="$(git rev-parse --short "$TARGET_SHA")"
stage "resolved $TARGET_REF → $SHORT_SHA"

# ── 2. 判定回退（目标非当前部署的后代 → 回退，跳过正向迁移）──
PREV_SHA="$(cat "$SHA_FILE" 2>/dev/null || true)"
IS_ROLLBACK=0
if [[ -n "$PREV_SHA" ]] && ! git merge-base --is-ancestor "$PREV_SHA" "$TARGET_SHA" 2>/dev/null; then
  IS_ROLLBACK=1
  warn "目标 $SHORT_SHA 非已部署 ${PREV_SHA:0:7} 的后代 → 按【回退】处理：跳过正向迁移"
fi

# ── 3. 检出目标代码（detached HEAD；脚本已从临时副本运行，改写本文件无碍）──
git checkout --quiet "$TARGET_SHA"
export IMAGE_TAG="$SHORT_SHA"
stage "checked out $SHORT_SHA"

# ── 4. 登录 ACR 并拉取镜像（无凭据则跳过 login，假设已登录或公共镜像）──
if [[ -n "${ACR_USERNAME:-}" && -n "${ACR_PASSWORD:-}" && -n "${IMAGE_REGISTRY:-}" ]]; then
  printf '%s' "$ACR_PASSWORD" | docker login "${IMAGE_REGISTRY%%/*}" -u "$ACR_USERNAME" --password-stdin >/dev/null
  stage "ACR login"
fi
dc pull --quiet
stage "pulled images (api:$SHORT_SHA)"

# ── 5. 起基础设施并等就绪（迁移前提）──
dc up -d postgres redis searxng
for ((i = 1; i <= 30; i++)); do
  dc exec -T postgres pg_isready -U agentcore >/dev/null 2>&1 && break
  [[ $i -eq 30 ]] && { err "postgres 未就绪，终止部署"; exit 1; }
  sleep 2
done
stage "infra up + postgres ready"

# ── 6. 迁移前 DB 快照（仅正向；失败即终止，避免无快照迁移，见 §7.7）──
if [[ "$IS_ROLLBACK" -eq 0 && "${SKIP_SNAPSHOT:-0}" != "1" ]]; then
  mkdir -p "$BACKUP_DIR"
  snapshot="$BACKUP_DIR/pre-deploy-$(date +%Y%m%d-%H%M%S)-$SHORT_SHA.sql.gz"
  dc exec -T postgres pg_dump -U agentcore agentcore | gzip >"$snapshot"
  stage "db snapshot → $(basename "$snapshot")"
fi

# ── 7. 停 api → 迁移 → schema gate（仅正向）──
# 破坏性迁移期间旧 api 不得继续接流量（2026-07-20 UndefinedColumn/Table 窗口）。
if [[ "$IS_ROLLBACK" -eq 0 ]]; then
  dc stop api 2>/dev/null || true
  stage "api stopped before migrate"
  dc run --rm api alembic upgrade head
  stage "alembic upgrade head"
  dc run --rm api python scripts/check_schema_gate.py --live
  stage "schema gate (live)"
else
  warn "回退：跳过 alembic（如 schema 不一致，从 $BACKUP_DIR 手动恢复对齐）"
fi

# ── 8. 重建应用容器（切流量到新镜像）──
dc up -d
stage "compose up"

# ── 9. 健康检查（/readyz 含 DB 探测；失败不记 SHA、退出非零）──
ok=0
for ((i = 1; i <= HEALTH_RETRIES; i++)); do
  if curl -fsS -o /dev/null --max-time 5 "$HEALTH_URL"; then ok=1; break; fi
  sleep "$HEALTH_INTERVAL"
done
if [[ "$ok" -ne 1 ]]; then
  err "健康检查失败（${HEALTH_URL}，约 $((HEALTH_RETRIES * HEALTH_INTERVAL))s）— 未记录 SHA。排查：dc logs api"
  exit 1
fi
stage "healthy"

# ── 10. 记录成功部署的 SHA（仅健康后）──
echo "$TARGET_SHA" >"$SHA_FILE"

# ── 11. 回收本机历史 api:<sha>（健康后；ACR 仍可回拉）。默认保留最近 5 个。──
KEEP_API_IMAGES="${KEEP_API_IMAGES:-5}"
if [[ -n "${IMAGE_REGISTRY:-}" ]]; then
  mapfile -t _old_tags < <(docker images "${IMAGE_REGISTRY}/api" --format '{{.CreatedAt}}\t{{.Tag}}' \
    | sort -r | awk -F'\t' '$2!="<none>" && $2!="latest" {print $2}')
  if ((${#_old_tags[@]} > KEEP_API_IMAGES)); then
    for _t in "${_old_tags[@]:KEEP_API_IMAGES}"; do
      docker rmi "${IMAGE_REGISTRY}/api:${_t}" 2>/dev/null || true
    done
    stage "pruned old api tags (keep ${KEEP_API_IMAGES})"
  fi
  docker image prune -f >/dev/null 2>&1 || true
  docker builder prune -af --filter until=168h >/dev/null 2>&1 || true
fi

log "部署成功 ✅  $SHORT_SHA  （总耗时 ${SECONDS}s）"
