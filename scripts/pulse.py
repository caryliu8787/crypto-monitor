#!/usr/bin/env python3
"""crypto-monitor 2.1 盘中异动脉冲监控（纯脚本，零模型消耗，每 2 小时静默巡检）。

用法:
  python3 scripts/pulse.py            # 正常巡检（仅命中异动时推 Telegram）
  python3 scripts/pulse.py --dry-run  # 本地只读测试打印，不改写任何文件且不发 Telegram
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from collect import TrendCollector, compute_weighted_funding_ann, load_json, pct_diff

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

    cfg = load_json(ROOT / "config/config.json", {}) or {}
    pcfg = cfg.get("pulse", {})
    out_cfg = load_json(ROOT / "config/output.json", {}) or {}
    tg_cfg = (out_cfg.get("formats") or {}).get("telegram") or {}
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg_cfg.get("bot_token") or ""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or tg_cfg.get("chat_id") or ""

    latest = load_json(ROOT / "data/latest.json", {}) or {}
    setup_map = {
        s["symbol"]: s
        for s in (latest.get("setups") or [])
        if isinstance(s, dict) and s.get("symbol") and s.get("action_override") != "AVOID"
    }

    daily_ref = {}
    for pool in (
        latest.get("setups") or [],
        latest.get("watchlist_rows") or [],
        (latest.get("market_scan") or {}).get("bull_radar") or [],
        (latest.get("market_scan") or {}).get("bear_radar") or [],
        (latest.get("market_scan") or {}).get("neg_funding_leaders") or [],
    ):
        for row in pool:
            if isinstance(row, dict) and row.get("symbol"):
                # 合并字段以保留最完整的日线参考位
                merged_row = dict(daily_ref.get(row["symbol"]) or {})
                merged_row.update({k: v for k, v in row.items() if v is not None})
                daily_ref[row["symbol"]] = merged_row

    btc_ref = (latest.get("market_context") or {}).get("btc") or {}
    if btc_ref.get("price_usd"):
        merged_btc = dict(daily_ref.get("BTC") or {})
        merged_btc.update({k: v for k, v in btc_ref.items() if v is not None})
        daily_ref["BTC"] = merged_btc

    collector = TrendCollector()
    selected, all_coins = collector.fetch_perp_universe(extra_symbols=list(setup_map.keys()))
    if not collector.sources.get("okx_swap") and not collector.sources.get("hyperliquid"):
        print(f"[pulse] {now.strftime('%H:%M')} upstream APIs unavailable, skipped", file=sys.stderr)
        return 0

    _, snap_4h = collector.update_and_calc_oi_deltas(all_coins, now_ts, persist=not dry_run)

    cooldown_sec = pcfg.get("cooldown_hours", 6) * 3600
    state = {
        k: v for k, v in (load_json(STATE_PATH, {}) or {}).items()
        if isinstance(v, (int, float)) and (now_ts - v) < cooldown_sec
    }

    min_vol = pcfg.get("min_perp_vol_24h_usd", 30_000_000)
    min_oi = pcfg.get("min_open_interest_usd", 10_000_000)
    brk_buf = pcfg.get("breakout_buffer_pct", 0.3) / 100.0
    sq_fr = pcfg.get("short_squeeze_funding_ann_pct", -38.0)
    sq_chg = pcfg.get("short_squeeze_24h_chg_min", 3.0)
    crowd_fr = pcfg.get("crowded_long_funding_ann_pct", 65.0)
    atr_ext = pcfg.get("atr_extension_warn", 3.0)

    monitored = [
        c for c in selected
        if c["symbol"] in setup_map or c.get("in_watchlist") or (c["perp_vol_24h_usd"] >= min_vol and c["oi_usd"] >= min_oi)
    ]
    # 补齐 OKX 实时资金费率，使盘中监控与早报完全统一为 OKX+HL 持仓加权费率口径
    collector.fetch_okx_funding_for_coins(monitored)

    hits = []
    for c in monitored:
        sym, vol, oi, p = c["symbol"], c["perp_vol_24h_usd"], c["oi_usd"], c["price_usd"]
        chg24 = c.get("chg_24h") or 0.0
        fr_ann = compute_weighted_funding_ann(c)
        oi_chg_4h = pct_diff(oi, (snap_4h or {}).get(sym))
        oi_txt = f"｜4h持仓 {oi_chg_4h:+.1f}%" if oi_chg_4h is not None else ""

        ref = daily_ref.get(sym) or {}
        d20h, d20l = ref.get("donchian_20d_high"), ref.get("donchian_20d_low")
        p20h, p20l = ref.get("prev_20d_high"), ref.get("prev_20d_low")
        ema20, atr, ref_close = ref.get("ema20"), ref.get("atr14"), ref.get("close_1d")
        is_watch_setup = (setup_map.get(sym) or {}).get("direction") == "WATCH"
        min_brk_chg = 1.5 if is_watch_setup else 3.0

        already_broke_up = bool(p20h and ref_close and ref_close >= p20h)
        already_broke_dn = bool(p20l and ref_close and ref_close <= p20l)

        # 触发器 1: 盘中新鲜突破 / 跌破 20 日高低点（过滤昨日已收盘确认的旧突破）
        if d20h and not already_broke_up and p > d20h * (1.0 + brk_buf) and chg24 >= min_brk_chg and f"{sym}:up" not in state:
            prefix = "🎯 早报观察池突破" if is_watch_setup else "🚀 盘中突破20日高点"
            hits.append(f"{prefix} <b>{escape(sym)}</b> 上破 {fmt_px(d20h)}\n• 现价 <b>{fmt_px(p)}</b>（{chg24:+.1f}%）｜成交 ${vol/1e6:.0f}M{oi_txt}")
            state[f"{sym}:up"] = int(now_ts)
        elif d20l and not already_broke_dn and p < d20l * (1.0 - brk_buf) and chg24 <= -min_brk_chg and f"{sym}:dn" not in state:
            prefix = "🎯 早报观察池破位" if is_watch_setup else "🩸 盘中跌破20日低点"
            hits.append(f"{prefix} <b>{escape(sym)}</b> 下破 {fmt_px(d20l)}\n• 现价 <b>{fmt_px(p)}</b>（{chg24:+.1f}%）｜成交 ${vol/1e6:.0f}M{oi_txt}")
            state[f"{sym}:dn"] = int(now_ts)

        # 触发器 2: 极端负费率轧空异动（OKX + HL 加权费率口径）
        if fr_ann is not None and fr_ann <= sq_fr and chg24 >= sq_chg and f"{sym}:sq" not in state:
            hits.append(f"🔥 <b>{escape(sym)}</b> 极端负费率逼空异动\n• 现价 {fmt_px(p)}（{chg24:+.1f}%）｜加权年化费率 <b>{fr_ann:+.0f}%</b>{oi_txt}")
            state[f"{sym}:sq"] = int(now_ts)

        # 触发器 3: 核心自选 / 早报剧本 均线过度偏离 vs 多头费率过热（文案与冷却严格分离）
        if (c.get("in_watchlist") or sym in setup_map) and ema20 and atr and atr > 0:
            dist_atr = (p - ema20) / atr
            if abs(dist_atr) >= atr_ext and f"{sym}:ext" not in state:
                hits.append(f"⚠️ <b>{escape(sym)}</b> 偏离20日均线达 <b>{dist_atr:+.1f}倍波幅</b>（现价 {fmt_px(p)}，切忌顺向追单）")
                state[f"{sym}:ext"] = int(now_ts)
            if fr_ann is not None and fr_ann >= crowd_fr and f"{sym}:crowd" not in state:
                hits.append(f"⚠️ <b>{escape(sym)}</b> 多头资金费率过热 <b>{fr_ann:+.0f}%</b>（现价 {fmt_px(p)}，警惕多单拥挤踩踏）")
                state[f"{sym}:crowd"] = int(now_ts)

    if not dry_run:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)

    if not hits:
        print(f"[pulse] {now.strftime('%H:%M')} quiet ({len(monitored)}/{len(selected)} perps checked)")
        return 0

    msg = f"⚡ <b>盘中合约异动提醒</b>  <code>{now.strftime('%m-%d %H:%M')}</code>\n\n" + "\n\n".join(hits[:6])
    if dry_run:
        print(msg)
        return 0
    if bot_token and chat_id:
        send_telegram(bot_token, chat_id, msg)
        print(f"[pulse] {now.strftime('%H:%M')} sent {len(hits)} alert(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
