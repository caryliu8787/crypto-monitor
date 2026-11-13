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

# Step 2: Generate clean, mobile-friendly Telegram message from data/latest.json
export DATE SESSION PAGES_URL
MESSAGE=$(python3 << 'PYEOF'
import json, os
from html import escape

date = os.environ.get("DATE", "")
pages_url = os.environ.get("PAGES_URL", "")

d = json.load(open("data/latest.json"))
reg = d.get("regime", {})
sc = reg.get("scores", {})
br = reg.get("breadth", {})
btc = d.get("market_context", {}).get("btc", {})
eth = d.get("market_context", {}).get("eth", {})

FGI_CN = {
    "Extreme Fear": "极度恐慌",
    "Fear": "恐慌",
    "Neutral": "中性",
    "Greed": "贪婪",
    "Extreme Greed": "极度贪婪",
}

def px(v):
    if v is None: return "—"
    if abs(v) >= 1000: return f"${v:,.0f}"
    if abs(v) >= 1: return f"${v:,.2f}"
    if abs(v) >= 0.01: return f"${v:.4f}"
    return f"${v:.6f}"

def pct(v, digits=1):
    if v is None: return "—"
    return f"+{v:.{digits}f}%" if v >= 0 else f"{v:.{digits}f}%"

code = reg.get("regime_code", "")
r_icon = "🟢" if "BULL" in code else ("🔴" if "BEAR" in code else "🟡")
fgi_cn = FGI_CN.get(btc.get("fear_greed_label", ""), "")

lines = [
    f"🧭 <b>日线合约早报</b>  <code>{date}</code>",
    "",
    f"{r_icon} <b>大盘环境：{escape(reg.get('regime_label','—'))}</b>（{sc.get('total','—')}/20分 · 情绪 {btc.get('fear_greed','—')} {fgi_cn}）",
    f"👉 {escape(reg.get('posture',''))}",
    "",
    f"• <b>BTC</b> {px(btc.get('price_usd'))}（{pct(btc.get('price_change_24h'))}）{escape(btc.get('trend_label',''))}｜20日线压力 {px(btc.get('ema20'))}",
    f"• <b>ETH</b> {px(eth.get('price_usd'))}（{pct(eth.get('chg_24h'))}）｜全场仅 <b>{br.get('pct_above_ema20','—')}%</b> 站上日线均线",
]

setups = d.get("setups") or []
action_list = [s for s in setups if s.get("direction") in ("LONG", "SHORT")]
watch_list = [s for s in setups if s.get("direction") == "WATCH"]

lines.append("")
lines.append("━━━━━━━━━━━━━━━")

if not action_list:
    lines.append("🎯 <b>今日可执行单：暂无</b>（建议观望等右侧信号）")
else:
    lines.append(f"🎯 <b>今日可执行单（共 {len(action_list)} 个）</b>")
    for idx, s in enumerate(action_list[:4], 1):
        is_long = s.get("direction") == "LONG"
        tag = "🟢 做多" if is_long else "🔴 做空"
        if s.get("action_override") == "AVOID":
            tag += "[排雷规避]"
        lev = (s.get("notional_1r_pct") or 0) / 100.0
        why = (s.get("catalyst_note") or s.get("quant_summary") or "").strip()
        if len(why) > 58:
            why = why[:57] + "…"
        lines.extend([
            "",
            f"<b>{idx}. {tag} {escape(s['symbol'])}</b>（{escape(s.get('setup_label',''))} · {s.get('score',{}).get('total','—')}分）",
            f"• 现价：{px(s.get('price_usd'))}（{pct(s.get('chg_24h'))}）｜年化费率 {pct(s.get('funding_ann_pct'))}",
            f"• 进场：{px(s.get('trigger_price'))} 附近（{escape(s.get('trigger_rule','')[:28])}）",
            f"• 止损：{px(s.get('stop_price'))}（止损宽 {s.get('stop_dist_pct')}%）",
            f"• 仓位：<b>≤ {lev:.2f}x 杠杆（{s.get('notional_1r_pct')}% 本金）</b>",
            f"• 逻辑：{escape(why)}",
        ])

if watch_list:
    lines.append("")
    lines.append("👀 <b>变盘观察池（等突破再动）</b>")
    for s in watch_list[:3]:
        d20h = px(s.get("donchian_20d_high") or s.get("trigger_price"))
        d20l = px(s.get("donchian_20d_low"))
        lines.append(
            f"• <b>{escape(s['symbol'])}</b>（现价 {px(s.get('price_usd'))}）：上破 <b>{d20h}</b> 做多 / 跌破 <b>{d20l}</b> 做空"
        )

ev_lines = []
TYPE_CN = {"unlock": "解锁", "upgrade": "升级", "macro": "宏观"}
for e in d.get("events") or []:
    da = e.get("days_away")
    if da is not None and 0 <= da <= 7:
        when = "今天" if da == 0 else ("明天" if da == 1 else f"{da}天后")
        t_cn = TYPE_CN.get(e.get("event_type"), "事件")
        ev_lines.append(f"• {when} ({e.get('date','')[5:]}) <b>{escape(str(e.get('coin','')).upper())}</b> {t_cn}：{escape(e.get('description','')[:34])}")

if ev_lines:
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("⚠️ <b>近 7 天持仓排雷</b>")
    lines.extend(ev_lines[:4])

lines.append("")
lines.append(f"📈 <a href=\"{pages_url}\"><b>点击打开完整网页图表与自选池 →</b></a>")
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
