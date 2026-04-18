#!/bin/bash
# Wrapper script for crypto-monitor report generation.
# Called by launchd plist. Handles: log rotation, claude invocation,
# output verification, failure alerting.
#
# Usage: ./scripts/run-report.sh <session>
#   session: "morning" or "evening"

set -uo pipefail
cd "$(dirname "$0")/.."

SESSION="${1:-morning}"
DATE=$(TZ=Asia/Shanghai date +%Y-%m-%d)
LOG_DIR="logs"
LOG_FILE="${LOG_DIR}/${DATE}_${SESSION}.log"
ERR_FILE="${LOG_DIR}/${DATE}_${SESSION}.err"
EXPECTED_HTML="reports/${DATE}_${SESSION}.html"
EXPECTED_MD="reports/${DATE}_${SESSION}.md"

# --- Log rotation: clean up logs older than 7 days ---
find "$LOG_DIR" -name "*.log" -mtime +7 -delete 2>/dev/null
find "$LOG_DIR" -name "*.err" -mtime +7 -delete 2>/dev/null

# --- Kill stale claude process from prior run ---
pkill -f "claude -p.*加密货币情报监控" 2>/dev/null
sleep 1

# --- Wait for network (up to 30s) ---
for i in $(seq 1 15); do
  ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && break
  sleep 2
done

# --- Run claude with hard timeout (防止网络/睡眠导致挂死) ---
TIMEOUT_SECS=1500  # 25 分钟。正常运行 8-12 分钟，超时即视为挂死
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${SESSION} report (timeout: ${TIMEOUT_SECS}s)" >> "$LOG_FILE"

caffeinate -is /Users/caryliu/.local/bin/claude -p \
  "执行加密货币情报监控。读取 CLAUDE.md，Phase 0-6 完整执行，生成 ${SESSION} 报告。" \
  --allowedTools "WebSearch,WebFetch,Read,Write,Edit,Bash,Glob,Grep" \
  >> "$LOG_FILE" 2>> "$ERR_FILE" &
CLAUDE_PID=$!

(
  sleep "$TIMEOUT_SECS"
  if kill -0 "$CLAUDE_PID" 2>/dev/null; then
    kill -TERM "$CLAUDE_PID" 2>/dev/null
    sleep 5
    kill -KILL "$CLAUDE_PID" 2>/dev/null
    pkill -KILL -f "claude -p.*加密货币情报监控" 2>/dev/null
  fi
) &
WATCHER_PID=$!

wait "$CLAUDE_PID"
CLAUDE_EXIT=$?

kill "$WATCHER_PID" 2>/dev/null
wait "$WATCHER_PID" 2>/dev/null

TIMED_OUT=false
if [ "$CLAUDE_EXIT" -eq 143 ] || [ "$CLAUDE_EXIT" -eq 137 ]; then
  TIMED_OUT=true
fi

# --- Verify output ---
FAILED=false
FAIL_REASON=""

if [ "$TIMED_OUT" = true ]; then
  FAILED=true
  FAIL_REASON="claude 挂死被 kill (超时 ${TIMEOUT_SECS}s, 通常是网络异常或系统睡眠合盖导致)"
elif [ $CLAUDE_EXIT -ne 0 ]; then
  FAILED=true
  FAIL_REASON="claude exited with code ${CLAUDE_EXIT}"
elif [ ! -f "$EXPECTED_HTML" ] || [ ! -f "$EXPECTED_MD" ]; then
  FAILED=true
  FAIL_REASON="report files not found (html: $([ -f "$EXPECTED_HTML" ] && echo ok || echo missing), md: $([ -f "$EXPECTED_MD" ] && echo ok || echo missing))"
elif [ ! -s "$EXPECTED_HTML" ]; then
  FAILED=true
  FAIL_REASON="HTML report is empty"
fi

# --- On success: run telegram push ---
if [ "$FAILED" = false ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Report generated successfully, running telegram push" >> "$LOG_FILE"
  bash scripts/telegram-push.sh "$DATE" "$SESSION" >> "$LOG_FILE" 2>> "$ERR_FILE"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done" >> "$LOG_FILE"
  exit 0
fi

# --- On failure: send alert via Telegram ---
echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAILED: ${FAIL_REASON}" >> "$LOG_FILE"

# Read Telegram config from env vars or config file
CONFIG="config/output.json"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram'].get('bot_token',''))" 2>/dev/null)}"
CHAT_ID="${TELEGRAM_CHAT_ID:-$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram'].get('chat_id',''))" 2>/dev/null)}"

if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
  ALERT_MSG="⚠️ <b>crypto-monitor 报告生成失败</b>
<code>${DATE} ${SESSION}</code>

原因: ${FAIL_REASON}

日志: ${LOG_FILE}
错误: ${ERR_FILE}"

  curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    -d "parse_mode=HTML" \
    --data-urlencode "text=${ALERT_MSG}" >/dev/null 2>&1

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Failure alert sent to Telegram" >> "$LOG_FILE"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cannot send alert: Telegram not configured" >> "$LOG_FILE"
fi

exit 1
