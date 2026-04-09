#!/bin/bash
# Telegram Push Script for Crypto Monitor
# Usage: ./scripts/telegram-push.sh [report_date] [session]
#
# 1. Git push HTML report to GitHub (triggers GitHub Pages update)
# 2. Send report URL to Telegram (click to open in mobile browser)

set -euo pipefail
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
SESSION="${2:-morning}"
HTML_FILE="reports/${DATE}_${SESSION}.html"
PAGES_URL="https://caryliu8787.github.io/crypto-monitor/reports/${DATE}_${SESSION}.html"

# Step 1: Push HTML to GitHub
if [ -f "$HTML_FILE" ]; then
  echo "Pushing report to GitHub..."
  git add "$HTML_FILE" data/latest.json 2>/dev/null
  git commit -m "Report: ${DATE} ${SESSION}" --allow-empty 2>/dev/null || true
  git push origin main 2>&1 | tail -1
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

date = os.environ.get("DATE", "")
session = os.environ.get("SESSION", "")
pages_url = os.environ.get("PAGES_URL", "")

try:
    d = json.load(open("data/latest.json"))
except:
    print("data/latest.json not found")
    sys.exit(1)

c = d.get("coins", {})
btc = c.get("btc", {})
score = d.get("market_score", {})

def pct(v):
    if v is None: return "—"
    return f"+{v}%" if v >= 0 else f"{v}%"

def price(v):
    if v is None: return "—"
    if v >= 1000: return f"${v:,.0f}"
    if v >= 1: return f"${v:.2f}"
    if v >= 0.01: return f"${v:.3f}"
    return f"${v:.4f}"

total = score.get("total", 0)
phase = "强牛市" if total>=16 else "偏多" if total>=12 else "中性偏空" if total>=8 else "偏空" if total>=4 else "强熊市"

fgi = btc.get("fear_greed", "—")

# Score bars
dims = [("BTC趋势", score.get("btc_trend",0)), ("资金面", score.get("funding",0)),
        ("情绪面", score.get("sentiment",0)), ("宏观面", score.get("macro",0))]
score_lines = ""
for name, val in dims:
    bar = "🟩" * val + "⬜" * (5 - val)
    score_lines += f"{name} {bar} {val}/5\n"

# Prices
coins_data = [
    ("BTC", c.get("btc",{})), ("ETH", c.get("eth",{})), ("SOL", c.get("sol",{})),
    ("LINK", c.get("link",{})), ("ARB", c.get("arb",{})),
    ("MON", c.get("monad",{})), ("PLUME", c.get("plume",{}))
]
price_lines = ""
for name, coin in coins_data:
    p = coin.get("price")
    ch = coin.get("change_24h")
    if p is not None:
        price_lines += f"<code>{name:6}</code> {price(p):>10}  {pct(ch)}\n"

# Key metrics
mvrv = btc.get("mvrv_zscore", "—")
sopr = btc.get("sopr_sth", "—")
reserves = btc.get("exchange_reserves")
reserves_str = f"{reserves/1e6:.2f}M" if reserves else "—"
funding = btc.get("funding_rate", "—")
support = btc.get("key_support")
resistance = btc.get("key_resistance")

# Alerts
alerts = d.get("alerts_triggered", [])
alert_str = ""
if alerts:
    for a in alerts:
        alert_str += f"  ⚡ {a}\n"

# Build message
msg = f"""<b>📊 加密货币每日情报</b>
<code>{date} {session}</code>

<b>FGI {fgi}</b> {btc.get('fear_greed_label','')} | 评分 <b>{total}/20</b> {phase}
BTC主导率 {btc.get('dominance','—')}% | 山寨季 {btc.get('altseason_index','—')}/100

{score_lines}
<b>━ 价格 ━</b>
{price_lines}
<b>━ BTC 链上 ━</b>
MVRV {mvrv} | SOPR {sopr} | 储备 {reserves_str}
费率 {funding}% | OI ${btc.get('open_interest',0)/1e9:.1f}B"""

if support and resistance:
    msg += f"\n支撑 ${support:,} | 阻力 ${resistance:,}"

if alert_str:
    msg += f"\n\n<b>━ 告警 ━</b>\n{alert_str}"

# ARB unlock
arb = c.get("arb", {})
if arb.get("next_unlock_date"):
    msg += f"\n⚠️ ARB 解锁 {arb['next_unlock_date']}: {arb.get('next_unlock_amount','—')}"

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
