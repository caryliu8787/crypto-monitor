#!/bin/bash
# Telegram Push Script for Crypto Monitor
# Usage: ./scripts/telegram-push.sh [report_date] [session]
#
# 1. Git push HTML report to GitHub (triggers GitHub Pages update)
# 2. Send report URL to Telegram (click to open in mobile browser)

set -uo pipefail
cd "$(dirname "$0")/.."

# Parse config — env vars take priority over config file
CONFIG="config/output.json"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram'].get('bot_token',''))")}"
CHAT_ID="${TELEGRAM_CHAT_ID:-$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram'].get('chat_id',''))")}"

if [ -z "$BOT_TOKEN" ] || [ "$BOT_TOKEN" = "" ]; then
  echo "Error: telegram.bot_token not configured"
  exit 1
fi
if [ -z "$CHAT_ID" ] || [ "$CHAT_ID" = "" ]; then
  echo "Error: telegram.chat_id not configured"
  exit 1
fi

API="https://api.telegram.org/bot${BOT_TOKEN}"
DATE="${1:-$(date +%Y-%m-%d)}"
SESSION="${2:-daily}"
HTML_FILE="reports/${DATE}_${SESSION}.html"
PAGES_URL="https://caryliu8787.github.io/crypto-monitor/reports/${DATE}_${SESSION}.html"

# Step 1: Push HTML to GitHub
if [ -f "$HTML_FILE" ]; then
  echo "Pushing report to GitHub..."
  git add "$HTML_FILE" data/latest.json 2>/dev/null
  # Only commit if there are staged changes (avoid duplicate commits)
  if ! git diff --cached --quiet 2>/dev/null; then
    git commit -m "Report: ${DATE} ${SESSION}"
  else
    echo "No new changes to commit (already committed by Claude)."
  fi
  # Only push if local is ahead of remote
  if [ "$(git rev-list --count origin/main..HEAD 2>/dev/null)" -gt 0 ]; then
    git push origin main 2>&1 | tail -1
  else
    echo "Already up to date with remote."
  fi
  echo "Waiting for GitHub Pages deploy..."
  for i in $(seq 1 12); do
    sleep 10
    STATUS=$(gh api repos/caryliu8787/crypto-monitor/pages/builds/latest 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "built" ]; then
      echo "Pages deployed."
      break
    fi
    echo "  Build status: $STATUS ($((i*10))s)..."
  done
else
  echo "Error: $HTML_FILE not found"
  exit 1
fi

# Step 2: Generate Telegram message from latest.json
export DATE SESSION PAGES_URL
MESSAGE=$(python3 << 'PYEOF'
import json, sys, os
from html import escape

date = os.environ.get("DATE", "")
session = os.environ.get("SESSION", "")
pages_url = os.environ.get("PAGES_URL", "")

try:
    d = json.load(open("data/latest.json"))
except:
    print("data/latest.json not found")
    sys.exit(1)

btc = d.get("market_context", {}).get("btc", {})
score = d.get("market_score", {})

def pct(v):
    if v is None: return "—"
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def price(v):
    if v is None: return "—"
    if v >= 1000: return f"${v:,.0f}"
    if v >= 1: return f"${v:.2f}"
    if v >= 0.01: return f"${v:.3f}"
    return f"${v:.4f}"

total = score.get("total", 0)
phase = "强牛市" if total>=16 else "偏多" if total>=12 else "中性" if total>=8 else "偏空" if total>=4 else "强熊市"

fgi = btc.get("fear_greed", "—")

# Score bars
dims = [("BTC趋势", score.get("btc_trend",0)), ("资金面", score.get("funding",0)),
        ("情绪面", score.get("sentiment",0)), ("宏观面", score.get("macro",0))]
score_lines = ""
for name, val in dims:
    val = int(val or 0)
    bar = "🟩" * val + "⬜" * max(0, 5 - val)
    score_lines += f"{name} {bar} {val}/5\n"

# Opportunities (top by score, exclude stale/expired)
DIFFUSION_ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
opps = [o for o in d.get("opportunities", [])
        if o.get("status") in ("new", "tracking", "triggered")]
opps.sort(key=lambda o: (o.get("score", {}).get("total") or 0), reverse=True)
opp_str = ""
for o in opps[:5]:
    icon = DIFFUSION_ICON.get(o.get("diffusion"), "⚪")
    s = o.get("score", {}).get("total", "—")
    flag = "🆕" if o.get("status") == "new" else ("✅" if o.get("status") == "triggered" else "")
    opp_str += f"{icon} {s}/20 <b>{escape(str(o.get('coin','')).upper())}</b> {escape(o.get('title',''))} {flag}\n"
if not opp_str:
    opp_str = "本期无新机会\n"

# Top movers
mover_str = ""
for m in d.get("market_scan", {}).get("movers", [])[:5]:
    sym = str(m.get("symbol", "")).upper()
    reason = m.get("reason") or "原因未明"
    if len(reason) > 30:
        reason = reason[:30] + "…"
    mover_str += f"<code>{sym:8}</code> {pct(m.get('price_change_24h'))}  {escape(reason)}\n"

# Events within 7 days
event_str = ""
for e in d.get("events", []):
    da = e.get("days_away")
    if e.get("status") == "upcoming" and da is not None and da <= 7:
        icon = "⏰" if da <= 2 else "📅"
        event_str += f"{icon} {e.get('date','')} {escape(str(e.get('coin','')).upper())} {escape(e.get('description',''))}\n"

# Cycle metrics
mvrv = btc.get("mvrv_ratio", "—")
funding = btc.get("funding_rate", "—")
oi = btc.get("open_interest", 0) or 0
support = btc.get("support")
resistance = btc.get("resistance")

# Alerts
alert_str = ""
for a in d.get("alerts", [])[:5]:
    text = a.get("message", str(a)) if isinstance(a, dict) else str(a)
    alert_str += f"  ⚡ {escape(text)}\n"

# Build message
msg = f"""<b>🔭 加密货币机会发现</b>
<code>{date} {session}</code>

<b>FGI {fgi}</b> {btc.get('fear_greed_label','')} | 评分 <b>{total}/20</b> {phase}
BTC {price(btc.get('price_usd'))} {pct(btc.get('price_change_24h'))} | 主导率 {btc.get('dominance','—')}%

{score_lines}
<b>━ 机会 ━</b>
{opp_str}"""

if mover_str:
    msg += f"\n<b>━ 异动 ━</b>\n{mover_str}"

if event_str:
    msg += f"\n<b>━ 事件（7天内）━</b>\n{event_str}"

msg += f"""
<b>━ 周期 ━</b>
MVRV {mvrv} | 费率 {funding}% | OI ${oi/1e9:.1f}B"""

if support and resistance:
    msg += f"\n支撑 ${support:,} | 阻力 ${resistance:,}"

if alert_str:
    msg += f"\n\n<b>━ 告警 ━</b>\n{alert_str}"

msg += f"""

<b>👉 <a href="{pages_url}">打开完整报告</a></b>"""

print(msg)
PYEOF
)

# Step 3: Send to Telegram
echo "Sending to Telegram..."
RESPONSE=$(curl -s -X POST "${API}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=false" \
  --data-urlencode "text=${MESSAGE}")

HTTP_CODE=$(echo "$RESPONSE" | python3 -c "import json,sys; r=json.load(sys.stdin); print('OK' if r.get('ok') else r.get('description','error'))")
echo "Telegram: $HTTP_CODE"

echo "Done. Report URL: ${PAGES_URL}"
