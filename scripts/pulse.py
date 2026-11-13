#!/usr/bin/env python3
"""crypto-monitor 2.0 盘中纯脚本异动脉冲监控器（零大模型消耗，建议每 2 小时运行一次）。

职责：
1. 拉取 OKX Swap + Hyperliquid 实时永续合约价格、成交额、资金费率与 OI，并追加写入 data/oi_history.json（为早报积累真实的 4h/24h OI 增减数据！）
2. 结合当日早报 data/collected.json 中已计算的日线基准位（20D 高低点、EMA20、ATR14），检测三类高价值盘中信号：
   - 🚀 / 🩸 盘中放量突破日线 20D 通道高点 / 低点
   - 🔥 主流合约极端负费率 + 价格逆势走强（潜在空头回补逼空行情）
   - ⚠️ 核心自选池极端正费率拥挤或价格偏离日线 EMA20 超过 3.0x ATR（提示分批止盈防插针，勿追单）
3. 内置冷却去重（默认同一币种同一类型 6 小时内不重复推送，状态存于 data/pulse_state.json）
4. 无异常时完全静默退出（不发垃圾消息）；命中时秒推精简卡片至 Telegram

用法:
  python3 scripts/pulse.py            # 正常巡检，命中则推 Telegram
  python3 scripts/pulse.py --dry-run  # 仅终端打印命中结果，不推 Telegram
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

# 复用 collect.py 中的采集方法与格式化辅助
from collect import TrendCollector, load_json, pct_diff

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))
STATE_PATH = ROOT / "data/pulse_state.json"


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


def send_tg(bot_token, chat_id, html_text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "text": html_text,
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read().decode())
        return bool(resp.get("ok"))


def run_pulse(dry_run=False):
    now = datetime.now(TZ)
    now_ts = now.timestamp()

    tc = TrendCollector()
    pulse_cfg = tc.scan_cfg.get("pulse", {})
    cooldown_sec = pulse_cfg.get("cooldown_hours", 6) * 3600
    min_vol = pulse_cfg.get("min_perp_vol_24h_usd", 25_000_000)
    min_oi = pulse_cfg.get("min_open_interest_usd", 10_000_000)
    brk_buf = pulse_cfg.get("breakout_buffer_pct", 0.3) / 100.0
    sq_fr = pulse_cfg.get("short_squeeze_funding_ann_pct", -38.0)
    sq_chg = pulse_cfg.get("short_squeeze_24h_chg_min", 3.0)
    crowd_fr = pulse_cfg.get("crowded_long_funding_ann_pct", 65.0)
    atr_ext = pulse_cfg.get("atr_extension_warn", 3.0)

    # 1. 读取最近一次日线基准与纯加密白名单，拉取实时全市场合约快照并更新 OI 历史
    collected = load_json(ROOT / "data/collected.json") or {}
    cached_whitelist = set(collected.get("crypto_universe_symbols") or []) or None
    selected, all_coins_map = tc.fetch_perp_universe(cached_whitelist)
    _, snap_4h = tc.update_and_calc_oi_deltas(all_coins_map, now_ts)

    # 2. 构建各合约日线参考位映射
    daily_ref = {}
    for lst_key in ("watchlist_rows", "rs_leaders", "rs_laggards", "setups_candidates"):
        for item in collected.get(lst_key) or []:
            if item.get("symbol"):
                daily_ref.setdefault(item["symbol"], item)

    state = load_json(STATE_PATH, {}) or {}
    # 清理过期冷却记录
    state = {k: ts for k, ts in state.items() if now_ts - ts < cooldown_sec}

    hits = []

    def can_fire(key):
        return key not in state

    def mark_fired(key):
        state[key] = int(now_ts)

    for c in selected:
        sym = c["symbol"]
        vol = c["perp_vol_24h_usd"]
        oi = c["oi_usd"]
        if vol < min_vol or oi < min_oi:
            continue

        p = c["price_usd"]
        chg24 = c.get("chg_24h") or 0.0
        # 优先取 Hyperliquid 实时 1h 折算年化费率（无需额外逐个请求 OKX），核心候选若异常可补充
        fr_8h = c.get("hl_funding_8h_pct")
        fr_ann = (fr_8h * 3.0 * 365.0) if fr_8h is not None else None
        oi_prev_4h = (snap_4h or {}).get(sym)
        oi_chg_4h = pct_diff(oi, oi_prev_4h) if oi_prev_4h else None

        ref = daily_ref.get(sym) or {}
        d20h = ref.get("donchian_20d_high")
        d20l = ref.get("donchian_20d_low")
        ema20 = ref.get("ema20")
        atr = ref.get("atr14")

        # 触发器 1: 盘中突破日线 20D 高/低点（要求当日日线基准尚未提前突破）
        ref_close = ref.get("close_1d")
        if d20h and ref_close and ref_close <= d20h and p > d20h * (1.0 + brk_buf) and chg24 >= 3.0:
            k = f"{sym}:brk20_up"
            if can_fire(k):
                oi_txt = f" | 4h OI {oi_chg_4h:+.1f}%" if oi_chg_4h is not None else ""
                hits.append(
                    f"🚀 <b>{escape(sym)}</b> 盘中突破 20D 日线高点 {fmt_px(d20h)}\n"
                    f"   现价 <b>{fmt_px(p)}</b> (24h {chg24:+.1f}%) | 24h量 ${vol/1e6:.0f}M{oi_txt}"
                )
                mark_fired(k)

        elif d20l and ref_close and ref_close >= d20l and p < d20l * (1.0 - brk_buf) and chg24 <= -3.0:
            k = f"{sym}:brk20_dn"
            if can_fire(k):
                oi_txt = f" | 4h OI {oi_chg_4h:+.1f}%" if oi_chg_4h is not None else ""
                hits.append(
                    f"🩸 <b>{escape(sym)}</b> 盘中跌破 20D 日线低点 {fmt_px(d20l)}\n"
                    f"   现价 <b>{fmt_px(p)}</b> (24h {chg24:+.1f}%) | 24h量 ${vol/1e6:.0f}M{oi_txt}"
                )
                mark_fired(k)

        # 触发器 2: 极端负费率 + 价格逆势走强（逼空监控）
        if fr_ann is not None and fr_ann <= sq_fr and chg24 >= sq_chg:
            k = f"{sym}:short_squeeze"
            if can_fire(k):
                oi_txt = f" | 4h OI {oi_chg_4h:+.1f}%" if oi_chg_4h is not None else ""
                hits.append(
                    f"🔥 <b>{escape(sym)}</b> 极端负费率逼空异动\n"
                    f"   现价 {fmt_px(p)} (24h {chg24:+.1f}%) | 年化费率 <b>{fr_ann:+.0f}%</b> | OI ${oi/1e6:.0f}M{oi_txt}"
                )
                mark_fired(k)

        # 触发器 3: 核心自选池偏离 EMA20 超过 3x ATR 或极端正费率过热
        if c.get("in_watchlist") and ema20 and atr and atr > 0:
            dist_atr = (p - ema20) / atr
            if abs(dist_atr) >= atr_ext or (fr_ann is not None and fr_ann >= crowd_fr):
                k = f"{sym}:overextended"
                if can_fire(k):
                    fr_str = f"{fr_ann:+.0f}%" if fr_ann is not None else "—"
                    hits.append(
                        f"⚠️ <b>{escape(sym)}</b> (自选池) 短期偏离/拥挤预警\n"
                        f"   现价 {fmt_px(p)} 距 EMA20 达 <b>{dist_atr:+.1f}x ATR</b> | 年化费率 {fr_str}（慎追单/可分批锁利）"
                    )
                    mark_fired(k)

    if not dry_run:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)

    if not hits:
        print(f"[pulse] {now.isoformat(timespec='seconds')} — quiet (OI snapshot saved, 0 alerts)", flush=True)
        return 0

    msg = (
        f"<b>⚡ 盘中合约趋势异动脉冲</b>  <code>{now.strftime('%m-%d %H:%M')}</code>\n\n"
        + "\n\n".join(hits[:6])
    )
    print(msg, flush=True)

    if dry_run:
        print("[pulse] dry-run mode, skipping Telegram push.", flush=True)
        return 0

    tg_cfg = (tc.output_cfg.get("formats") or {}).get("telegram") or {}
    if tg_cfg.get("enabled") and tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
        ok = send_tg(tg_cfg["bot_token"], tg_cfg["chat_id"], msg)
        print(f"[pulse] Telegram push: {'OK' if ok else 'FAILED'}", flush=True)
    return 0


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    sys.exit(run_pulse(dry_run=is_dry))
