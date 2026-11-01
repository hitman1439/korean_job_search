#!/usr/bin/env bash
# One collection cycle on the Pi: collect → build site/ → build site_test/.
# Run by the korean-jobs-collect timer 4 times a day (00, 06, 12, 18) (see pi_install_collect_timer.sh);
# can also be run by hand:  bash pi_collect.sh
#
# collect_jobs.py reads secrets.env itself, so any API keys there apply here too.
#
# Each site is built into a fresh folder and swapped in at the end, so serve.py
# never serves a half-written site. If collection fails, the last good site stays.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# A collection takes 10–15 minutes; never let two runs overlap.
command -v flock >/dev/null || { echo "flock not found (sudo apt install util-linux)" >&2; exit 1; }
exec 9>"$DIR/.collect.lock"
if ! flock -n 9; then
  echo "another collection is still running; skipping this one"
  exit 0
fi

log() { echo "[$(date '+%F %T')] $*"; }

build() {  # build <out dir> [build_site.py flags...]
  local out="$1"; shift
  python3 build_site.py --out "$out.new" "$@"
  rm -rf "$out.old"
  if [ -d "$out" ]; then mv "$out" "$out.old"; fi
  mv "$out.new" "$out"
  rm -rf "$out.old"
}

log "collect start"
# Exit 2 means some sources failed (a board down, a timeout) but the rest were
# saved: build anyway. Anything else (a crash) keeps the last good site.
status=0
python3 collect_jobs.py || status=$?
if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
  log "collect failed (exit $status); site left as it was"
  exit "$status"
fi
if [ "$status" -eq 2 ]; then log "collect done, some sources failed (see source_errors); building"
else log "collect done; building"; fi
build site
build site_test --test
log "all done"
