#!/usr/bin/env bash
# 生产机收尾上线：切 IMAGE_TAG → 拉镜像 → 停 api → 迁移 → schema gate → 起 api → 健康检查。
# 供 deploy-backend.yml SSH 调用；与 /opt/agentcore/finish.sh 同路径约定。
# VPC ACR 的 short-sha tag 可能晚于公网端点同步，拉不到时回退 latest 并本地打 tag。
#
# 顺序铁律（破坏性迁移）：停旧 api → alembic upgrade → schema gate → 起新 api。
# 禁止在旧容器仍接流量时 DROP COLUMN/TABLE（2026-07-20 单日 582×500 根因）。
set -euo pipefail

DEPLOY="${AGENTCORE_DEPLOY_DIR:-/opt/agentcore/repo/deploy}"
ENVF="$DEPLOY/config/production.env"
ROOT_ENV="${AGENTCORE_HOME:-/opt/agentcore}/.env"
TAG="${1:?usage: finish-server.sh <short-sha|latest>}"

if [[ ! "$TAG" =~ ^([0-9a-fA-F]{7,40}|latest)$ ]]; then
  echo "ERROR: invalid TAG '$TAG' (expected 7–40 hex chars or 'latest')"
  exit 1
fi

[[ -f "$ENVF" ]] || { echo "ERROR: $ENVF 不存在"; exit 1; }

echo "== [1/9] 切 IMAGE_TAG -> $TAG =="
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$TAG/" "$ENVF"
export IMAGE_TAG="$TAG"
export IMAGE_REGISTRY="$(grep -E '^IMAGE_REGISTRY=' "$ENVF" | head -1 | cut -d= -f2-)"
echo "registry=$IMAGE_REGISTRY tag=$IMAGE_TAG"

echo "== [2/9] 登录 ACR(VPC) =="
ACR_USER="$(grep -E '^ACR_USERNAME=' "$ROOT_ENV" | head -1 | cut -d= -f2-)"
ACR_PASS="$(grep -E '^ACR_PASSWORD=' "$ROOT_ENV" | head -1 | cut -d= -f2-)"
ACR_HOST="$(grep -E '^ACR_REGISTRY=' "$ROOT_ENV" | head -1 | cut -d= -f2-)"
echo "$ACR_PASS" | docker login "$ACR_HOST" -u "$ACR_USER" --password-stdin

IMAGE="${IMAGE_REGISTRY}/api:${IMAGE_TAG}"
echo "== [3/9] 拉 api 镜像 ($IMAGE) =="
# 同机构建路径（remote-build-deploy.mjs 的 buildx --load）镜像已在本机：sha tag 视作
# 不可变，直接复用、省一次 ACR 往返。浮动 latest 不享受此捷径（本机存在 ≠ 最新）。
# 本机缺镜像时照旧 pull + 回退 latest，失败语义不变。
if [[ "$IMAGE_TAG" != "latest" ]] && docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "镜像本机已存在（同机构建），跳过 pull"
elif ! docker pull "$IMAGE" 2>/dev/null; then
  echo "WARN: tag $IMAGE_TAG 在 VPC 不可用，回退 latest 并本地打 tag"
  docker pull "${IMAGE_REGISTRY}/api:latest"
  docker tag "${IMAGE_REGISTRY}/api:latest" "$IMAGE"
fi

COMPOSE=( docker compose -p agentcore -f "$DEPLOY/docker-compose.server.yml" -f "$DEPLOY/docker-compose.app.yml" --env-file "$ENVF" )
# gVisor 灰度：env 开了就叠 sandbox 层。快照目录若缺 sandbox 则回退仓库 deploy/
# （remote-build-deploy 已 checkout 的 tree）。
if grep -Eq '^[[:space:]]*GVISOR_ENABLED[[:space:]]*=[[:space:]]*(true|1|yes|True|TRUE)[[:space:]]*$' "$ENVF"; then
  _sandbox_yml=""
  for _cand in \
    "$DEPLOY/docker-compose.sandbox.yml" \
    "${AGENTCORE_HOME:-/opt/agentcore}/repo/deploy/docker-compose.sandbox.yml"; do
    if [[ -f "$_cand" ]]; then
      _sandbox_yml="$_cand"
      break
    fi
  done
  if [[ -z "$_sandbox_yml" ]]; then
    echo "ERROR: GVISOR_ENABLED=true 但找不到 docker-compose.sandbox.yml"
    exit 1
  fi
  COMPOSE+=(-f "$_sandbox_yml")
  echo "gVisor sandbox overlay: $_sandbox_yml"
fi

echo "== [4/9] 确认基础设施在线 + 等 postgres =="
"${COMPOSE[@]}" up -d postgres redis searxng
for i in $(seq 1 30); do
  "${COMPOSE[@]}" exec -T postgres pg_isready -U agentcore >/dev/null 2>&1 && break
  [[ $i -eq 30 ]] && { echo "ERROR: postgres 未就绪"; exit 1; }
  sleep 2
done
echo "postgres ready"

echo "== [5/9] 停 api（关闭旧代码 + 新 schema 窗口）=="
"${COMPOSE[@]}" stop api 2>/dev/null || true

echo "== [6/9] alembic upgrade head =="
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "== [7/9] schema gate (live) =="
"${COMPOSE[@]}" run --rm api python scripts/check_schema_gate.py --live

echo "== [8/9] 起 api =="
"${COMPOSE[@]}" up -d

echo "== [9/9] 健康检查 /readyz =="
ok=0
for i in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/readyz || true)"
  [[ "$code" = "200" ]] && { ok=1; break; }
  sleep 3
done
if [[ "$ok" != "1" ]]; then
  echo "ERROR: /readyz 未健康"
  "${COMPOSE[@]}" logs --tail 80 api
  exit 1
fi
echo "READYZ OK"
echo "--- /version ---"
curl -s http://127.0.0.1:8000/version
echo

# 健康后回收本机历史 api:<sha>（ACR 仍可回拉）。默认保留最近 5 个 tag + 容器在用镜像。
KEEP_API_IMAGES="${KEEP_API_IMAGES:-5}"
echo "== prune old api images (keep ${KEEP_API_IMAGES}) =="
_reg="${IMAGE_REGISTRY:-}"
if [[ -n "$_reg" ]]; then
  mapfile -t _tags < <(docker images "${_reg}/api" --format '{{.CreatedAt}}\t{{.Tag}}' \
    | sort -r | awk -F'\t' 'NR>0 && $2!="<none>" && $2!="latest" {print $2}')
  if ((${#_tags[@]} > KEEP_API_IMAGES)); then
    for _t in "${_tags[@]:KEEP_API_IMAGES}"; do
      docker rmi "${_reg}/api:${_t}" 2>/dev/null || true
    done
  fi
  # latest 浮动标签与当前 sha 共存；清掉已无引用的悬空层
  docker image prune -f >/dev/null 2>&1 || true
  docker builder prune -af --filter until=168h >/dev/null 2>&1 || true
fi
echo "FINISH DONE ✓"
