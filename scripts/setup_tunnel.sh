#!/usr/bin/env bash
# Set up Cloudflare Tunnel for remote access.
# Requires: brew install cloudflared, and a Cloudflare account with a domain.

set -euo pipefail

TUNNEL_NAME="nicks-watch-service"
HOSTNAME="${CF_HOSTNAME:-watches.yourdomain.com}"
LOCAL_PORT="${APP_PORT:-8000}"

echo "==> Authenticating with Cloudflare…"
cloudflared tunnel login

echo "==> Creating tunnel: $TUNNEL_NAME"
cloudflared tunnel create "$TUNNEL_NAME"

TUNNEL_ID=$(cloudflared tunnel list --output json | python3 -c "
import sys, json
tunnels = json.load(sys.stdin)
for t in tunnels:
    if t['name'] == '$TUNNEL_NAME':
        print(t['id'])
        break
")

CONFIG_DIR="$HOME/.cloudflared"
CONFIG_FILE="$CONFIG_DIR/config.yml"

echo "==> Writing config to $CONFIG_FILE"
cat > "$CONFIG_FILE" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json
ingress:
  - hostname: $HOSTNAME
    service: http://localhost:$LOCAL_PORT
  - service: http_status:404
EOF

echo ""
echo "Done! Config written to $CONFIG_FILE"
echo ""
echo "To run the tunnel:"
echo "  cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo "To run persistently (macOS launchd):"
echo "  cloudflared service install"
