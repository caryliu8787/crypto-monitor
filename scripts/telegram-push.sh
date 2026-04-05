#!/bin/bash
# Telegram Push Script for Crypto Monitor
# Usage: ./scripts/telegram-push.sh [report_date] [session]
# Example: ./scripts/telegram-push.sh 2026-04-04 morning
#
# Reads data from data/latest.json and config from config/output.json
# Sends a rich formatted Telegram message that's fully readable in-app

set -euo pipefail
cd "$(dirname "$0")/.."

# Parse config
CONFIG="config/output.json"
BOT_TOKEN=$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram']['bot_token'])")
CHAT_ID=$(python3 -c "import json; print(json.load(open('$CONFIG'))['formats']['telegram']['chat_id'])")

if [ -z "$BOT_TOKEN" ] || [ "$BOT_TOKEN" = "" ]; then
  echo "Error: telegram.bot_token not configured in $CONFIG"
  exit 1
fi
if [ -z "$CHAT_ID" ] || [ "$CHAT_ID" = "" ]; then
  echo "Error: telegram.chat_id not configured in $CONFIG"
  exit 1
fi

API="https://api.telegram.org/bot${BOT_TOKEN}"
DATE="${1:-$(date +%Y-%m-%d)}"
SESSION="${2:-morning}"
DATA="data/latest.json"

