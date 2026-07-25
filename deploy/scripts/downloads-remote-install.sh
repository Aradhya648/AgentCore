#!/usr/bin/env bash
# One-time / idempotent: downloads static root + nginx site on :8092.
# Invoked via: ssh … 'bash -s' < deploy/scripts/downloads-remote-install.sh
# Override: DOWNLOADS_HOST（默认 downloads.example.com）
set -euo pipefail

DOWNLOADS_HOST="${DOWNLOADS_HOST:-downloads.example.com}"
DOWNLOADS_ROOT="/opt/agentcore/downloads"
NGINX_AVAIL="/etc/nginx/sites-available/downloads"
NGINX_ENABLED="/etc/nginx/sites-enabled/downloads"

sudo mkdir -p "$DOWNLOADS_ROOT/desktop" "$DOWNLOADS_ROOT/android"
sudo chown -R "$(id -u):$(id -g)" "$DOWNLOADS_ROOT" 2>/dev/null || true

if [[ -f /tmp/downloads.conf ]]; then
  sudo install -D -m 644 /tmp/downloads.conf "$NGINX_AVAIL"
  rm -f /tmp/downloads.conf
elif [[ -f /tmp/deploy/nginx/downloads.conf ]]; then
  sudo install -D -m 644 /tmp/deploy/nginx/downloads.conf "$NGINX_AVAIL"
  rm -f /tmp/deploy/nginx/downloads.conf
else
  echo "ERROR: downloads.conf not uploaded to /tmp"
  exit 1
fi

# Bake real hostname into the installed site (snippet ships with placeholder).
sudo sed -i "s/server_name downloads\\.example\\.com;/server_name ${DOWNLOADS_HOST};/" "$NGINX_AVAIL"

ln -sfn "$NGINX_AVAIL" "$NGINX_ENABLED"
sudo nginx -t
sudo systemctl reload nginx

LOCAL_CODE="$(curl -sS -o /dev/null -w '%{http_code}' -H "Host: ${DOWNLOADS_HOST}" http://127.0.0.1:8092/ || true)"
echo "nginx reloaded; local probe :8092 / → HTTP ${LOCAL_CODE} (404 without index is OK)"
echo "downloads root → $DOWNLOADS_ROOT"
echo ""
echo "NEXT (Cloudflare Tunnel ingress is remotely managed on this host):"
echo "  Zero Trust → Networks → Tunnels → Public Hostname"
echo "  Hostname: ${DOWNLOADS_HOST}"
echo "  Service:  http://127.0.0.1:8092"
echo "  (DNS CNAME for downloads.* is usually created with the hostname)"
