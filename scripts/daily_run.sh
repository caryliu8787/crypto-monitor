#!/usr/bin/env bash
# Daily 08:05 (+ 08:35 / 09:05 zero-token retry) Crypto Perp Trend Radar
# Architecture: macOS launchd -> Python zero-token live gate -> collect.py -> agy CLI (Step 2) -> publish.py (+ pure-quant fallback)
set -euo pipefail

export HOME="${HOME:-/Users/cary}"
export LANG="en_US.UTF-8"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.gemini/antigravity/bin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PYTHON="/usr/bin/python3"
AGY_BIN="${AGY_BIN:-/Applications/Gemini.app/Contents/Helpers/agy}"

# 0. Non-blocking single-instance flock across the entire run (prevents overlap on wake/retry)
if [ "${DAILY_RUN_LOCKED:-0}" != "1" ]; then
    export DAILY_RUN_LOCKED=1
    exec "$PYTHON" -c '
import fcntl, os, pathlib, sys
pathlib.Path("data").mkdir(exist_ok=True)
f = open("data/.daily_run.lock", "w")
try:
    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("[daily_run] another daily_run.sh holds the lock, skipping.", flush=True)
    sys.exit(0)
os.set_inheritable(f.fileno(), True)
os.execvp(sys.argv[1], sys.argv[1:])
' /bin/bash "$0" "$@"
fi

# 1. Zero-token live gate: silent exit if today's report is already on GitHub Pages + Telegram
if "$PYTHON" "$PROJECT_DIR/scripts/publish.py" --check-live; then
    echo "[daily_run] $(date '+%Y-%m-%d %H:%M:%S') report already live, silent exit (0 tokens)"
    exit 0
fi

echo "[daily_run] Starting at $(date '+%Y-%m-%dT%H:%M:%S%z')"

# Wait up to 20s for DNS/network readiness (in case Mac just woke from lid-closed sleep)
"$PYTHON" -c '
import socket, time
for _ in range(10):
    try:
        socket.getaddrinfo("www.okx.com", 443)
        break
    except Exception:
        time.sleep(2)
'

# 2. Step 1: Quantitative collection (reuse if valid today and < 2h old; zero-token exit on upstream failure)
NEED_COLLECT="$("$PYTHON" -c '
import json, pathlib, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, "scripts")
from publish import validate_collected
today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
p = pathlib.Path("data/collected.json")
try:
    d = json.loads(p.read_text()) if p.is_file() else None
except Exception:
    d = None
age = time.time() - ((d or {}).get("collected_ts") or 0)
print("0" if (isinstance(d, dict) and d.get("date") == today and validate_collected(d) is None and 0 <= age < 7200) else "1")
')"

if [ "$NEED_COLLECT" = "1" ]; then
    set +e
    "$PYTHON" "$PROJECT_DIR/scripts/collect.py"
    col_rc=$?
    set -e
    if [ "$col_rc" -ne 0 ]; then
        echo "[daily_run] FATAL: collect.py failed with code ${col_rc} (0 tokens spent); aborting." >&2
        if [ "$(date '+%H')" -ge 9 ]; then
            "$PYTHON" "$PROJECT_DIR/scripts/publish.py" --notify-error "⚠️ 加密货币日线早报采集熔断（collect.py 退出码 ${col_rc}），请检查 logs/daily.err" || true
        fi
        exit "$col_rc"
    fi
else
    echo "[daily_run] Reusing valid today's data/collected.json (<2h old)"
fi

# 3. Step 2: AI Catalyst & Unlock Verification via agy CLI (skip if today's overlay.json already exists)
HAS_FRESH_OVERLAY="$("$PYTHON" -c '
import json, pathlib
from datetime import datetime, timezone, timedelta
today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
p = pathlib.Path("data/overlay.json")
try:
    d = json.loads(p.read_text()) if p.is_file() else {}
except Exception:
    d = {}
print("1" if (isinstance(d, dict) and d.get("date") == today) else "0")
')"

if [ "$HAS_FRESH_OVERLAY" = "0" ] && [ -x "$AGY_BIN" ]; then
    PROMPT='请严格按 /Users/cary/projects/crypto-monitor/AGENTS.md 完成今日早报的 Step 2（定向催化验证与排雷）与 Step 3（一键组装发布），严禁编造任何数值或未核查结论：

1. Step 1 量化采集刚刚已完成，请直接读取 `/Users/cary/projects/crypto-monitor/AGENTS.md` 与 `/Users/cary/projects/crypto-monitor/data/collected.json`（无需重复运行 collect.py）。
2. 结合当日 `regime`、`setups_candidates`、`watchlist_rows` 与 `previous.events`：按顺势原则挑选候选合约，对候选标的及未来 14-30 天代币解锁/宏观节点做受控 `search_web`（总搜索 ≤ 8 次），将纯定性结论写入 `/Users/cary/projects/crypto-monitor/data/overlay.json`（`date` 必须严格等于 `collected.json` 的 `date`；`events` 增量补充或用 `"status": "cancelled"` 删除；若候选标的近 7 日内有大额悬崖解锁风险则标 `"action_override": "AVOID"`；严禁手改任何量化数值）。
3. 运行 `/usr/bin/python3 /Users/cary/projects/crypto-monitor/scripts/publish.py` 一键生成早报、同步更新根目录 `index.html` 并推送至 GitHub Pages 与 Telegram。'

    echo "[daily_run] Invoking agy CLI for Step 2 + Step 3..."
    set +e
    "$AGY_BIN" --dangerously-skip-permissions --print-timeout 600s -p "$PROMPT"
    agy_rc=$?
    set -e
    echo "[daily_run] agy finished with exit code ${agy_rc}"
else
    echo "[daily_run] Today's overlay.json already present (or agy missing); proceeding to publish.py"
fi

# 4. Step 3 / Safety-Net Fallback: ensure today's report is live on GitHub Pages + Telegram
if ! "$PYTHON" "$PROJECT_DIR/scripts/publish.py" --check-live; then
    echo "[daily_run] Report not yet live after Step 2; running publish.py fallback from today's collected.json..."
    set +e
    "$PYTHON" "$PROJECT_DIR/scripts/publish.py"
    pub_rc=$?
    set -e
    if [ "$pub_rc" -ne 0 ]; then
        if [ "$(date '+%H')" -ge 9 ]; then
            "$PYTHON" "$PROJECT_DIR/scripts/publish.py" --notify-error "⚠️ 加密货币日线早报发布异常（publish.py 退出码 ${pub_rc}），请检查 logs/daily.err" || true
        fi
        exit "$pub_rc"
    fi
fi

echo "[daily_run] Completed at $(date '+%Y-%m-%dT%H:%M:%S%z')"