# Generate rich message from latest.json
MESSAGE=$(python3 << 'PYEOF'
import json, sys

try:
    d = json.load(open("data/latest.json"))
except:
    print("⚠️ data/latest.json not found")
    sys.exit(0)

c = d.get("coins", {})
btc = c.get("btc", {})
eth = c.get("eth", {})
sol = c.get("sol", {})
link = c.get("link", {})
arb = c.get("arb", {})
mon = c.get("monad", {})
plume = c.get("plume", {})
score = d.get("market_score", {})
alerts = d.get("alerts_triggered", [])

def fmt_pct(v):
    if v is None: return "—"
    return f"+{v}%" if v >= 0 else f"{v}%"

def fmt_price(v):
    if v is None: return "—"
    if v >= 1000: return f"${v:,.0f}"
    if v >= 1: return f"${v:.2f}"
    return f"${v:.4f}"

# Header
msg = f"<b>📊 加密货币每日情报简报</b>\n"
msg += f"<code>{d.get('timestamp','')[:10]} {d.get('session','')}</code>\n\n"

# Alerts
if alerts:
    msg += "⚠️ <b>告警:</b>\n"
    for a in alerts:
        msg += f"  • {a}\n"
    msg += "\n"

# Market Status
fgi = btc.get("fear_greed", "—")
fgi_label = btc.get("fear_greed_label", "")
dom = btc.get("dominance", "—")
total = score.get("total", "—")
phase = ""
if isinstance(total, (int, float)):
    if total >= 16: phase = "强牛市"
    elif total >= 12: phase = "偏多"
    elif total >= 8: phase = "中性偏空"
    elif total >= 4: phase = "偏空"
    else: phase = "强熊市"

msg += f"<b>━━ 市场状态 ━━</b>\n"
msg += f"恐惧贪婪: <b>{fgi}</b> {fgi_label}\n"
msg += f"综合评分: <b>{total}/20</b> {phase}\n"
msg += f"BTC主导率: {dom}% | 山寨季: {btc.get('altseason_index','—')}\n\n"

# 4-dim scores
msg += f"<b>━━ 四维评分 ━━</b>\n"
dims = [("BTC趋势", score.get("btc_trend")), ("资金面", score.get("funding")),
        ("情绪面", score.get("sentiment")), ("宏观面", score.get("macro"))]
for name, val in dims:
    bar = "🟩" * (val or 0) + "⬜" * (5 - (val or 0))
    msg += f"{name}: {bar} {val}/5\n"
msg += "\n"

# Price Overview
msg += f"<b>━━ 价格概览 ━━</b>\n"
coins_list = [
    ("BTC", btc.get("price"), btc.get("change_24h"), btc.get("change_7d")),
    ("ETH", eth.get("price"), eth.get("change_24h"), None),
    ("SOL", sol.get("price"), sol.get("change_24h"), None),
    ("LINK", link.get("price"), link.get("change_24h"), None),
    ("ARB", arb.get("price"), arb.get("change_24h"), None),
    ("MON", mon.get("price"), mon.get("change_24h"), None),
    ("PLUME", plume.get("price"), plume.get("change_24h"), None),
]
for name, price, ch24, ch7 in coins_list:
    line = f"{name} {fmt_price(price)} ({fmt_pct(ch24)})"
    if ch7 is not None:
        line += f" 7d:{fmt_pct(ch7)}"
    msg += line + "\n"
msg += "\n"

# On-chain
msg += f"<b>━━ BTC 链上 ━━</b>\n"
msg += f"MVRV: {btc.get('mvrv_zscore','—')} | SOPR: {btc.get('sopr_sth','—')}(STH) {btc.get('sopr_aggregate','—')}(agg)\n"
reserves = btc.get('exchange_reserves')
reserves_trend = btc.get('exchange_reserves_trend', '')
if reserves:
    msg += f"交易所储备: {reserves/1e6:.2f}M BTC ({reserves_trend})\n"
msg += f"资金费率: {btc.get('funding_rate','—')}% | OI: ${btc.get('open_interest',0)/1e9:.1f}B\n"
msg += f"期权MaxPain: ${btc.get('options_max_pain','—'):,} | P/C: {btc.get('put_call_ratio','—')}\n"
ath_ch = btc.get('ath_change')
if ath_ch: msg += f"距ATH: {ath_ch}% (ATH ${btc.get('ath',0):,})\n"
msg += "\n"

# ETF
etf = btc.get('etf_daily_flow')
if etf:
    msg += f"<b>━━ ETF ━━</b>\n"
    msg += f"最近净流入: ${etf/1e6:.1f}M | 累计: ${btc.get('etf_cumulative',0)/1e9:.1f}B\n\n"

# Ecosystem
msg += f"<b>━━ 生态 TVL ━━</b>\n"
tvl_list = [("ETH", eth.get("tvl")), ("SOL", sol.get("tvl")), ("ARB", arb.get("tvl")),
            ("MON", mon.get("tvl")), ("PLUME", plume.get("tvl"))]
for name, tvl in tvl_list:
    if tvl:
        if tvl >= 1e9: msg += f"{name}: ${tvl/1e9:.1f}B\n"
        else: msg += f"{name}: ${tvl/1e6:.0f}M\n"
msg += "\n"

# LINK specifics
if link.get("revenue_30d"):
    msg += f"<b>━━ LINK 深度 ━━</b>\n"
    msg += f"质押: {link.get('staking_tvl_link',0)/1e6:.0f}M LINK (${link.get('staking_tvl_usd',0)/1e6:.0f}M)\n"
    msg += f"CCIP年化: ${link.get('ccip_annual_volume',0)/1e9:.1f}B\n"
    msg += f"30d收入: ${link.get('revenue_30d',0)/1e6:.1f}M\n\n"

# ARB unlock
if arb.get("next_unlock_date"):
    msg += f"<b>━━ ARB ⚠️ ━━</b>\n"
    msg += f"解锁: {arb['next_unlock_date']} ({arb.get('next_unlock_amount','—')})\n"
    msg += f"TVL: ${arb.get('tvl',0)/1e9:.2f}B | 30d费用: ${arb.get('fees_30d',0)/1e3:.0f}K\n\n"

# PLUME
if plume.get("rwa_assets"):
    msg += f"<b>━━ PLUME (RWA) ━━</b>\n"
    msg += f"RWA资产: ${plume.get('rwa_assets',0)/1e6:.0f}M | 持有者: {plume.get('rwa_holders',0)/1e3:.0f}K\n"
    msg += f"TVL: ${plume.get('tvl',0)/1e6:.1f}M | 稳定币: ${plume.get('stablecoin_supply',0)/1e6:.0f}M\n\n"

# Key support/resistance
support = btc.get("key_support")
resistance = btc.get("key_resistance")
if support and resistance:
    msg += f"<b>━━ 技术面 ━━</b>\n"
    msg += f"支撑: ${support:,} | 阻力: ${resistance:,}\n"
    msg += f"趋势: {btc.get('trend_direction','—')}\n\n"

# Macro
fomc = d.get("macro", {}).get("next_fomc")
if fomc:
    msg += f"<b>━━ 宏观 ━━</b>\n"
    msg += f"下次FOMC: {fomc}\n\n"

# Footer
msg += "<i>💡 手机打开HTML附件: 点击文件 → 分享(↗️) → Safari</i>"

print(msg)
PYEOF
)

# Send rich message
echo "Sending rich summary..."
curl -s -X POST "${API}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" \
  --data-urlencode "text=${MESSAGE}" \
  -o /dev/null -w "HTTP %{http_code}\n"

# Send HTML report as document (optional deep dive)
HTML_FILE="reports/${DATE}_${SESSION}.html"
if [ -f "$HTML_FILE" ]; then
  echo "Sending HTML report..."
  curl -s -X POST "${API}/sendDocument" \
    -F "chat_id=${CHAT_ID}" \
    -F "document=@${HTML_FILE}" \
    -F "caption=📊 完整报告 — 点击文件 → 分享(↗️) → Safari 打开" \
    -o /dev/null -w "HTTP %{http_code}\n"
fi

echo "Done."
