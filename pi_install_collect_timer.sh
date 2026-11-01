#!/usr/bin/env bash
# Install (or update) the collection (4 times a day) on the Pi as a systemd timer.
# Run on the Pi from the project folder:  bash pi_install_collect_timer.sh
#
#   systemctl list-timers korean-jobs-collect.timer   # next run
#   journalctl -u korean-jobs-collect -n 50           # last run's log
#   sudo systemctl start korean-jobs-collect          # run once now
#   sudo systemctl disable --now korean-jobs-collect.timer   # stop collecting
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(id -un)"
UNIT=/etc/systemd/system/korean-jobs-collect

if [ ! -f "$DIR/secrets.env" ]; then
  echo "warning: $DIR/secrets.env not found; collection runs without API keys" >&2
fi

sudo tee "$UNIT.service" >/dev/null <<EOF
[Unit]
Description=Korean teacher jobs: collect, then build site/ and site_test/
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/usr/bin/env bash $DIR/pi_collect.sh
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=50min
EOF

sudo tee "$UNIT.timer" >/dev/null <<EOF
[Unit]
Description=Collect Korean teacher jobs 4 times a day (00, 06, 12, 18)

[Timer]
OnCalendar=*-*-* 00,06,12,18:00
RandomizedDelaySec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now korean-jobs-collect.timer
systemctl --no-pager list-timers korean-jobs-collect.timer
