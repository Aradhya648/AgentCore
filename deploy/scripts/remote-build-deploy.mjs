#!/usr/bin/env node
/**
 * 后端兜底发布：GHA build-backend.yml 不可用时，在生产机构建 api 镜像并上线。
 *
 *   node deploy/scripts/remote-build-deploy.mjs <short-sha>
 *
 * 前置：deploy/.env.deploy.local 配好 DEPLOY_SSH_*；生产机 /opt/agentcore/.env 含 ACR 凭据。
 * 耗时：层缓存命中的热修（只改源码）约 1–2min；缓存被清或依赖/浏览器层变更时可达
 * 15–30min+——大头是 Playwright Chromium（~290MB 下载）与 apt 字体层，uv sync 有
 * cache mount 通常秒级。勿中途杀 SSH；进度可查 check-remote-build.mjs。
 */
import { loadDeployEnv, sshScript } from "./load-deploy-env.mjs";

loadDeployEnv();

const sha = process.argv[2]?.trim();
if (!sha) {
  console.error("usage: node deploy/scripts/remote-build-deploy.mjs <short-sha>");
  process.exit(1);
}

const script = `set -euo pipefail
HOME_DIR="\${AGENTCORE_HOME:-/opt/agentcore}"
REPO="\$HOME_DIR/repo"
SHA="${sha}"
cd "\$REPO"
git fetch --tags --force --quiet origin
git checkout "\$SHA"
ROOT_ENV="\$HOME_DIR/.env"
ACR_USER="\$(grep -E '^ACR_USERNAME=' "\$ROOT_ENV" | head -1 | cut -d= -f2-)"
ACR_PASS="\$(grep -E '^ACR_PASSWORD=' "\$ROOT_ENV" | head -1 | cut -d= -f2-)"
ACR_HOST="\$(grep -E '^ACR_REGISTRY=' "\$ROOT_ENV" | head -1 | cut -d= -f2-)"
ENVF="\${AGENTCORE_DEPLOY_DIR:-\$HOME_DIR/repo/deploy_f6d1637}/config/production.env"
IMAGE_REG="\$(grep -E '^IMAGE_REGISTRY=' "\$ENVF" | head -1 | cut -d= -f2-)"
echo "==> build+push api:\$SHA registry=\$IMAGE_REG"
echo "\$ACR_PASS" | docker login "\$ACR_HOST" -u "\$ACR_USER" --password-stdin
if ! docker buildx version >/dev/null 2>&1; then
  echo "==> installing docker-buildx-plugin"
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-buildx-plugin
fi
export DOCKER_BUILDKIT=1
BUILT_AT="\$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker buildx build --progress=plain --load \\
  -t "\${IMAGE_REG}/api:\${SHA}" -t "\${IMAGE_REG}/api:latest" \\
  --build-arg GIT_SHA="\$SHA" --build-arg BUILT_AT="\$BUILT_AT" apps/server
docker push "\${IMAGE_REG}/api:\${SHA}"
docker push "\${IMAGE_REG}/api:latest"
bash "\$REPO/deploy/scripts/finish-server.sh" "\$SHA"
`;

console.log(`→ remote build+deploy api:${sha}（层缓存命中约 1–2min；冷缓存可达 15–30min+）`);
sshScript(script);
