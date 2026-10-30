#!/usr/bin/env bash
# Point the Pi's web-test service at serve.py (site + save counts) and restart it.
# Run on the Pi:  bash pi_use_serve.sh
set -euo pipefail

CONF=/etc/systemd/system/web-test.service.d/site.conf
DIR="$(cd "$(dirname "$0")" && pwd)"
EXEC="ExecStart=/usr/bin/python3 $DIR/serve.py --port 8080 --bind 127.0.0.1"

if [ ! -f "$CONF" ]; then
  echo "error: $CONF not found" >&2
  exit 1
fi
if [ ! -f "$DIR/site/index.html" ]; then
  echo "error: no built site; run python3 build_site.py first" >&2
  exit 1
fi

sudo sed -i "s|^ExecStart=/usr/bin/python3 .*|$EXEC|" "$CONF"
sudo systemctl daemon-reload
sudo systemctl restart web-test
sleep 1
systemctl --no-pager --lines=5 status web-test
