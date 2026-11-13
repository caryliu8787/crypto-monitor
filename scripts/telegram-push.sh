#!/bin/bash
# Telegram Push & GitHub Pages Deploy Script for Crypto Perp Trend Radar 2.0
# Usage: ./scripts/telegram-push.sh [report_date] [session]

set -uo pipefail
cd "$(dirname "$0")/.."

CONFIG="config/output.json"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram'].get('bot_token',''))")}"
CHAT_ID="${TELEGRAM_CHAT_ID:-$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram'].get('chat_id',''))")}"

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "Error: telegram.bot_token or chat_id not configured"
  exit 1
fi

API="https://api.telegram.org/bot${BOT_TOKEN}"
DATE="${1:-$(date +%Y-%m-%d)}"
SESSION="${2:-daily}"
HTML_FILE="reports/${DATE}_${SESSION}.html"
MD_FILE="reports/${DATE}_${SESSION}.md"
PAGES_URL="https://caryliu8787.github.io/crypto-monitor/reports/${DATE}_${SESSION}.html"

# Step 1: Push HTML & latest.json to GitHub
if [ -f "$HTML_FILE" ]; then
  echo "Pushing report to GitHub..."
  git add "$HTML_FILE" data/latest.json 2>/dev/null
  if ! git diff --cached --quiet 2>/dev/null; then
    git commit -m "Report: ${DATE} ${SESSION}"
  else
    echo "No new changes to commit."
  fi
  if [ "$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)" -gt 0 ]; then
    git push origin main 2>&1 | tail -2
  else
    echo "Already up to date with remote."
  fi
else
  echo "Error: $HTML_FILE not found"
  exit 1
fi

# Step 2: Generate Telegram message from data/latest.json
export DATE SESSION PAGES_URL
MESSAGE=$(python3 << 'PYEOF'
import json, os, sys
from html import escape

date = os.environ.get("DATE", "")
session = os.environ.get("SESSION", "")
pages_url = os.environ.get("PAGES_URL", "")

d = json.load(open("data/latest.json"))
reg = d.get("regime", {})
sc = reg.get("scores", {})
br = reg.get("breadth", {})
deriv = reg.get("derivatives_overview", {})
btc = d.get("market_context", {}).get("btc", {})
eth = d.get("market_context", {}).get("eth", {})

def px(v):
    if v is None: return "—"
    if abs(v) >= 1000: return f"${v:,.0f}"
    if abs(v) >= 1: return f"${v:,.2f}"
    if abs(v) >= 0.01: return f"${v:.4f}"
    return f"${v:.6f}"

def pct(v, d=1):
    if v is None: return "—"
    return f"+{v:.{d}f}%" if v >= 0 else f"{v:.{d}f}%"

lines = [
    f"<b>🧭 日线合约趋势早报</b>  <code>{date}</code>",
    f"<b>{escape(reg.get('regime_label','—'))} ({sc.get('total','—')}/20)</b> | FGI <b>{btc.get('fear_greed','—')}</b>",
    f"<i>{escape(reg.get('posture',''))}</i>",
    "",
    f"<b>BTC</b> {px(btc.get('price_usd'))} ({pct(btc.get('price_change_24h'))}) · {escape(btc.get('trend_label',''))}",
    f"  EMA20 {px(btc.get('ema20'))} | EMA50 {px(btc.get('ema50'))} | ATR {pct(btc.get('atr_pct'),1).lstrip('+')}",
    f"<b>ETH</b> {px(eth.get('price_usd'))} ({pct(eth.get('chg_24h'))}) · 广度(站上EMA20) <b>{br.get('pct_above_ema20','—')}%</b> | 中位费率 {pct(deriv.get('median_funding_ann_pct'),1)}",
    "",
    "<b>━━ 今日交易剧本 (1%风险仓位标尺) ━━</b>",
]

setups = d.get("setups") or []
if not setups:
    lines.append("今日无高赔率标准剧本，建议观望或持既有底仓。")
else:
    for s in setups[:5]:
        icon = "🟢" if s.get("direction") == "LONG" else ("🔴" if s.get("direction") == "SHORT" else "🟡")
        avoid = " [规避]" if s.get("action_override") == "AVOID" else ""
        lines.append(
            f"{icon} <b>{escape(s['symbol'])}</b> {s['direction']}{avoid} · {escape(s.get('setup_label',''))} ({s.get('score',{}).get('total','—')}/20)\n"
            f"   现价 {px(s.get('price_usd'))} | 触发 {px(s.get('trigger_price'))} | 止损 {px(s.get('stop_price'))} (-{s.get('stop_dist_pct')}%)\n"
            f"   费率(年化) {pct(s.get('funding_ann_pct'),1)} | 1%风险仓位 <b>{s.get('notional_1r_pct')}%</b>"
        )

# 7 天内排雷事件
ev_lines = []
for e in d.get("events") or []:
    da = e.get("days_away")
    if da is not None and 0 <= da <= 7:
        ic = "⏰" if da <= 2 else "📅"
        ev_lines.append(f"{ic} {e.get('date','')[5:]} <b>{escape(str(e.get('coin','')).upper())}</b> ({e.get('event_type')}) {escape(e.get('description','')[:42])}")

if ev_lines:
    lines.append("")
    lines.append("<b>━━ 7天持仓排雷 ━━</b>")
    lines.extend(ev_lines[:5])

lines.append("")
lines.append(f"<b>👉 <a href=\"{pages_url}\">打开完整日线图表与自选矩阵</a></b>")
print("\n".join(lines))
PYEOF
)

# Step 3: Send to Telegram
echo "Sending to Telegram..."
RESPONSE=$(curl -s -X POST "${API}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" \
  --data-urlencode "text=${MESSAGE}")

STATUS=$(echo "$RESPONSE" | python3 -c "import json,sys; r=json.load(sys.stdin); print('OK' if r.get('ok') else r.get('description','error'))" 2>/dev/null || echo "parse_error")
echo "Telegram: $STATUS"
echo "Done. Report URL: ${PAGES_URL}"
