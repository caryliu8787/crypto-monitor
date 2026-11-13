#!/usr/bin/env python3
"""crypto-monitor 2.1 量化采集引擎（含运行前归档 + 失败熔断保护 + 日线结构扫描）。

用法: python3 scripts/collect.py [daily]
失败退出码: 2（当核心交易所接口不可用、有效合约数不足 15 或 BTC 日线缺失时熔断退出，绝不产出残缺 collected.json）
"""

import json
import math
import os
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))

OKX_BASE = "https://www.okx.com"
HL_INFO = "https://api.hyperliquid.xyz/info"
CG_BASE = "https://api.coingecko.com/api/v3"

MIN_VALID_PERPS = 15


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fetch_json(url, headers=None, body=None, timeout=25):
    hdrs = {"User-Agent": "crypto-trend-radar/2.1"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body is not None else None

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(15)
                continue
            return None
        except Exception:
            return None
    return None


def classify_regime(total_score):
    """根据四维总分（4~20）确定性映射市场阶段与仓位纪律（供 collect 与 publish 共用）。"""
    if total_score >= 15:
        return (
            "BULL_TREND",
            "多头趋势期",
            "顺势做多突破与20日线回踩标的，总名义仓位上限 2.0x–3.0x，不做逆势空单。",
        )
    if total_score >= 12:
        return (
            "BULL_LEAN",
            "偏多结构期",
            "逢回踩20日线布局相对大饼强势币，总仓位建议 1.0x–2.0x，不追高费率品种。",
        )
    if total_score >= 9:
        return (
            "CHOP_SELECTIVE",
            "震荡分化期",
            "控制出手频率（总仓位 ≤1.0x–1.5x），仅做独立逻辑强α或多空配对，防假突破磨损。",
        )
    if total_score >= 6:
        return (
            "BEAR_PRESSURE",
            "空头承压期",
            "防守为主（总仓位 ≤1.0x）：严禁大跌后低位追空大饼；只做极少数独立强势/负费率逼空多单，弱势币等反抽20日线再空。",
        )
    return (
        "DEEP_BEAR",
        "单边恐慌宣泄期",
        "严控回撤（≤0.5x–1.0x）：警惕极端负费率暴力轧空，空单等反抽均线再进，抄底等日线收复20日线。",
    )


def housekeeping(now_ts):
    """运行前日志清理与有效 latest.json 备份（仅当 latest.json 含有效 BTC 价格时才更新 .bak）。"""
    (ROOT / "logs").mkdir(exist_ok=True)
    hist_dir = ROOT / "data/history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    for p in (ROOT / "logs").glob("*"):
        if p.is_file() and (now_ts - p.stat().st_mtime) > 7 * 86400:
            p.unlink(missing_ok=True)

    latest_path = ROOT / "data/latest.json"
    prev = load_json(latest_path, {}) or {}
    btc_px = ((prev.get("market_context") or {}).get("btc") or {}).get("price_usd")
    if btc_px and btc_px > 0:
        shutil.copy2(latest_path, ROOT / "data/latest.json.bak")
        ts = (prev.get("timestamp") or "")[:10]
        if ts:
            shutil.copy2(latest_path, hist_dir / f"{ts}_daily.json")

    for p in hist_dir.glob("*.json"):
        if (now_ts - p.stat().st_mtime) > 30 * 86400:
            p.unlink(missing_ok=True)


def compute_weighted_funding_ann(coin):
    """计算 OKX + Hyperliquid 按持仓 OI 加权的年化资金费率（%），供 collect 与 pulse 共用。"""
    okx_fr = coin.get("okx_funding_8h_pct")
    hl_fr = coin.get("hl_funding_8h_pct")
    oi_tot = coin.get("oi_usd") or 0.0
    if okx_fr is not None and hl_fr is not None and oi_tot > 0:
        fr_8h = (okx_fr * (coin.get("okx_oi_usd") or 0.0) + hl_fr * (coin.get("hl_oi_usd") or 0.0)) / oi_tot
    elif okx_fr is not None:
        fr_8h = okx_fr
    else:
        fr_8h = hl_fr
    return (fr_8h * 3.0 * 365.0) if fr_8h is not None else None


# ---------- 技术指标纯函数 ----------

def calc_ema_series(values, span):
    n = len(values)
    if n < span:
        return [None] * n
    out = [None] * (span - 1)
    prev = sum(values[:span]) / span
    out.append(prev)
    k = 2.0 / (span + 1.0)
    for v in values[span:]:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def calc_wilder_atr(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 1:
        return None
    trs = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, n)
    ]
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_bb_width_pctile(closes, period=20, lookback=60):
    if len(closes) < period + 10:
        return None
    widths = []
    for idx in range(max(period, len(closes) - lookback), len(closes) + 1):
        win = closes[idx - period:idx]
        mean = sum(win) / period
        if mean > 0:
            var = sum((x - mean) ** 2 for x in win) / period
            widths.append((4.0 * math.sqrt(var)) / mean * 100.0)
    if len(widths) < 5:
        return None
    cur = widths[-1]
    return round(sum(1 for w in widths if w <= cur) / len(widths) * 100.0, 1)


def pct_diff(a, b):
    return ((a - b) / b * 100.0) if (a is not None and b) else None


def round_sig(val, digits=4):
    if val is None:
        return None
    if val == 0:
        return 0.0
    if abs(val) >= 1000:
        return round(val, 2)
    if abs(val) >= 1:
        return round(val, 4)
    return float(f"{val:.{digits}g}")


def fmt_rule_px(v):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"${v:,.0f}"
    if abs(v) >= 1:
        return f"${v:,.2f}"
    if abs(v) >= 0.01:
        return f"${v:.4f}"
    return f"${v:.6f}"


# ---------- 主采集引擎 ----------

