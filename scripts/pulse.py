#!/usr/bin/env python3
"""crypto-monitor 2.0 盘中异动脉冲监控（纯脚本，零模型消耗，每 2 小时静默巡检）。

用法:
  python3 scripts/pulse.py            # 正常巡检（仅命中异动时推 Telegram）
  python3 scripts/pulse.py --dry-run  # 本地测试打印，不发 Telegram
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from collect import TrendCollector, load_json, pct_diff

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))
STATE_PATH = ROOT / "data/pulse-state.json"


def fmt_px(v):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"${v:,.0f}"
    if abs(v) >= 1:
        return f"${v:,.2f}"
    if abs(v) >= 0.01:
        return f"${v:.4f}"
    return f"${v:.6f}"


def send_telegram(bot_token, chat_id, html_text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "text": html_text,
    }).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("ok", False)


def main():
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(TZ)
    now_ts = now.timestamp()

    cfg = load_json(ROOT / "config/config.json", {})
    pcfg = cfg.get("pulse", {})
    out_cfg = load_json(ROOT / "config/output.json", {})
    tg_cfg = (out_cfg.get("formats") or {}).get("telegram") or {}
    bot_token, chat_id = tg_cfg.get("bot_token") or "", tg_cfg.get("chat_id") or ""

    collector = TrendCollector()
    selected, all_coins = collector.fetch_perp_universe()
    _, snap_4h = collector.update_and_calc_oi_deltas(all_coins, now_ts)

    latest = load_json(ROOT / "data/latest.json", {}) or {}
    daily_ref = {}
    for pool in (
        latest.get("watchlist_rows") or [],
        (latest.get("market_scan") or {}).get("bull_radar") or [],
        (latest.get("market_scan") or {}).get("bear_radar") or [],
    ):
        for row in pool:
            if row.get("symbol"):
                daily_ref[row["symbol"]] = row
    btc_ref = (latest.get("market_context") or {}).get("btc") or {}
    if btc_ref.get("price_usd"):
        daily_ref.setdefault("BTC", btc_ref)

    cooldown_sec = pcfg.get("cooldown_hours", 6) * 3600
    state = {k: v for k, v in (load_json(STATE_PATH, {}) or {}).items() if isinstance(v, (int, float)) and (now_ts - v) < cooldown_sec}

    min_vol = pcfg.get("min_perp_vol_24h_usd", 30_000_000)
    min_oi = pcfg.get("min_open_interest_usd", 15_000_000)
    brk_buf = pcfg.get("breakout_buffer_pct", 0.3) / 100.0
    sq_fr = pcfg.get("short_squeeze_funding_ann_pct", -38.0)
    sq_chg = pcfg.get("short_squeeze_24h_chg_min", 3.0)
    crowd_fr = pcfg.get("crowded_long_funding_ann_pct", 65.0)
    atr_ext = pcfg.get("atr_extension_warn", 3.0)

    hits = []
    for c in selected:
        sym, vol, oi, p = c["symbol"], c["perp_vol_24h_usd"], c["oi_usd"], c["price_usd"]
        if vol < min_vol or oi < min_oi:
            continue
        chg24 = c.get("chg_24h") or 0.0
        fr_ann = (c["hl_funding_8h_pct"] * 3.0 * 365.0) if c.get("hl_funding_8h_pct") is not None else None
        oi_chg_4h = pct_diff(oi, (snap_4h or {}).get(sym))
        oi_txt = f"｜4h持仓 {oi_chg_4h:+.1f}%" if oi_chg_4h is not None else ""

        ref = daily_ref.get(sym) or {}
        d20h, d20l = ref.get("donchian_20d_high"), ref.get("donchian_20d_low")
        ema20, atr, ref_close = ref.get("ema20"), ref.get("atr14"), ref.get("close_1d")

        if d20h and ref_close and ref_close <= d20h and p > d20h * (1.0 + brk_buf) and chg24 >= 3.0 and f"{sym}:up" not in state:
            hits.append(f"🚀 <b>{escape(sym)}</b> 盘中突破20日高点 {fmt_px(d20h)}\n• 现价 <b>{fmt_px(p)}</b>（{chg24:+.1f}%）｜成交 ${vol/1e6:.0f}M{oi_txt}")
            state[f"{sym}:up"] = int(now_ts)
        elif d20l and ref_close and ref_close >= d20l and p < d20l * (1.0 - brk_buf) and chg24 <= -3.0 and f"{sym}:dn" not in state:
            hits.append(f"🩸 <b>{escape(sym)}</b> 盘中跌破20日低点 {fmt_px(d20l)}\n• 现价 <b>{fmt_px(p)}</b>（{chg24:+.1f}%）｜成交 ${vol/1e6:.0f}M{oi_txt}")
            state[f"{sym}:dn"] = int(now_ts)

        if fr_ann is not None and fr_ann <= sq_fr and chg24 >= sq_chg and f"{sym}:sq" not in state:
            hits.append(f"🔥 <b>{escape(sym)}</b> 极端负费率逼空异动\n• 现价 {fmt_px(p)}（{chg24:+.1f}%）｜年化费率 <b>{fr_ann:+.0f}%</b>{oi_txt}")
            state[f"{sym}:sq"] = int(now_ts)

        if c.get("in_watchlist") and ema20 and atr and atr > 0 and f"{sym}:ext" not in state:
            dist_atr = (p - ema20) / atr
            if abs(dist_atr) >= atr_ext or (fr_ann is not None and fr_ann >= crowd_fr):
                hits.append(f"⚠️ <b>{escape(sym)}</b> 偏离20日均线达 <b>{dist_atr:+.1f}倍波幅</b>（现价 {fmt_px(p)}，切忌顺向追单）")
                state[f"{sym}:ext"] = int(now_ts)

    if not dry_run:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)

    if not hits:
        print(f"[pulse] {now.strftime('%H:%M')} quiet ({len(selected)} perps checked)")
        return 0

    msg = f"⚡ <b>盘中合约异动提醒</b>  <code>{now.strftime('%m-%d %H:%M')}</code>\n\n" + "\n\n".join(hits[:6])
    if dry_run:
        print(msg)
        return 0
    if bot_token and chat_id:
        send_telegram(bot_token, chat_id, msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
