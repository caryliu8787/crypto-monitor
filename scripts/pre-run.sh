#!/bin/bash
# Pre-run housekeeping for crypto-monitor.
# Called by the Kimi Work scheduled task BEFORE report generation.
# Handles: log rotation (7d), snapshot archiving to data/history (30d),
# and .bak backup of data/latest.json (restored by the agent if the run fails).
#
# Usage: ./scripts/pre-run.sh

set -uo pipefail
cd "$(dirname "$0")/.."

# --- Log rotation: clean up logs older than 7 days ---
find logs -name "*.log" -mtime +7 -delete 2>/dev/null
find logs -name "*.err" -mtime +7 -delete 2>/dev/null

# --- Archive previous snapshot before this run overwrites it ---
mkdir -p data/history
if [ -s data/latest.json ]; then
  python3 -c "
import json, shutil, sys
try:
    d = json.load(open('data/latest.json'))
    ts, sess = d.get('timestamp', 'unknown')[:10], d.get('session', 'unknown')
    shutil.copy('data/latest.json', f'data/history/{ts}_{sess}.json')
except Exception as e:
    print(f'history archive skipped: {e}', file=sys.stderr)
"
  # --- .bak backup: agent restores this if report generation fails midway ---
  cp data/latest.json data/latest.json.bak
fi
find data/history -name "*.json" -mtime +30 -delete 2>/dev/null

echo "pre-run done: logs rotated, snapshot archived, .bak written"