class TrendCollector:
    def __init__(self):
        self.cfg = load_json(ROOT / "config/config.json", {})
        self.out_cfg = load_json(ROOT / "config/output.json", {})
        self.prev = load_json(ROOT / "data/latest.json", {}) or {}
        self.sources = {}
        cg_key = (self.out_cfg.get("api_keys") or {}).get("coingecko_demo") or ""
        self._cg_hdr = {"x-cg-demo-api-key": cg_key} if cg_key else {}

    def get_crypto_whitelist(self):
        limit = min(250, self.cfg.get("universe", {}).get("coingecko_top_limit", 150))
        rows = fetch_json(
            f"{CG_BASE}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={limit}&page=1",
            headers=self._cg_hdr,
        )
        syms = {(r.get("symbol") or "").upper() for r in (rows or []) if r.get("symbol")}
        self.sources["coingecko_top150"] = "coingecko" if syms else None
        return syms

    def fetch_okx_funding_for_coins(self, coins_iter):
        """并发补齐指定合约的 OKX 实时资金费率（供 collect 与 pulse 统一口径调用）。"""
        targets = [c for c in coins_iter if c.get("okx_inst_id") and c.get("okx_funding_8h_pct") is None]
        if not targets:
            return

        def _one(c):
            iid = c["okx_inst_id"]
            fr_data = (fetch_json(f"{OKX_BASE}/api/v5/public/funding-rate?instId={iid}", timeout=12) or {}).get("data") or []
            if fr_data and fr_data[0].get("fundingRate") not in (None, ""):
                try:
                    c["okx_funding_8h_pct"] = float(fr_data[0]["fundingRate"]) * 100.0
                except (TypeError, ValueError):
                    pass

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_one, targets))

    def fetch_perp_universe(self, crypto_whitelist=None, extra_symbols=None):
        uni = self.cfg.get("universe", {})
        exclude = {s.upper() for s in uni.get("exclude_bases", [])}
        min_vol = uni.get("min_perp_vol_24h_usd", 15_000_000)
        min_oi = uni.get("min_open_interest_usd", 10_000_000)
        top_n = uni.get("top_n_perps", 60)
        watch_syms = [str(s).upper() for s in self.cfg.get("watchlist", [])]
        must_include = {s.upper() for s in (extra_symbols or [])} | set(watch_syms) | {"BTC", "ETH"}

        okx_t = (fetch_json(f"{OKX_BASE}/api/v5/market/tickers?instType=SWAP") or {}).get("data") or []
        okx_oi = (fetch_json(f"{OKX_BASE}/api/v5/public/open-interest?instType=SWAP") or {}).get("data") or []
        self.sources["okx_swap"] = "okx_v5" if okx_t else None

        oi_by_inst = {}
        for item in okx_oi:
            try:
                oi_by_inst[item.get("instId")] = float(item.get("oiUsd") or 0)
            except (TypeError, ValueError):
                pass

        raw_bases = {
            t["instId"][:-10].upper()
            for t in okx_t
            if (t.get("instId") or "").endswith("-USDT-SWAP")
        }

        coins = {}
        for t in okx_t:
            iid = t.get("instId") or ""
            if not iid.endswith("-USDT-SWAP"):
                continue
            raw_base = iid[:-10].upper()
            scale, sym = 1.0, raw_base
            if raw_base.startswith("1000") and len(raw_base) > 4:
                stripped = raw_base[4:]
                if stripped in raw_bases:
                    continue
                sym, scale = stripped, 1000.0
            if sym in exclude:
                continue
            try:
                last = float(t["last"]) / scale
                open24 = float(t["open24h"]) / scale if t.get("open24h") else None
                vol_usd = float(t.get("volCcy24h") or 0) * scale * last
                oi_usd = oi_by_inst.get(iid, 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            if last <= 0:
                continue
            coins[sym] = {
                "symbol": sym, "price_usd": last, "chg_24h": pct_diff(last, open24) if open24 else None,
                "okx_inst_id": iid, "okx_scale": scale, "okx_vol_usd": vol_usd, "okx_oi_usd": oi_usd, "okx_funding_8h_pct": None,
                "hl_coin": None, "hl_scale": 1.0, "hl_vol_usd": 0.0, "hl_oi_usd": 0.0, "hl_funding_8h_pct": None,
            }

        hl_resp = fetch_json(HL_INFO, body={"type": "metaAndAssetCtxs"})
        self.sources["hyperliquid"] = "hyperliquid_info" if hl_resp else None
        if isinstance(hl_resp, list) and len(hl_resp) >= 2:
            for u, ctx in zip((hl_resp[0] or {}).get("universe") or [], hl_resp[1] or []):
                if u.get("isDelisted") or not u.get("name"):
                    continue
                name = u["name"]
                scale, sym = (1000.0, name[1:].upper()) if (name.startswith("k") and len(name) > 1 and name[1:].isupper()) else (1.0, name.upper())
                if sym in exclude:
                    continue
                try:
                    mark_raw = float(ctx.get("markPx") or 0)
                    prev_raw = float(ctx.get("prevDayPx") or 0)
                    vol_usd = float(ctx.get("dayNtlVlm") or 0)
                    oi_usd = float(ctx.get("openInterest") or 0) * mark_raw
                    fr_1h = float(ctx["funding"]) if ctx.get("funding") is not None else None
                except (TypeError, ValueError):
                    continue
                if mark_raw <= 0:
                    continue
                price = mark_raw / scale
                prev_px = prev_raw / scale if prev_raw > 0 else None
                fr_8h = (fr_1h * 8.0 * 100.0) if fr_1h is not None else None

                if sym in coins:
                    coins[sym].update({"hl_coin": name, "hl_scale": scale, "hl_vol_usd": vol_usd, "hl_oi_usd": oi_usd, "hl_funding_8h_pct": fr_8h})
                else:
                    coins[sym] = {
                        "symbol": sym, "price_usd": price, "chg_24h": pct_diff(price, prev_px) if prev_px else None,
                        "okx_inst_id": None, "okx_scale": 1.0, "okx_vol_usd": 0.0, "okx_oi_usd": 0.0, "okx_funding_8h_pct": None,
                        "hl_coin": name, "hl_scale": scale, "hl_vol_usd": vol_usd, "hl_oi_usd": oi_usd, "hl_funding_8h_pct": fr_8h,
                    }

        eligible = []
        for sym, c in coins.items():
            c["perp_vol_24h_usd"] = c["okx_vol_usd"] + c["hl_vol_usd"]
            c["oi_usd"] = c["okx_oi_usd"] + c["hl_oi_usd"]
            c["in_watchlist"] = sym in watch_syms
            if crypto_whitelist and sym not in crypto_whitelist and sym not in must_include:
                continue
            if sym in must_include or (c["perp_vol_24h_usd"] >= min_vol and c["oi_usd"] >= min_oi):
                eligible.append(c)

        eligible.sort(key=lambda x: 0.6 * x["perp_vol_24h_usd"] + 0.4 * x["oi_usd"], reverse=True)
        selected = {c["symbol"]: c for c in eligible[:top_n]}
        for sym in must_include:
            if sym in coins:
                selected.setdefault(sym, coins[sym])
        return list(selected.values()), coins

    def update_and_calc_oi_deltas(self, all_coins_map, now_ts, persist=True):
        oi_path = ROOT / "data/oi_history.json"
        cutoff = now_ts - 72 * 3600
        hist = [
            h for h in (load_json(oi_path, []) or [])
            if isinstance(h, dict) and (h.get("ts") or 0) >= cutoff and bool(h.get("oi"))
        ]
        cur_oi = {sym: round(c["oi_usd"], 2) for sym, c in all_coins_map.items() if (c.get("oi_usd") or 0) >= 2_000_000}

        def find_snap(target_s, min_s, max_s):
            best, best_d = None, 1e18
            for h in hist:
                age = now_ts - (h.get("ts") or 0)
                if min_s <= age <= max_s and abs(age - target_s) < best_d:
                    best_d = abs(age - target_s)
                    best = h.get("oi") or {}
            return best

        snap_24h = find_snap(24 * 3600, 14 * 3600, 36 * 3600)
        snap_4h = find_snap(4 * 3600, 1.5 * 3600, 8 * 3600)
        if persist and cur_oi and (not hist or (now_ts - hist[-1].get("ts", 0)) >= 1200):
            hist.append({"ts": int(now_ts), "oi": cur_oi})
            with open(oi_path, "w") as f:
                json.dump(hist, f, separators=(",", ":"))
        return snap_24h, snap_4h

    def _fetch_coin_detail(self, coin, candle_days, now_ms):
        closed_bars, candle_src = [], None
        if coin.get("okx_inst_id"):
            iid = coin["okx_inst_id"]
            scale = coin.get("okx_scale", 1.0)
            rows = (fetch_json(f"{OKX_BASE}/api/v5/market/candles?instId={iid}&bar=1Dutc&limit={min(299, candle_days + 5)}") or {}).get("data") or []
            if rows:
                candle_src = "okx_1Dutc"
                for r in reversed(rows):
                    try:
                        if str(r[8]) == "1":
                            ts = int(r[0])
                            closed_bars.append({
                                "date": datetime.fromtimestamp(ts / 1000.0, timezone.utc).strftime("%Y-%m-%d"),
                                "o": float(r[1]) / scale, "h": float(r[2]) / scale,
                                "l": float(r[3]) / scale, "c": float(r[4]) / scale,
                                "qv": float(r[7]),
                            })
                    except (IndexError, TypeError, ValueError):
                        continue
            fr_data = (fetch_json(f"{OKX_BASE}/api/v5/public/funding-rate?instId={iid}") or {}).get("data") or []
            if fr_data and fr_data[0].get("fundingRate") not in (None, ""):
                try:
                    coin["okx_funding_8h_pct"] = float(fr_data[0]["fundingRate"]) * 100.0
                except (TypeError, ValueError):
                    pass

        if not closed_bars and coin.get("hl_coin"):
            scale = coin.get("hl_scale", 1.0)
            resp = fetch_json(HL_INFO, body={
                "type": "candleSnapshot",
                "req": {"coin": coin["hl_coin"], "interval": "1d", "startTime": now_ms - (candle_days + 5) * 86400 * 1000, "endTime": now_ms},
            })
            if isinstance(resp, list) and resp:
                candle_src = "hyperliquid_1d"
                for r in sorted(resp, key=lambda x: int(x.get("t", 0))):
                    try:
                        if int(r["T"]) < now_ms:
                            c_raw = float(r["c"])
                            closed_bars.append({
                                "date": datetime.fromtimestamp(int(r["t"]) / 1000.0, timezone.utc).strftime("%Y-%m-%d"),
                                "o": float(r["o"]) / scale, "h": float(r["h"]) / scale,
                                "l": float(r["l"]) / scale, "c": c_raw / scale,
                                "qv": float(r["v"]) * c_raw,
                            })
                    except (KeyError, TypeError, ValueError):
                        continue
        return coin["symbol"], closed_bars, candle_src

    def enrich_universe_metrics(self, selected, snap_24h, snap_4h):
        candle_days = self.cfg.get("universe", {}).get("candle_days", 220)
        now_ms = int(time.time() * 1000)
        candle_map = {}

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {}
            for idx, coin in enumerate(selected):
                if idx > 0 and idx % 8 == 0:
                    time.sleep(0.2)
                futs[pool.submit(self._fetch_coin_detail, coin, candle_days, now_ms)] = coin["symbol"]
            for fut in as_completed(futs):
                sym, bars, src = fut.result()
                candle_map[sym] = (bars, src)

        self.sources["daily_candles"] = "okx_1Dutc+hyperliquid_1d" if any(b for b, _ in candle_map.values()) else None
        btc_bars = candle_map.get("BTC", ([], None))[0]
        btc_p = next((c["price_usd"] for c in selected if c["symbol"] == "BTC"), None)

        # closed[-1] 为最近一根 00:00 UTC 收盘，closed[-(d+1)] 的收盘恰为 d*24h 前（消除 1 天偏差）
        def ret_nd(cur_p, bars, d):
            idx = d + 1
            return pct_diff(cur_p, bars[-idx]["c"]) if (cur_p is not None and len(bars) >= idx) else None

        btc_r7 = ret_nd(btc_p, btc_bars, 7)
        btc_r14 = ret_nd(btc_p, btc_bars, 14)

        enriched = []
        for c in selected:
            sym = c["symbol"]
            closed, c_src = candle_map.get(sym, ([], None))
            if len(closed) < 22:
                continue
            closes = [b["c"] for b in closed]
            highs = [b["h"] for b in closed]
            lows = [b["l"] for b in closed]
            qvols = [b["qv"] for b in closed]

            ema20_s = calc_ema_series(closes, 20)
            ema50_s = calc_ema_series(closes, 50)
            ema200_s = calc_ema_series(closes, 200)
            ema20, ema50, ema200 = ema20_s[-1], ema50_s[-1], ema200_s[-1]
            ema20_prev3 = ema20_s[-4] if len(ema20_s) >= 4 and ema20_s[-4] is not None else ema20
            atr14 = calc_wilder_atr(highs, lows, closes, 14)

            live_p = c["price_usd"]
            close_1d = closes[-1]
            prev_20d_high, prev_20d_low = max(highs[-21:-1]), min(lows[-21:-1])
            d20h, d20l = max(highs[-20:]), min(lows[-20:])
            d10h, d10l = max(highs[-10:]), min(lows[-10:])
            d55h = max(highs[-55:]) if len(highs) >= 55 else max(highs)
            d55l = min(lows[-55:]) if len(lows) >= 55 else min(lows)
            range_20d_pct = ((d20h - d20l) / d20l * 100.0) if d20l > 0 else None

            avg_qv20 = sum(qvols[-21:-1]) / 20.0
            vol_ratio = (qvols[-1] / avg_qv20) if avg_qv20 > 0 else None
            bb_pctile = calc_bb_width_pctile(closes, 20, 60)

            chg_7d = ret_nd(live_p, closed, 7)
            chg_14d = ret_nd(live_p, closed, 14)
            rs_7d = (chg_7d - btc_r7) if (chg_7d is not None and btc_r7 is not None) else None
            rs_14d = (chg_14d - btc_r14) if (chg_14d is not None and btc_r14 is not None) else None

            fr_ann = compute_weighted_funding_ann(c)
            oi_now = c["oi_usd"]
            oi_chg_24h = pct_diff(oi_now, (snap_24h or {}).get(sym))
            oi_chg_4h = pct_diff(oi_now, (snap_4h or {}).get(sym))

            dist20_pct = pct_diff(live_p, ema20) if ema20 else None
            atr_pct = (atr14 / live_p * 100.0) if (atr14 and live_p) else None
            dist20_atr = ((live_p - ema20) / atr14) if (ema20 and atr14 and atr14 > 0) else None
            pos_20d = round(max(0.0, min(100.0, (live_p - d20l) / (d20h - d20l) * 100.0)), 1) if d20h > d20l else None

            ema20_rising = bool(ema20 and ema20_prev3 and ema20 >= ema20_prev3)
            if ema20 and ema50:
                if live_p > ema20 > ema50 and ema20_rising:
                    t_state, t_label = "STRONG_UP", "多头排列"
                elif ema20 > ema50 and live_p >= ema50 * 0.99:
                    t_state, t_label = "UP_PULLBACK", "多头回踩"
                elif live_p < ema20 < ema50 and not ema20_rising:
                    t_state, t_label = "STRONG_DOWN", "空头排列"
                elif ema20 < ema50 and live_p <= ema50 * 1.01:
                    t_state, t_label = "DOWN_BOUNCE", "空头反抽"
                else:
                    t_state, t_label = "RANGE_CHOP", "均线纠缠"
            else:
                t_state, t_label = "RANGE_CHOP", "结构待定"

            item = {
                "symbol": sym,
                "in_watchlist": c["in_watchlist"],
                "candle_source": c_src,
                "last_closed_date": closed[-1]["date"],
                "price_usd": round_sig(live_p, 5),
                "close_1d": round_sig(close_1d, 5),
                "chg_24h": round(c["chg_24h"], 2) if c["chg_24h"] is not None else None,
                "chg_7d": round(chg_7d, 2) if chg_7d is not None else None,
                "chg_14d": round(chg_14d, 2) if chg_14d is not None else None,
                "rs_7d": round(rs_7d, 2) if rs_7d is not None else None,
                "rs_14d": round(rs_14d, 2) if rs_14d is not None else None,
                "ema20": round_sig(ema20, 5),
                "ema50": round_sig(ema50, 5),
                "ema200": round_sig(ema200, 5),
                "ema20_rising": ema20_rising,
                "dist_ema20_pct": round(dist20_pct, 2) if dist20_pct is not None else None,
                "dist_ema20_atr": round(dist20_atr, 2) if dist20_atr is not None else None,
                "atr14": round_sig(atr14, 5),
                "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
                "prev_20d_high": round_sig(prev_20d_high, 5),
                "prev_20d_low": round_sig(prev_20d_low, 5),
                "donchian_20d_high": round_sig(d20h, 5),
                "donchian_20d_low": round_sig(d20l, 5),
                "donchian_10d_high": round_sig(d10h, 5),
                "donchian_10d_low": round_sig(d10l, 5),
                "donchian_55d_high": round_sig(d55h, 5),
                "donchian_55d_low": round_sig(d55l, 5),
                "range_20d_pct": round(range_20d_pct, 2) if range_20d_pct is not None else None,
                "pos_in_20d_pct": pos_20d,
                "vol_ratio_1d": round(vol_ratio, 2) if vol_ratio is not None else None,
                "bb_width_pctile": bb_pctile,
                "trend_state": t_state,
                "trend_label": t_label,
                "perp_vol_24h_usd": round(c["perp_vol_24h_usd"], 0),
                "oi_usd": round(oi_now, 0),
                "oi_change_24h_pct": round(oi_chg_24h, 2) if oi_chg_24h is not None else None,
                "oi_change_4h_pct": round(oi_chg_4h, 2) if oi_chg_4h is not None else None,
                "funding_ann_pct": round(fr_ann, 2) if fr_ann is not None else None,
            }
            if sym == "BTC":
                tail = min(60, len(closed))
                item["chart_60d"] = {
                    "dates": [b["date"][5:] for b in closed[-tail:]],
                    "closes": [round(b["c"], 2) for b in closed[-tail:]],
                    "ema20": [round(x, 2) if x is not None else None for x in ema20_s[-tail:]],
                    "ema50": [round(x, 2) if x is not None else None for x in ema50_s[-tail:]],
                }
            enriched.append(item)
        return enriched

    def scan_setups(self, enriched, today_str, regime_code):
        scfg = self.cfg.get("setups", {})
        max_atr = self.cfg.get("universe", {}).get("max_atr_pct_filter", 20.0)
        max_act = scfg.get("max_actionable", 4)
        max_wat = scfg.get("max_watch", 3)
        vol_min = scfg.get("breakout_vol_ratio_min", 1.25)
        pb_lo, pb_hi = scfg.get("pullback_ema20_band_pct", [-2.8, 3.2])
        bn_lo, bn_hi = scfg.get("bounce_ema20_band_pct", [-3.2, 2.8])
        max_long_fr = scfg.get("max_long_funding_ann_pct", 50.0)
        min_short_fr = scfg.get("min_short_funding_ann_pct", -30.0)
        sq_max = scfg.get("squeeze_bb_pctile_max", 15.0)
        sq_rng_max = scfg.get("squeeze_20d_range_max_pct", 18.0)
        unit_risk = scfg.get("unit_risk_equity_pct", 1.0)
        max_lev = scfg.get("max_leverage_cap", 3.0)

        is_bull_regime = regime_code in ("BULL_TREND", "BULL_LEAN")
        is_bear_regime = regime_code in ("BEAR_PRESSURE", "DEEP_BEAR")

        action_pool, watch_pool = [], []

        for m in enriched:
            sym, p, c1d, ema20, ema50, atr = m["symbol"], m["price_usd"], m["close_1d"], m["ema20"], m["ema50"], m["atr14"]
            if not (p and c1d and ema20 and atr and atr > 0) or (m.get("atr_pct") or 0) > max_atr:
                continue

            fr_ann = m["funding_ann_pct"] if m["funding_ann_pct"] is not None else 0.0
            vr = m["vol_ratio_1d"] or 1.0
            rs14, rs7 = m["rs_14d"] or 0.0, m["rs_7d"] or 0.0
            dist20, dist_atr = m["dist_ema20_pct"] or 0.0, m["dist_ema20_atr"] or 0.0
            p20h, p20l = m["prev_20d_high"], m["prev_20d_low"]
            d20h, d20l = m["donchian_20d_high"], m["donchian_20d_low"]
            d10h, d10l = m["donchian_10d_high"], m["donchian_10d_low"]
            rng20 = m.get("range_20d_pct") or 999.0

            coin_actions, coin_watch = [], []

            def build_risk_from_entry(entry_raw, stop_ref, is_long):
                """严格以实际计划进场价 entry_px 为基准计算止损宽度与 1% 风险定仓，确保展示价格与百分比 100% 自洽。"""
                entry_px = round_sig(entry_raw, 5)
                raw_dist = ((entry_px - stop_ref) if is_long else (stop_ref - entry_px)) / entry_px * 100.0
                if raw_dist < 2.0:
                    stop_ref = entry_px - 1.8 * atr if is_long else entry_px + 1.8 * atr
                stop_px = round_sig(stop_ref, 5)
                exact_dist = abs(entry_px - stop_px) / entry_px * 100.0
                size_1r = int(min(max_lev * 100.0, math.floor(unit_risk / exact_dist * 100.0 + 0.5)))
                if size_1r * exact_dist / 100.0 > unit_risk * 1.02 and size_1r > 1:
                    size_1r -= 1
                rr_sc = 5 if 3.0 <= exact_dist <= 8.5 else (4 if exact_dist <= 12.0 else (3 if exact_dist <= 16.0 else 2))
                return entry_px, stop_px, round(exact_dist, 2), max(1, size_1r), rr_sc

            # A1: LONG 20D 通道突破（空头期仅允许 14D 相对大饼 >= +10% 的独立强 α）
            if (not is_bear_regime or rs14 >= 10.0) and ((c1d >= p20h and p >= p20h * 0.99) or p > d20h * 1.001) and fr_ann <= max_long_fr and dist_atr <= 2.8 and (vr >= vol_min or (m["chg_24h"] or 0) >= 4.0):
                brk_lvl = round_sig(p20h if c1d >= p20h else d20h, 5)
                sc_px = max(d10l, ema20 - 0.5 * atr)
                if sc_px >= max(p, brk_lvl) * 0.975:
                    sc_px = max(p, brk_lvl) - 1.8 * atr
                entry_px, stop_px, stop_pct, size_1r, rr_sc = build_risk_from_entry(max(p, brk_lvl), sc_px, True)
                vol_word = f"放量突破20日高点（量能比 {vr:.2f}x）" if vr >= vol_min else f"日线突破20日高点（昨日量比 {vr:.2f}x，盘中走强）"
                s_st = 5 if (ema50 and ema20 > ema50 and c1d > p20h) else 4
                s_mo = 5 if (vr >= 1.6 and rs14 >= 8) else (4 if (vr >= 1.25 or rs14 >= 4) else 3)
                s_cr = 5 if fr_ann <= 5 else (4 if fr_ann <= 20 else 3)
                coin_actions.append({
                    "direction": "LONG", "setup_type": "breakout_20d", "setup_label": "日线20日高点突破",
                    "trigger_price": entry_px, "trigger_rule": f"站稳突破位 {fmt_rule_px(brk_lvl)} 跟进（按 {fmt_rule_px(entry_px)} 计仓）",
                    "stop_price": stop_px, "stop_rule": f"日线收盘跌破 {fmt_rule_px(stop_px)} 止损（-{stop_pct}%）",
                    "stop_dist_pct": stop_pct, "notional_1r_pct": size_1r,
                    "score": {"structure": s_st, "momentum": s_mo, "crowding": s_cr, "risk_reward": rr_sc, "total": s_st + s_mo + s_cr + rr_sc},
                    "quant_summary": f"{vol_word}，14天相对大饼 {rs14:+.1f}%，年化费率 {fr_ann:+.1f}%。",
                })

            # A2: LONG 多头排列回踩 EMA20（空头期要求 rs14 >= 8% 强抗跌）
            if (not is_bear_regime or rs14 >= 8.0) and ema50 and ema20 > ema50 and (m["ema20_rising"] or p >= ema20) and pb_lo <= dist20 <= pb_hi and p > ema50 * 1.005 and rs14 >= 2.0 and fr_ann <= 35.0:
                entry_px, stop_px, stop_pct, size_1r, rr_sc = build_risk_from_entry(
                    ema20 if p >= ema20 else p, min(ema50 * 0.99, ema20 - 1.5 * atr), True
                )
                rule_txt = (
                    f"挂单/等待回踩 20 日均线 {fmt_rule_px(entry_px)} 企稳低吸"
                    if p >= ema20
                    else f"现价已回踩至 20 日均线（{fmt_rule_px(ema20)}）下方，于 {fmt_rule_px(entry_px)} 企稳收阳低吸"
                )
                s_st = 5 if (m.get("ema200") and ema50 > m["ema200"]) else 4
                s_mo = 5 if rs14 >= 10 else 4
                s_cr = 5 if fr_ann <= 5 else 4
                coin_actions.append({
                    "direction": "LONG", "setup_type": "pullback_ema20", "setup_label": "多头排列回踩20日线",
                    "trigger_price": entry_px, "trigger_rule": rule_txt,
                    "stop_price": stop_px, "stop_rule": f"日线收盘跌破防守位 {fmt_rule_px(stop_px)} 离场（-{stop_pct}%）",
                    "stop_dist_pct": stop_pct, "notional_1r_pct": size_1r,
                    "score": {"structure": s_st, "momentum": s_mo, "crowding": s_cr, "risk_reward": rr_sc, "total": s_st + s_mo + s_cr + rr_sc},
                    "quant_summary": f"日线维持多头排列，现价距20日均线 {dist20:+.1f}%，14天跑赢大饼 {rs14:+.1f}%。",
                })

            # A3: LONG 逆势多头领涨 / 负费率逼空
            if p >= ema20 * 0.985 and rs7 >= 6.0 and ((ema50 and ema20 > ema50) or fr_ann <= -15.0) and dist_atr <= 2.4:
                raw_entry = ema20 if p >= ema20 else p
                entry_px, stop_px, stop_pct, size_1r, rr_sc = build_risk_from_entry(raw_entry, min(ema20 * 0.95, raw_entry - 1.5 * atr), True)
                if stop_pct <= 18.0:
                    s_st = 4 if (ema50 and p > ema50) else 3
                    s_mo = 5 if rs7 >= 12 else 4
                    s_cr = 5 if fr_ann <= -25 else 4
                    s_lbl = "逆势负费率逼空" if fr_ann <= -15.0 else "逆势多头领涨"
                    q_sum = (
                        f"7天逆势跑赢大饼 {rs7:+.1f}%，年化费率 {fr_ann:+.1f}% 空头显著拥挤。"
                        if fr_ann <= -15.0
                        else f"大盘承压下日线维持多头排列，7天逆势跑赢大饼 {rs7:+.1f}%。"
                    )
                    if p > ema20 * 1.01:
                        rule_txt = f"等待回踩 20 日均线 {fmt_rule_px(entry_px)} 附近低吸（突破 {fmt_rule_px(d20h)} 右侧加仓）"
                    elif p >= ema20:
                        rule_txt = f"守稳 20 日均线 {fmt_rule_px(entry_px)} 附近低吸（突破 {fmt_rule_px(d20h)} 加仓）"
                    else:
                        rule_txt = f"现价略低于 20 日均线（{fmt_rule_px(ema20)}），于 {fmt_rule_px(entry_px)} 收复企稳低吸（突破 {fmt_rule_px(d20h)} 加仓）"
                    coin_actions.append({
                        "direction": "LONG", "setup_type": "rs_leader_squeeze", "setup_label": s_lbl,
                        "trigger_price": entry_px, "trigger_rule": rule_txt,
                        "stop_price": stop_px, "stop_rule": f"日线收盘跌破 {fmt_rule_px(stop_px)} 离场（-{stop_pct}%）",
                        "stop_dist_pct": stop_pct, "notional_1r_pct": size_1r,
                        "score": {"structure": s_st, "momentum": s_mo, "crowding": s_cr, "risk_reward": rr_sc, "total": s_st + s_mo + s_cr + rr_sc},
                        "quant_summary": q_sum,
                    })

            # B1: SHORT 20D 支撑破位（多头趋势期不做逆势空；偏离均线已超 -1.8x ATR 时禁追地板空单）
            if not is_bull_regime and ((c1d <= p20l and p <= p20l * 1.01) or p < d20l * 0.999) and fr_ann >= min_short_fr and dist_atr >= -1.8 and (vr >= 1.15 or (m["chg_24h"] or 0) <= -4.0):
                brk_lvl = round_sig(p20l if c1d <= p20l else d20l, 5)
                raw_entry = brk_lvl if p < brk_lvl else p
                sc_px = min(d10h, ema20 + 0.5 * atr)
                if sc_px <= raw_entry * 1.025:
                    sc_px = raw_entry + 1.8 * atr
                entry_px, stop_px, stop_pct, size_1r, rr_sc = build_risk_from_entry(raw_entry, sc_px, False)
                if stop_pct <= 18.0:
                    vol_word = f"放量跌破20日低点（量能比 {vr:.2f}x）" if vr >= 1.25 else f"日线跌破20日低点（昨日量比 {vr:.2f}x，盘中转弱）"
                    s_st = 5 if (ema50 and ema20 < ema50 and c1d < p20l) else 4
                    s_mo = 5 if (vr >= 1.5 and rs14 <= -6) else 4
                    s_cr = 5 if fr_ann >= 5 else 4
                    coin_actions.append({
                        "direction": "SHORT", "setup_type": "breakdown_20d", "setup_label": "日线20日支撑破位",
                        "trigger_price": entry_px, "trigger_rule": f"等待反抽破位口 {fmt_rule_px(entry_px)} 受阻做空（勿低位追空）",
                        "stop_price": stop_px, "stop_rule": f"日线收盘站回 {fmt_rule_px(stop_px)} 止损（+{stop_pct}%）",
                        "stop_dist_pct": stop_pct, "notional_1r_pct": size_1r,
                        "score": {"structure": s_st, "momentum": s_mo, "crowding": s_cr, "risk_reward": rr_sc, "total": s_st + s_mo + s_cr + rr_sc},
                        "quant_summary": f"{vol_word}，14天跑输大饼 {rs14:+.1f}%。",
                    })

            # B2: SHORT 空头排列反抽 EMA20（多头趋势期仅在 rs14 <= -12% 极弱标的上保留）
            if (not is_bull_regime or rs14 <= -12.0) and ema50 and ema20 < ema50 and not m["ema20_rising"] and bn_lo <= dist20 <= bn_hi and p < ema50 * 0.995 and rs14 <= -3.0 and fr_ann >= -15.0:
                entry_px, stop_px, stop_pct, size_1r, rr_sc = build_risk_from_entry(
                    ema20 if p <= ema20 else p, max(ema50 * 1.01, ema20 + 1.5 * atr), False
                )
                rule_txt = (
                    f"等待反抽 20 日均线 {fmt_rule_px(entry_px)} 滞涨布空"
                    if p <= ema20
                    else f"现价已反抽至 20 日均线（{fmt_rule_px(ema20)}）上方，于 {fmt_rule_px(entry_px)} 滞涨收上影线布空"
                )
                s_st = 5 if (m.get("ema200") and ema50 < m["ema200"]) else 4
                s_mo = 5 if rs14 <= -10 else 4
                s_cr = 5 if fr_ann >= 5 else 4
                coin_actions.append({
                    "direction": "SHORT", "setup_type": "bounce_ema20_short", "setup_label": "空头反抽20日线受阻",
                    "trigger_price": entry_px, "trigger_rule": rule_txt,
                    "stop_price": stop_px, "stop_rule": f"日线收盘站回 {fmt_rule_px(stop_px)} 止损（+{stop_pct}%）",
                    "stop_dist_pct": stop_pct, "notional_1r_pct": size_1r,
                    "score": {"structure": s_st, "momentum": s_mo, "crowding": s_cr, "risk_reward": rr_sc, "total": s_st + s_mo + s_cr + rr_sc},
                    "quant_summary": f"标准空头趋势反抽至20日均线附近（{dist20:+.1f}%），14天跑输大饼 {rs14:+.1f}%。",
                })

            # C: WATCH 真正窄幅收敛（同时要求 BB 带宽低分位 + 20 日高低振幅 <= sq_rng_max，且独立池不挤占可执行单名额）
            if not coin_actions and m["bb_width_pctile"] is not None and m["bb_width_pctile"] <= sq_max and rng20 <= sq_rng_max and m["perp_vol_24h_usd"] >= 30_000_000:
                entry_px, stop_px, stop_pct, size_1r, rr_sc = build_risk_from_entry(d20h, ema20, True)
                watch_stop_rule = (
                    f"上破后以 20 日均线 {fmt_rule_px(stop_px)} 为防守（-{stop_pct}%）"
                    if stop_px == round_sig(ema20, 5)
                    else f"上破后以 {fmt_rule_px(stop_px)} 为防守（1.8x ATR，-{stop_pct}%）"
                )
                coin_watch.append({
                    "direction": "WATCH", "setup_type": "volatility_squeeze", "setup_label": "日线窄幅收敛待变盘",
                    "trigger_price": entry_px, "trigger_rule": f"上破 {fmt_rule_px(d20h)} 做多 / 下破 {fmt_rule_px(d20l)} 做空",
                    "stop_price": stop_px, "stop_rule": watch_stop_rule,
                    "stop_dist_pct": stop_pct, "notional_1r_pct": size_1r,
                    "score": {"structure": 4, "momentum": 3, "crowding": 4, "risk_reward": rr_sc, "total": 11 + rr_sc},
                    "quant_summary": f"近20日高低振幅仅 {rng20:.1f}%（布林带宽处60日 {m['bb_width_pctile']}% 分位），蓄势待突破。",
                })

            def _attach(best):
                best.update({
                    "id": f"{sym.lower()}-{best['setup_type']}-{today_str.replace('-', '')}",
                    "symbol": sym, "in_watchlist": m["in_watchlist"],
                    "price_usd": p, "close_1d": c1d, "chg_24h": m["chg_24h"], "rs_14d": m["rs_14d"],
                    "ema20": ema20, "ema50": ema50,
                    "prev_20d_high": p20h, "prev_20d_low": p20l,
                    "donchian_20d_high": d20h, "donchian_20d_low": d20l,
                    "range_20d_pct": m["range_20d_pct"], "bb_width_pctile": m["bb_width_pctile"], "trend_label": m["trend_label"],
                    "atr14": atr, "atr_pct": m["atr_pct"], "vol_ratio_1d": m["vol_ratio_1d"],
                    "perp_vol_24h_usd": m["perp_vol_24h_usd"], "oi_usd": m["oi_usd"],
                    "oi_change_24h_pct": m["oi_change_24h_pct"], "funding_ann_pct": m["funding_ann_pct"],
                })
                return best

            if coin_actions:
                coin_actions.sort(key=lambda s: s["score"]["total"], reverse=True)
                action_pool.append(_attach(coin_actions[0]))
            elif coin_watch:
                watch_pool.append(_attach(coin_watch[0]))

        sort_key = lambda x: (x["score"]["total"], 1 if x["in_watchlist"] else 0, math.log10(max(1.0, x["perp_vol_24h_usd"])))
        action_pool.sort(key=sort_key, reverse=True)
        watch_pool.sort(key=lambda x: (-(x.get("range_20d_pct") or 99), math.log10(max(1.0, x["perp_vol_24h_usd"]))), reverse=True)
        return action_pool[:max_act] + watch_pool[:max_wat]

    def evaluate_regime(self, enriched, fgi, stable_delta):
        by_sym = {m["symbol"]: m for m in enriched}
        btc, eth = by_sym.get("BTC", {}), by_sym.get("ETH", {})
        total = len(enriched) or 1
        above20 = sum(1 for m in enriched if m.get("ema20") and m["price_usd"] > m["ema20"])
        above50 = sum(1 for m in enriched if m.get("ema50") and m["price_usd"] > m["ema50"])
        pct20 = round(above20 / total * 100.0, 1)
        pct50 = round(above50 / total * 100.0, 1)

        fundings = [m["funding_ann_pct"] for m in enriched if m.get("funding_ann_pct") is not None]
        med_fr = round(statistics.median(fundings), 2) if fundings else None
        total_oi = round(sum(m.get("oi_usd") or 0 for m in enriched), 0)

        bp, be20, be50, be200 = btc.get("price_usd") or 0, btc.get("ema20") or 0, btc.get("ema50") or 0, btc.get("ema200") or 0
        if bp > be20 > be50 and (not be200 or be50 > be200):
            s_btc = 5 if bp >= (btc.get("prev_20d_high") or bp + 1) else 4
        elif bp > be50:
            s_btc = 3
        elif bp < be20 < be50:
            s_btc = 1 if bp <= (btc.get("prev_20d_low") or 0) else 2
        else:
            s_btc = 2 if bp < be50 else 3

        s_br = 5 if (pct20 >= 65 and (stable_delta or 0) >= 0) else (4 if pct20 >= 50 else (3 if pct20 >= 32 else (2 if pct20 >= 18 else 1)))
        s_sent = 4 if (med_fr is not None and -10 <= med_fr <= 25 and (fgi or 50) >= 45) else (2 if (fgi or 50) < 25 else 3)
        s_macro = 3
        tot = s_btc + s_br + s_sent + s_macro
        code, label, posture = classify_regime(tot)

        return {
            "regime_code": code,
            "regime_label": label,
            "posture": posture,
            "scores": {"btc_trend": s_btc, "breadth": s_br, "sentiment": s_sent, "macro": s_macro, "total": tot},
            "breadth": {"universe_count": total, "above_ema20": above20, "pct_above_ema20": pct20, "pct_above_ema50": pct50},
            "derivatives_overview": {"universe_total_oi_usd": total_oi, "median_funding_ann_pct": med_fr},
            "eth_summary": {
                "price_usd": eth.get("price_usd"), "chg_24h": eth.get("chg_24h"),
                "ema20": eth.get("ema20"), "ema50": eth.get("ema50"),
                "trend_label": eth.get("trend_label"),
                "eth_btc_ratio": round(eth["price_usd"] / bp, 5) if (eth.get("price_usd") and bp) else None,
            },
        }

    def get_stablecoins(self):
        d = fetch_json("https://stablecoins.llama.fi/stablecoins?includePrices=true")
        if not d or not d.get("peggedAssets"):
            self.sources["stablecoins"] = None
            return None
        total = sum(
            ((a.get("circulating") or {}).get("peggedUSD") or 0)
            for a in d["peggedAssets"] if a.get("pegType") == "peggedUSD"
        )
        self.sources["stablecoins"] = "defillama" if total > 0 else None
        return total if total > 0 else None

    def get_fgi(self):
        d = fetch_json("https://api.alternative.me/fng/")
        try:
            row = (d or {}).get("data", [])[0]
            self.sources["fear_greed"] = "alternative.me"
            return int(row["value"]), row.get("value_classification")
        except Exception:
            self.sources["fear_greed"] = None
            return None, None

    def prev_events(self, today):
        out = []
        for e in self.prev.get("events", []):
            e = dict(e)
            if e.get("status") in ("passed", "cancelled"):
                continue
            try:
                d = datetime.strptime(e["date"], "%Y-%m-%d").date()
                e["days_away"] = (d - today).days
                if e["days_away"] >= 0:
                    e["status"] = "upcoming"
                    out.append(e)
            except Exception:
                pass
        return out

    def run(self, session="daily", mark_pipeline=True):
        t0 = time.time()
        now = datetime.now(TZ)
        today = now.date()
        today_str = today.strftime("%Y-%m-%d")
        housekeeping(now.timestamp())
        pipe_path = ROOT / "data/.pipeline-run.json"
        if mark_pipeline:
            with open(pipe_path, "w") as pf:
                json.dump({"pid": os.getpid(), "date": today_str, "started_ts": int(t0), "stage": "collect"}, pf)
        print(f"[collect 2.1] {now.isoformat(timespec='seconds')} start", flush=True)

        whitelist = self.get_crypto_whitelist()
        selected, all_coins = self.fetch_perp_universe(whitelist)

        # 失败熔断门禁 1: 两个核心合约交易所均失败时立即清除旧暂存文件并终止，防止下游误发旧数据
        if not self.sources.get("okx_swap") and not self.sources.get("hyperliquid"):
            (ROOT / "data/collected.json").unlink(missing_ok=True)
            pipe_path.unlink(missing_ok=True)
            print("[collect 2.1] FATAL: both OKX Swap and Hyperliquid APIs failed; aborting.", file=sys.stderr)
            return 2

        snap_24h, snap_4h = self.update_and_calc_oi_deltas(all_coins, now.timestamp(), persist=True)
        enriched = self.enrich_universe_metrics(selected, snap_24h, snap_4h)

        by_sym = {m["symbol"]: m for m in enriched}
        btc_m = by_sym.get("BTC", {})

        # 失败熔断门禁 2: 有效日线合约池不足或 BTC 核心数据缺失时立即清除旧暂存文件并终止
        if len(enriched) < MIN_VALID_PERPS or not btc_m.get("price_usd") or not btc_m.get("ema20"):
            (ROOT / "data/collected.json").unlink(missing_ok=True)
            pipe_path.unlink(missing_ok=True)
            print(
                f"[collect 2.1] FATAL: insufficient valid perps ({len(enriched)} < {MIN_VALID_PERPS}) or missing BTC daily candles; aborting.",
                file=sys.stderr,
            )
            return 2

        stable_total = self.get_stablecoins()
        fgi, fgi_label = self.get_fgi()
        prev_stable = ((self.prev.get("market_context") or {}).get("global") or {}).get("stablecoin_total_supply")
        stable_delta = round((stable_total - prev_stable) / prev_stable * 100.0, 2) if (stable_total and prev_stable) else None

        regime = self.evaluate_regime(enriched, fgi, stable_delta)
        setups = self.scan_setups(enriched, today_str, regime["regime_code"])

        max_atr = self.cfg.get("universe", {}).get("max_atr_pct_filter", 20.0)
        min_oi = self.cfg.get("universe", {}).get("min_open_interest_usd", 10_000_000)
        liquid = [
            m for m in enriched
            if m["symbol"] != "BTC" and (m.get("oi_usd") or 0) >= min_oi and (m.get("atr_pct") or 0) <= max_atr and m.get("rs_14d") is not None
        ]
        if len(liquid) < 8:
            liquid = [m for m in enriched if m["symbol"] != "BTC" and m.get("rs_14d") is not None]

        bull_radar = sorted(liquid, key=lambda x: x["rs_14d"], reverse=True)[:6]
        bear_radar = sorted(liquid, key=lambda x: x["rs_14d"])[:6]
        neg_funding = sorted([m for m in liquid if m.get("funding_ann_pct") is not None], key=lambda x: x["funding_ann_pct"])[:5]

        watch_order = [str(s).upper() for s in self.cfg.get("watchlist", [])]
        watchlist_rows = [by_sym[s] for s in watch_order if s in by_sym]

        def slim(m):
            keys = (
                "symbol", "price_usd", "close_1d", "chg_24h", "chg_7d", "rs_7d", "rs_14d",
                "ema20", "ema50", "dist_ema20_pct", "dist_ema20_atr",
                "prev_20d_high", "prev_20d_low", "donchian_20d_high", "donchian_20d_low",
                "range_20d_pct", "pos_in_20d_pct", "atr14", "atr_pct", "vol_ratio_1d",
                "bb_width_pctile", "trend_state", "trend_label", "perp_vol_24h_usd", "oi_usd",
                "oi_change_24h_pct", "funding_ann_pct",
            )
            return {k: m.get(k) for k in keys}

        collected = {
            "schema_version": "2.1-slim",
            "collected_at": now.isoformat(timespec="seconds"),
            "collected_ts": int(time.time()),
            "date": today_str,
            "session": session,
            "regime": regime,
            "setups_candidates": setups,
            "watchlist_rows": [slim(m) for m in watchlist_rows],
            "bull_radar": [slim(m) for m in bull_radar],
            "bear_radar": [slim(m) for m in bear_radar],
            "neg_funding_leaders": [slim(m) for m in neg_funding],
            "btc": {
                "price_usd": btc_m.get("price_usd"),
                "close_1d": btc_m.get("close_1d"),
                "last_closed_date": btc_m.get("last_closed_date"),
                "price_change_24h": btc_m.get("chg_24h"),
                "price_change_7d": btc_m.get("chg_7d"),
                "ema20": btc_m.get("ema20"),
                "ema50": btc_m.get("ema50"),
                "ema200": btc_m.get("ema200"),
                "atr14": btc_m.get("atr14"),
                "atr_pct": btc_m.get("atr_pct"),
                "prev_20d_high": btc_m.get("prev_20d_high"),
                "prev_20d_low": btc_m.get("prev_20d_low"),
                "donchian_20d_high": btc_m.get("donchian_20d_high"),
                "donchian_20d_low": btc_m.get("donchian_20d_low"),
                "trend_state": btc_m.get("trend_state"),
                "trend_label": btc_m.get("trend_label"),
                "fear_greed": fgi,
                "fear_greed_label": fgi_label,
                "funding_ann_pct": btc_m.get("funding_ann_pct"),
                "open_interest": btc_m.get("oi_usd"),
                "chart_60d": btc_m.get("chart_60d") or {},
            },
            "eth": regime["eth_summary"],
            "global": {
                "stablecoin_total_supply": stable_total,
                "stablecoin_supply_change_pct": stable_delta,
            },
            "previous": {
                "date": (self.prev.get("timestamp") or "")[:10] or None,
                "events": self.prev_events(today),
            },
            "_sources": self.sources,
        }

        out_path = ROOT / "data/collected.json"
        with open(out_path, "w") as f:
            json.dump(collected, f, ensure_ascii=False, indent=2)
        if mark_pipeline:
            with open(pipe_path, "w") as pf:
                json.dump({"pid": os.getpid(), "date": today_str, "started_ts": int(t0), "collected_ts": int(time.time()), "stage": "step2_pending"}, pf)

        missing = [k for k, v in self.sources.items() if v is None]
        print(
            f"[collect 2.1] done in {time.time() - t0:.1f}s -> perps={len(enriched)} "
            f"setups={len(setups)} watchlist={len(watchlist_rows)} missing={missing or '无'}",
            flush=True,
        )
        return 0


if __name__ == "__main__":
    sys.exit(TrendCollector().run(sys.argv[1] if len(sys.argv) > 1 else "daily"))
