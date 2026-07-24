#!/usr/bin/env bash
#
# AgentCore 健康巡检 + 告警（部署与运维.md §7.8「可观测·巡检」）。
#
# 单次探测 /readyz（含 DB 探测，未就绪回 503）→ 连续 N 次失败才告警（防抖）→
# 恢复时补一条恢复通知。由 systemd timer（或 cron）每 1–2 分钟驱动一次；本脚本
# 自身无状态循环，连续失败计数落 STATE_FILE 跨次累积。
#
# 告警出口是「可插拔 notifier」：配了 ALERT_WEBHOOK_URL（飞书群机器人）就推飞书，
# 没配就降级到 journald（stderr，systemd 自动收）+ 非零退出。换钉钉/换渠道只改
# URL，不改逻辑——呼应仓里 RateLimiter protocol 那种可注入缝的姿态。
#
# 用法：
#   healthcheck.sh                 # 一次探测（systemd timer / cron 反复调）
#
# 配置（可经环境或 $AGENTCORE_HOME/.env 覆盖，部署与运维.md §8.2）：
#   AGENTCORE_HOME     部署根目录                （默认 /opt/agentcore）
#   HEALTH_URL         探测地址                  （默认 http://127.0.0.1:8000/readyz）
#   HEALTH_TIMEOUT     单次探测超时(s)           （默认 10）
#   FAIL_THRESHOLD     连续失败几次才首次告警    （默认 3，防抖）
#   REALERT_EVERY      持续失败每隔几次再报一次  （默认 30，0=只报一次直到恢复）
#   STATE_FILE         连续失败计数文件          （默认 $AGENTCORE_HOME/.healthcheck.state）
#   ALERT_WEBHOOK_URL  飞书群机器人 webhook      （未配则降级 journald）
#   ALERT_KEYWORD      告警前缀/飞书自定义关键词 （默认 AgentCore）

set -euo pipefail

# ── 配置 ──
AGENTCORE_HOME="${AGENTCORE_HOME:-/opt/agentcore}"
# 根 .env：ALERT_WEBHOOK_URL 等运维级变量（与 deploy-server.sh 同源约定）。
if [[ -f "$AGENTCORE_HOME/.env" ]]; then
  set -a; . "$AGENTCORE_HOME/.env"; set +a
fi
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/readyz}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-10}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"
REALERT_EVERY="${REALERT_EVERY:-30}"
STATE_FILE="${STATE_FILE:-$AGENTCORE_HOME/.healthcheck.state}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
ALERT_KEYWORD="${ALERT_KEYWORD:-AgentCore}"

HOST="$(hostname 2>/dev/null || echo unknown)"
NOW="$(date '+%Y-%m-%d %H:%M:%S %z')"

log()  { printf '[healthcheck] %s\n' "$*"; }
warn() { printf '[healthcheck][warn] %s\n' "$*" >&2; }
err()  { printf '[healthcheck][error] %s\n' "$*" >&2; }

# ── notifier：飞书 webhook，失败/未配则回落 journald ──
json_escape() {  # 转义 JSON 字符串内的 \ 与 "（消息保持单行，无需处理换行）
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  printf '%s' "$s"
}

send_alert() {  # $1=正文；前缀 keyword 既作标识也满足飞书「自定义关键词」安全模式
  local body="$1"
  local text="[$ALERT_KEYWORD] $body · host=$HOST · $NOW"
  if [[ -z "$ALERT_WEBHOOK_URL" ]]; then
    err "$text （未配 ALERT_WEBHOOK_URL，降级 journald）"
    return 0
  fi
  local payload="{\"msg_type\":\"text\",\"content\":{\"text\":\"$(json_escape "$text")\"}}"
  if curl -fsS -m "$HEALTH_TIMEOUT" -X POST \
      -H 'Content-Type: application/json' \
      -d "$payload" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1; then
    log "alert pushed: $body"
  else
    err "$text （飞书推送失败，降级 journald）"
  fi
}

# ── 读跨次连续失败计数 ──
prev=0
if [[ -f "$STATE_FILE" ]]; then
  prev="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"
  [[ "$prev" =~ ^[0-9]+$ ]] || prev=0
fi
write_state() {  # 写计数；状态目录不可写则仅告警（防抖退化为每次都报，可接受）
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
  if ! printf '%s' "$1" >"$STATE_FILE" 2>/dev/null; then
    warn "无法写状态文件 $STATE_FILE，防抖计数将不跨次累积"
  fi
}

# ── 单次探测：仅 HTTP 200 视为健康。curl 的 %{http_code} 在连接失败时本身就输出
#    000，故不能再 `|| echo 000`（会拼成 000000）；用 `|| true` 仅吞掉非零退出。──
code="$(curl -s -o /dev/null -w '%{http_code}' -m "$HEALTH_TIMEOUT" "$HEALTH_URL" 2>/dev/null)" || true
code="${code:-000}"

if [[ "$code" == "200" ]]; then
  if (( prev >= FAIL_THRESHOLD )); then
    send_alert "✅ 已恢复：$HEALTH_URL 200（此前连续失败 ${prev} 次）"
  fi
  write_state 0
  log "healthy: $HEALTH_URL 200"
  exit 0
fi

# ── 不健康：累加计数，按阈值/重报间隔决定是否告警，非零退出让 systemctl status 标红 ──
count=$(( prev + 1 ))
write_state "$count"
reason="HTTP ${code}"
[[ "$code" == "000" ]] && reason="不可达（连接失败/超时）"

if (( count == FAIL_THRESHOLD )); then
  send_alert "🔴 服务异常：$HEALTH_URL $reason（连续 ${count} 次，达告警阈值）"
elif (( count > FAIL_THRESHOLD && REALERT_EVERY > 0 )) && (( (count - FAIL_THRESHOLD) % REALERT_EVERY == 0 )); then
  send_alert "🔴 服务仍异常：$HEALTH_URL $reason（已连续 ${count} 次）"
else
  warn "probe failed: $HEALTH_URL $reason（连续 ${count}/${FAIL_THRESHOLD} 次，未达告警阈值）"
fi
exit 1
