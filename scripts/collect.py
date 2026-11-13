#!/usr/bin/env python3
"""crypto-monitor 2.0 数据采集与日线合约趋势量化引擎（确定性环节）。

定位：服务「低倍永续合约 · 日线级别趋势交易」。
职责：
1. 拉取 OKX Swap + Hyperliquid 全市场永续合约实时快照（价格/24h成交额/OI/资金费率），构建 Top 高流动性合约池 + 核心自选池
2. 并发拉取各合约 200 根 UTC 日线 K 线（00:00 UTC = 08:00 UTC+8 收盘对齐），严格区分「已收盘日线」与「盘中实时价」
3. 精确计算 EMA20/50/200、20D/55D 唐奇安通道高低点、Wilder ATR(14)、20D 量能比、布林带宽压缩分位、相对 BTC 强弱（RS 7d/14d/30d）
4. 持久化 OI 历史快照（data/oi_history.json），计算 4h / 24h OI 变化率
5. 运行日线趋势剧本扫描器（20D突破/破位、EMA20顺势回踩/反抽、逆势抗跌逼空、波动率极度压缩），生成客观触发位、结构止损位与 1% 风险仓位标尺
6. 采集宏观与链上背景（CoinGecko 板块轮动[已修复字段名] / BTC 主导率、DeFiLlama 稳定币与链 TVL、CoinMetrics MVRV、Alternative.me FGI）
7. 输出 data/collected.json 供后续定性排雷与报告渲染使用

用法: python3 scripts/collect.py [daily]
"""

import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

OKX_BASE = "https://www.okx.com"
HL_INFO = "https://api.hyperliquid.xyz/info"
CG_BASE = "https://api.coingecko.com/api/v3"

CG_CALL_GAP = 3.0
RETRY_WAIT_429 = 30
FRESHNESS_FIELDS = ["mvrv_ratio", "funding_rate", "open_interest", "fear_greed", "dominance"]


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fetch_json(url, headers=None, body=None, timeout=30, retries_on_429=1):
    hdrs = {"User-Agent": "crypto-trend-radar/2.0"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body is not None else None

    for attempt in range(1 + retries_on_429):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries_on_429:
                print(f"  429 rate limited, wait {RETRY_WAIT_429}s: {url[:80]}", flush=True)
                time.sleep(RETRY_WAIT_429)
                continue
            print(f"  HTTP {e.code}: {url[:80]}", flush=True)
            return None
        except Exception as e:
            print(f"  fetch failed ({e}): {url[:80]}", flush=True)
            return None
    return None


# ---------- 技术指标纯函数（严格对应 TradingView / 标准日线口径） ----------

def calc_ema_series(values, span):
    """标准指数移动平均序列（首值用前 span 根 SMA 初始化）。长度不足返回全 None。"""
    n = len(values)
    if n < span:
        return [None] * n
    out = [None] * (span - 1)
    sma = sum(values[:span]) / span
    out.append(sma)
    k = 2.0 / (span + 1.0)
    prev = sma
    for v in values[span:]:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def calc_wilder_atr(highs, lows, closes, period=14):
    """Wilder 平滑 ATR(14)，返回最新值；不足 period+1 根返回 None。"""
    n = len(closes)
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_bb_width_pctile(closes, period=20, lookback=60):
    """计算最新 20D 布林带宽度 (4*std/sma) 在过去 lookback 天内的分位数 (0~100)。"""
    if len(closes) < period + 10:
        return None
    widths = []
    start = max(period, len(closes) - lookback)
    for idx in range(start, len(closes) + 1):
        win = closes[idx - period:idx]
        mean = sum(win) / period
        if mean <= 0:
            continue
        var = sum((x - mean) ** 2 for x in win) / period
        widths.append((4.0 * math.sqrt(var)) / mean * 100.0)
    if len(widths) < 5:
        return None
    cur = widths[-1]
    le_cnt = sum(1 for w in widths if w <= cur)
    return round(le_cnt / len(widths) * 100.0, 1)


def pct_diff(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0


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


# ---------- 核心采集引擎 ----------

class TrendCollector:
    def __init__(self):
        self.scan_cfg = load_json(ROOT / "config/scan-config.json", {})
        self.output_cfg = load_json(ROOT / "config/output.json", {})
        self.watchlist_cfg = load_json(ROOT / "config/watchlist.json", {})
        self.prev = load_json(ROOT / "data/latest.json")
        self.sources = {}
        self._cg_key = (self.output_cfg.get("api_keys") or {}).get("coingecko_demo") or ""
        self._cg_headers = {"x-cg-demo-api-key": self._cg_key} if self._cg_key else {}
        self._last_cg = 0.0

    def cg(self, path):
        gap = time.time() - self._last_cg
        if gap < CG_CALL_GAP:
            time.sleep(CG_CALL_GAP - gap)
        self._last_cg = time.time()
        return fetch_json(CG_BASE + path, headers=self._cg_headers)

    # ---------- 1. 合约全市场快照（OKX Swap + Hyperliquid） ----------

    def get_crypto_whitelist_symbols(self):
        """从 CoinGecko 前 N 页市值榜提取纯正加密货币 Symbol 白名单，自动剔除交易所上的美股/ETF/贵金属衍生品（如 GOOGL/AMD/MSTR/SOXS/XAU）。"""
        pages = self.scan_cfg.get("perp_universe", {}).get("coingecko_crypto_top_pages", 2)
        syms = set()
        for page in range(1, pages + 1):
            rows = self.cg(
                f"/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"
            )
            for r in rows or []:
                s = (r.get("symbol") or "").upper()
                if s:
                    syms.add(s)
        self.sources["coingecko_crypto_universe"] = "coingecko" if syms else None
        return syms

    def fetch_perp_universe(self, crypto_whitelist=None):
        uni_cfg = self.scan_cfg.get("perp_universe", {})
        exclude = {s.upper() for s in uni_cfg.get("exclude_bases", [])}
        min_vol = uni_cfg.get("min_perp_vol_24h_usd", 12_000_000)
        min_oi = uni_cfg.get("min_open_interest_usd", 5_000_000)
        top_n = uni_cfg.get("top_n_perps", 75)
        watch_syms = [str(s).upper() for s in (self.watchlist_cfg.get("coins") or [])]

        # 1a. OKX Swap tickers & OI
        okx_t_resp = fetch_json(f"{OKX_BASE}/api/v5/market/tickers?instType=SWAP")
        okx_oi_resp = fetch_json(f"{OKX_BASE}/api/v5/public/open-interest?instType=SWAP")
        okx_tickers = (okx_t_resp or {}).get("data") or []
        okx_ois = (okx_oi_resp or {}).get("data") or []
        self.sources["okx_swap_markets"] = "okx_v5" if okx_tickers else None
        self.sources["okx_swap_oi"] = "okx_v5" if okx_ois else None

        oi_by_inst = {}
        for item in okx_ois:
            iid = item.get("instId")
            try:
                oi_by_inst[iid] = float(item.get("oiUsd") or 0)
            except (TypeError, ValueError):
                pass

        coins = {}
        raw_okx_bases = set()
        for t in okx_tickers:
            iid = t.get("instId") or ""
            if not iid.endswith("-USDT-SWAP"):
                continue
            raw_okx_bases.add(iid[:-10].upper())

        for t in okx_tickers:
            iid = t.get("instId") or ""
            if not iid.endswith("-USDT-SWAP"):
                continue
            raw_base = iid[:-10].upper()
            scale = 1.0
            sym = raw_base
            if raw_base.startswith("1000") and len(raw_base) > 4:
                stripped = raw_base[4:]
                if stripped in raw_okx_bases:
                    continue
                sym = stripped
                scale = 1000.0
            if sym in exclude:
                continue
            try:
                last = float(t["last"]) / scale
                open24 = float(t["open24h"]) / scale if t.get("open24h") else None
                vol_ccy = float(t.get("volCcy24h") or 0) * scale
                vol_usd = vol_ccy * last
                oi_usd = oi_by_inst.get(iid, 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            if last <= 0:
                continue
            chg_24h = pct_diff(last, open24) if open24 else None
            coins[sym] = {
                "symbol": sym,
                "price_usd": last,
                "chg_24h": chg_24h,
                "okx_inst_id": iid,
                "okx_scale": scale,
                "okx_vol_usd": vol_usd,
                "okx_oi_usd": oi_usd,
                "hl_coin": None,
                "hl_scale": 1.0,
                "hl_vol_usd": 0.0,
                "hl_oi_usd": 0.0,
                "hl_funding_8h_pct": None,
                "okx_funding_8h_pct": None,
            }

        # 1b. Hyperliquid metaAndAssetCtxs
        hl_resp = fetch_json(HL_INFO, body={"type": "metaAndAssetCtxs"})
        self.sources["hyperliquid_perps"] = "hyperliquid_info" if hl_resp else None
        if isinstance(hl_resp, list) and len(hl_resp) >= 2:
            universe = (hl_resp[0] or {}).get("universe") or []
            ctxs = hl_resp[1] or []
            for u, ctx in zip(universe, ctxs):
                if u.get("isDelisted"):
                    continue
                name = u.get("name") or ""
                if not name:
                    continue
                scale = 1.0
                sym = name.upper()
                if name.startswith("k") and len(name) > 1 and name[1:].isupper():
                    sym = name[1:].upper()
                    scale = 1000.0
                if sym in exclude:
                    continue
                try:
                    mark_raw = float(ctx.get("markPx") or 0)
                    prev_raw = float(ctx.get("prevDayPx") or 0)
                    vol_usd = float(ctx.get("dayNtlVlm") or 0)
                    oi_coins = float(ctx.get("openInterest") or 0)
                    oi_usd = oi_coins * mark_raw
                    fr_1h = float(ctx.get("funding")) if ctx.get("funding") is not None else None
                except (TypeError, ValueError):
                    continue
                if mark_raw <= 0:
                    continue
                price = mark_raw / scale
                prev_px = prev_raw / scale if prev_raw > 0 else None
                fr_8h_pct = (fr_1h * 8.0 * 100.0) if fr_1h is not None else None

                if sym in coins:
                    c = coins[sym]
                    c["hl_coin"] = name
                    c["hl_scale"] = scale
                    c["hl_vol_usd"] = vol_usd
                    c["hl_oi_usd"] = oi_usd
                    c["hl_funding_8h_pct"] = fr_8h_pct
                else:
                    coins[sym] = {
                        "symbol": sym,
                        "price_usd": price,
                        "chg_24h": pct_diff(price, prev_px) if prev_px else None,
                        "okx_inst_id": None,
                        "okx_scale": 1.0,
                        "okx_vol_usd": 0.0,
                        "okx_oi_usd": 0.0,
                        "hl_coin": name,
                        "hl_scale": scale,
                        "hl_vol_usd": vol_usd,
                        "hl_oi_usd": oi_usd,
                        "hl_funding_8h_pct": fr_8h_pct,
                        "okx_funding_8h_pct": None,
                    }

        # 汇总成交额与 OI，过滤主流高流动性纯加密合约池（自动剔除美股/ETF/大宗商品合约）
        eligible = []
        for sym, c in coins.items():
            c["perp_vol_24h_usd"] = c["okx_vol_usd"] + c["hl_vol_usd"]
            c["oi_usd"] = c["okx_oi_usd"] + c["hl_oi_usd"]
            c["in_watchlist"] = sym in watch_syms
            if crypto_whitelist and sym not in crypto_whitelist and sym not in watch_syms:
                continue
            if sym in watch_syms or (c["perp_vol_24h_usd"] >= min_vol and c["oi_usd"] >= min_oi):
                eligible.append(c)

        # 按 (是否在自选池置顶保底 + 综合流动性 0.6*Vol + 0.4*OI) 取前 top_n + 全部自选
        eligible.sort(key=lambda x: 0.6 * x["perp_vol_24h_usd"] + 0.4 * x["oi_usd"], reverse=True)
        selected_map = {}
        for c in eligible[:top_n]:
            selected_map[c["symbol"]] = c
        for sym in watch_syms:
            if sym in coins and sym not in selected_map:
                selected_map[sym] = coins[sym]
        if "BTC" in coins:
            selected_map["BTC"] = coins["BTC"]
        if "ETH" in coins:
            selected_map["ETH"] = coins["ETH"]

        return list(selected_map.values()), coins

    # ---------- 2. OI 历史快照持久化与 4h/24h 变化率 ----------

    def update_and_calc_oi_deltas(self, all_coins_map, now_ts):
        oi_path = ROOT / "data/oi_history.json"
        hist = load_json(oi_path, [])
        if not isinstance(hist, list):
            hist = []

        # 只保留最近 72 小时有效非空快照，且若距离上一条 < 20 分钟则不重复追加
        cutoff = now_ts - 72 * 3600
        hist = [
            h for h in hist
            if isinstance(h, dict) and (h.get("ts") or 0) >= cutoff and bool(h.get("oi"))
        ]

        cur_oi_snap = {
            sym: round(c["oi_usd"], 2)
            for sym, c in all_coins_map.items()
            if (c.get("oi_usd") or 0) >= 1_000_000
        }

        def find_snap(target_age_sec, min_age_sec, max_age_sec):
            best = None
            best_diff = 1e18
            for h in hist:
                age = now_ts - (h.get("ts") or 0)
                if min_age_sec <= age <= max_age_sec:
                    d = abs(age - target_age_sec)
                    if d < best_diff:
                        best_diff = d
                        best = h.get("oi") or {}
            return best

        snap_24h = find_snap(24 * 3600, 14 * 3600, 36 * 3600)
        snap_4h = find_snap(4 * 3600, 1.5 * 3600, 8 * 3600)

        if cur_oi_snap and (not hist or (now_ts - hist[-1].get("ts", 0)) >= 1200):
            hist.append({"ts": int(now_ts), "oi": cur_oi_snap})
            with open(oi_path, "w") as f:
                json.dump(hist, f, separators=(",", ":"))

        return snap_24h, snap_4h

    # ---------- 3. 并发拉取日线 K 线与 OKX 资金费率 ----------

    def _fetch_coin_detail(self, coin, candle_days, now_ms):
        """单币种详情：日线 K 线 (1Dutc) + OKX 实时 8h 资金费率。"""
        closed_bars = []  # [{"ts": ms, "date": "YYYY-MM-DD", "o","h","l","c","qv"}]
        forming_bar = None
        candle_src = None

        if coin.get("okx_inst_id"):
            iid = coin["okx_inst_id"]
            scale = coin.get("okx_scale", 1.0)
            resp = fetch_json(
                f"{OKX_BASE}/api/v5/market/candles?instId={iid}&bar=1Dutc&limit={candle_days}"
            )
            rows = (resp or {}).get("data") or []
            if rows:
                candle_src = "okx_1Dutc"
                for r in reversed(rows):
                    try:
                        ts = int(r[0])
                        dt_str = datetime.fromtimestamp(ts / 1000.0, timezone.utc).strftime("%Y-%m-%d")
                        bar = {
                            "ts": ts,
                            "date": dt_str,
                            "o": float(r[1]) / scale,
                            "h": float(r[2]) / scale,
                            "l": float(r[3]) / scale,
                            "c": float(r[4]) / scale,
                            "qv": float(r[7]),
                        }
                        if str(r[8]) == "1":
                            closed_bars.append(bar)
                        else:
                            forming_bar = bar
                    except (IndexError, TypeError, ValueError):
                        continue

            fr_resp = fetch_json(f"{OKX_BASE}/api/v5/public/funding-rate?instId={iid}")
            fr_data = (fr_resp or {}).get("data") or []
            if fr_data and fr_data[0].get("fundingRate") not in (None, ""):
                try:
                    coin["okx_funding_8h_pct"] = float(fr_data[0]["fundingRate"]) * 100.0
                except (TypeError, ValueError):
                    pass

        # 若无 OKX K 线（如 HYPE 等 Hyperliquid 原生币），走 Hyperliquid candleSnapshot
        if not closed_bars and coin.get("hl_coin"):
            hl_name = coin["hl_coin"]
            scale = coin.get("hl_scale", 1.0)
            start_ms = now_ms - (candle_days + 5) * 86400 * 1000
            resp = fetch_json(
                HL_INFO,
                body={
                    "type": "candleSnapshot",
                    "req": {"coin": hl_name, "interval": "1d", "startTime": start_ms, "endTime": now_ms},
                },
            )
            if isinstance(resp, list) and resp:
                candle_src = "hyperliquid_1d"
                resp_sorted = sorted(resp, key=lambda x: int(x.get("t", 0)))
                for r in resp_sorted:
                    try:
                        t_open = int(r["t"])
                        t_close = int(r["T"])
                        c_raw = float(r["c"])
                        v_raw = float(r["v"])
                        dt_str = datetime.fromtimestamp(t_open / 1000.0, timezone.utc).strftime("%Y-%m-%d")
                        bar = {
                            "ts": t_open,
                            "date": dt_str,
                            "o": float(r["o"]) / scale,
                            "h": float(r["h"]) / scale,
                            "l": float(r["l"]) / scale,
                            "c": c_raw / scale,
                            "qv": v_raw * c_raw,
                        }
                        if t_close < now_ms:
                            closed_bars.append(bar)
                        else:
                            forming_bar = bar
                    except (KeyError, TypeError, ValueError):
                        continue

        return coin["symbol"], closed_bars, forming_bar, candle_src

    def enrich_universe_metrics(self, selected, snap_24h, snap_4h):
        candle_days = self.scan_cfg.get("perp_universe", {}).get("candle_days", 200)
        now_ms = int(time.time() * 1000)

        candle_map = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}
            for idx, coin in enumerate(selected):
                if idx > 0 and idx % 6 == 0:
                    time.sleep(0.25)
                futures[pool.submit(self._fetch_coin_detail, coin, candle_days, now_ms)] = coin["symbol"]
            for fut in as_completed(futures):
                sym, closed_bars, forming_bar, src = fut.result()
                candle_map[sym] = (closed_bars, forming_bar, src)

        self.sources["daily_candles_1d"] = "okx_1Dutc+hyperliquid_1d" if candle_map else None

        # 先算 BTC 的 7d/14d/30d 收益率用于计算全市场相对强弱 RS
        btc_bars = candle_map.get("BTC", ([], None, None))[0]
        btc_price = next((c["price_usd"] for c in selected if c["symbol"] == "BTC"), None)

        def calc_horizon_ret(cur_p, bars, days):
            if cur_p is None or len(bars) < days:
                return None
            ref = bars[-days]["c"]
            return pct_diff(cur_p, ref)

        btc_ret_7d = calc_horizon_ret(btc_price, btc_bars, 7)
        btc_ret_14d = calc_horizon_ret(btc_price, btc_bars, 14)
        btc_ret_30d = calc_horizon_ret(btc_price, btc_bars, 30)

        enriched = []
        for c in selected:
            sym = c["symbol"]
            closed, forming, c_src = candle_map.get(sym, ([], None, None))
            if len(closed) < 22:
                continue

            closes = [b["c"] for b in closed]
            highs = [b["h"] for b in closed]
            lows = [b["l"] for b in closed]
            qvols = [b["qv"] for b in closed]

            ema20_s = calc_ema_series(closes, 20)
            ema50_s = calc_ema_series(closes, 50)
            ema200_s = calc_ema_series(closes, 200)

            ema20 = ema20_s[-1]
            ema20_prev3 = ema20_s[-4] if len(ema20_s) >= 4 and ema20_s[-4] is not None else ema20
            ema50 = ema50_s[-1]
            ema200 = ema200_s[-1]

            atr14 = calc_wilder_atr(highs, lows, closes, 14)
            live_p = c["price_usd"]
            close_1d = closes[-1]
            prev_close_1d = closes[-2]
            last_closed_date = closed[-1]["date"]

            # 唐奇安通道：
            # prev_20d_high/low = 最新已收盘日线之前的 20 根日线极值（用于判定最新收盘日线是否完成突破）
            # donchian_20d_high/low = 最近 20 根已收盘日线极值（用于今日盘中突破触发位与止损参考）
            prev_20_highs = highs[-21:-1]
            prev_20_lows = lows[-21:-1]
            prev_20d_high = max(prev_20_highs)
            prev_20d_low = min(prev_20_lows)

            donchian_20d_high = max(highs[-20:])
            donchian_20d_low = min(lows[-20:])
            donchian_10d_high = max(highs[-10:])
            donchian_10d_low = min(lows[-10:])
            donchian_55d_high = max(highs[-55:]) if len(highs) >= 55 else max(highs)
            donchian_55d_low = min(lows[-55:]) if len(lows) >= 55 else min(lows)

            # 成交量比：最新已收盘日线成交额 / 前 20 日均量
            avg_qvol_20d = sum(qvols[-21:-1]) / 20.0 if sum(qvols[-21:-1]) > 0 else None
            vol_ratio_1d = (qvols[-1] / avg_qvol_20d) if avg_qvol_20d else None
            # 同时考虑实时 24h 合约成交额相对均值（捕捉盘中放量）
            bb_pctile = calc_bb_width_pctile(closes, 20, 60)

            chg_1d_closed = pct_diff(close_1d, prev_close_1d)
            chg_7d = calc_horizon_ret(live_p, closed, 7)
            chg_14d = calc_horizon_ret(live_p, closed, 14)
            chg_30d = calc_horizon_ret(live_p, closed, 30)

            rs_7d = (chg_7d - btc_ret_7d) if (chg_7d is not None and btc_ret_7d is not None) else None
            rs_14d = (chg_14d - btc_ret_14d) if (chg_14d is not None and btc_ret_14d is not None) else None
            rs_30d = (chg_30d - btc_ret_30d) if (chg_30d is not None and btc_ret_30d is not None) else None

            # OI 加权资金费率（8h 口径 % 与年化 %）
            okx_fr = c.get("okx_funding_8h_pct")
            hl_fr = c.get("hl_funding_8h_pct")
            if okx_fr is not None and hl_fr is not None and c["oi_usd"] > 0:
                fr_8h = (okx_fr * c["okx_oi_usd"] + hl_fr * c["hl_oi_usd"]) / c["oi_usd"]
            elif okx_fr is not None:
                fr_8h = okx_fr
            else:
                fr_8h = hl_fr
            fr_ann = (fr_8h * 3.0 * 365.0) if fr_8h is not None else None

            # OI 4h / 24h 变化率
            oi_now = c["oi_usd"]
            oi_24h_prev = (snap_24h or {}).get(sym)
            oi_4h_prev = (snap_4h or {}).get(sym)
            oi_chg_24h = pct_diff(oi_now, oi_24h_prev) if oi_24h_prev else None
            oi_chg_4h = pct_diff(oi_now, oi_4h_prev) if oi_4h_prev else None

            dist_ema20_pct = pct_diff(live_p, ema20) if ema20 else None
            dist_ema50_pct = pct_diff(live_p, ema50) if ema50 else None
            atr_pct = (atr14 / live_p * 100.0) if (atr14 and live_p) else None
            dist_ema20_atr = ((live_p - ema20) / atr14) if (ema20 and atr14 and atr14 > 0) else None

            pos_20d = None
            if donchian_20d_high > donchian_20d_low:
                pos_20d = round(
                    max(0.0, min(100.0, (live_p - donchian_20d_low) / (donchian_20d_high - donchian_20d_low) * 100.0)),
                    1,
                )

            # 日线趋势状态分类
            ema20_rising = (ema20 is not None and ema20_prev3 is not None and ema20 >= ema20_prev3)
            if ema20 and ema50:
                if live_p > ema20 > ema50 and ema20_rising:
                    trend_state = "STRONG_UP"
                    trend_label = "多头排列"
                elif ema20 > ema50 and live_p >= ema50 * 0.99:
                    trend_state = "UP_PULLBACK"
                    trend_label = "多头回踩"
                elif live_p < ema20 < ema50 and not ema20_rising:
                    trend_state = "STRONG_DOWN"
                    trend_label = "空头排列"
                elif ema20 < ema50 and live_p <= ema50 * 1.01:
                    trend_state = "DOWN_BOUNCE"
                    trend_label = "空头反抽"
                else:
                    trend_state = "RANGE_CHOP"
                    trend_label = "均线纠缠"
            else:
                trend_state = "RANGE_CHOP"
                trend_label = "结构待定"

            item = {
                "symbol": sym,
                "in_watchlist": c["in_watchlist"],
                "candle_source": c_src,
                "last_closed_date": last_closed_date,
                "price_usd": round_sig(live_p, 5),
                "close_1d": round_sig(close_1d, 5),
                "chg_1d_closed": round(chg_1d_closed, 2) if chg_1d_closed is not None else None,
                "chg_24h": round(c["chg_24h"], 2) if c["chg_24h"] is not None else None,
                "chg_7d": round(chg_7d, 2) if chg_7d is not None else None,
                "chg_14d": round(chg_14d, 2) if chg_14d is not None else None,
                "chg_30d": round(chg_30d, 2) if chg_30d is not None else None,
                "rs_7d": round(rs_7d, 2) if rs_7d is not None else None,
                "rs_14d": round(rs_14d, 2) if rs_14d is not None else None,
                "rs_30d": round(rs_30d, 2) if rs_30d is not None else None,
                "ema20": round_sig(ema20, 5),
                "ema50": round_sig(ema50, 5),
                "ema200": round_sig(ema200, 5),
                "ema20_rising": ema20_rising,
                "dist_ema20_pct": round(dist_ema20_pct, 2) if dist_ema20_pct is not None else None,
                "dist_ema50_pct": round(dist_ema50_pct, 2) if dist_ema50_pct is not None else None,
                "dist_ema20_atr": round(dist_ema20_atr, 2) if dist_ema20_atr is not None else None,
                "atr14": round_sig(atr14, 5),
                "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
                "prev_20d_high": round_sig(prev_20d_high, 5),
                "prev_20d_low": round_sig(prev_20d_low, 5),
                "donchian_20d_high": round_sig(donchian_20d_high, 5),
                "donchian_20d_low": round_sig(donchian_20d_low, 5),
                "donchian_10d_high": round_sig(donchian_10d_high, 5),
                "donchian_10d_low": round_sig(donchian_10d_low, 5),
                "donchian_55d_high": round_sig(donchian_55d_high, 5),
                "donchian_55d_low": round_sig(donchian_55d_low, 5),
                "pos_in_20d_pct": pos_20d,
                "vol_ratio_1d": round(vol_ratio_1d, 2) if vol_ratio_1d is not None else None,
                "bb_width_pctile": bb_pctile,
                "trend_state": trend_state,
                "trend_label": trend_label,
                "perp_vol_24h_usd": round(c["perp_vol_24h_usd"], 0),
                "oi_usd": round(c["oi_usd"], 0),
                "oi_change_24h_pct": round(oi_chg_24h, 2) if oi_chg_24h is not None else None,
                "oi_change_4h_pct": round(oi_chg_4h, 2) if oi_chg_4h is not None else None,
                "funding_8h_pct": round(fr_8h, 5) if fr_8h is not None else None,
                "funding_ann_pct": round(fr_ann, 2) if fr_ann is not None else None,
                "okx_funding_8h_pct": round(okx_fr, 5) if okx_fr is not None else None,
                "hl_funding_8h_pct": round(hl_fr, 5) if hl_fr is not None else None,
            }

            # 为 BTC 保存最近 60 根已收盘日线 + EMA20/50 供趋势图直接渲染
            if sym == "BTC":
                tail_n = min(60, len(closed))
                item["chart_60d"] = {
                    "dates": [b["date"][5:] for b in closed[-tail_n:]],
                    "closes": [round(b["c"], 2) for b in closed[-tail_n:]],
                    "ema20": [round(x, 2) if x is not None else None for x in ema20_s[-tail_n:]],
                    "ema50": [round(x, 2) if x is not None else None for x in ema50_s[-tail_n:]],
                }
            enriched.append(item)

        return enriched

    # ---------- 4. 日线趋势交易剧本扫描器（确定性量化筛选） ----------

    def scan_setups(self, enriched, today_str):
        cfg = self.scan_cfg.get("trend_setups", {})
        max_atr_filter = self.scan_cfg.get("perp_universe", {}).get("max_atr_pct_filter", 25.0)
        vol_min = cfg.get("breakout_vol_ratio_min", 1.25)
        pb_lo, pb_hi = cfg.get("pullback_ema20_band_pct", [-2.8, 3.2])
        bn_lo, bn_hi = cfg.get("bounce_ema20_band_pct", [-3.2, 2.8])
        max_long_fr = cfg.get("max_long_funding_ann_pct", 55.0)
        min_short_fr = cfg.get("min_short_funding_ann_pct", -35.0)
        sq_max = cfg.get("squeeze_bb_pctile_max", 15.0)
        unit_risk_pct = (cfg.get("risk_model") or {}).get("unit_risk_equity_pct", 1.0)
        max_lev_cap = (cfg.get("risk_model") or {}).get("max_leverage_cap", 3.0)

        candidates = []

        for m in enriched:
            sym = m["symbol"]
            p = m["price_usd"]
            c1d = m["close_1d"]
            ema20 = m["ema20"]
            ema50 = m["ema50"]
            atr = m["atr14"]
            if not (p and c1d and ema20 and atr and atr > 0):
                continue
            if (m.get("atr_pct") or 0) > max_atr_filter:
                continue

            fr_ann = m["funding_ann_pct"] if m["funding_ann_pct"] is not None else 0.0
            vr = m["vol_ratio_1d"] or 1.0
            rs14 = m["rs_14d"] or 0.0
            rs7 = m["rs_7d"] or 0.0
            dist20 = m["dist_ema20_pct"] or 0.0
            dist_atr = m["dist_ema20_atr"] or 0.0
            p20h = m["prev_20d_high"]
            p20l = m["prev_20d_low"]
            d20h = m["donchian_20d_high"]
            d20l = m["donchian_20d_low"]
            d10l = m["donchian_10d_low"]
            d10h = m["donchian_10d_high"]

            coin_setups = []

            def build_risk(entry_ref, stop_ref, is_long):
                if is_long:
                    raw_dist = (entry_ref - stop_ref) / entry_ref * 100.0
                else:
                    raw_dist = (stop_ref - entry_ref) / entry_ref * 100.0
                # 兜底防止止损过窄 (<2%) 或异常负值
                if raw_dist < 2.0:
                    stop_ref = entry_ref - 1.8 * atr if is_long else entry_ref + 1.8 * atr
                    raw_dist = abs(entry_ref - stop_ref) / entry_ref * 100.0
                notional_1r_pct = min(max_lev_cap * 100.0, round(unit_risk_pct / raw_dist * 100.0, 0))
                rr_score = 5 if 3.0 <= raw_dist <= 8.5 else (4 if raw_dist <= 12.0 else (3 if raw_dist <= 16.0 else 2))
                return round_sig(stop_ref, 5), round(raw_dist, 2), int(notional_1r_pct), rr_score

            # --- 模板 A1: LONG · 日线 20D 通道突破 ---
            broke_20d_up = (c1d >= p20h and p >= p20h * 0.99) or (p > d20h * 1.001)
            if broke_20d_up and fr_ann <= max_long_fr and dist_atr <= 2.8 and (vr >= vol_min or (m["chg_24h"] or 0) >= 4.0):
                entry_ref = max(p, p20h)
                stop_candidate = max(d10l, ema20 - 0.5 * atr)
                if stop_candidate >= entry_ref * 0.975:
                    stop_candidate = entry_ref - 1.8 * atr
                stop_px, stop_pct, size_1r, rr_sc = build_risk(p, stop_candidate, True)
                s_struct = 5 if (ema50 and ema20 > ema50 and c1d > p20h) else 4
                s_mom = 5 if (vr >= 1.6 and rs14 >= 8) else (4 if (vr >= 1.25 or rs14 >= 4) else 3)
                s_crowd = 5 if fr_ann <= 5 else (4 if fr_ann <= 20 else 3)
                coin_setups.append({
                    "direction": "LONG",
                    "setup_type": "breakout_20d",
                    "setup_label": "日线 20D 通道突破",
                    "trigger_price": round_sig(p20h if c1d >= p20h else d20h, 5),
                    "trigger_rule": f"日线站稳 20D 前高 ${round_sig(p20h if c1d >= p20h else d20h, 5)} 上方（或回踩不破）顺势跟进",
                    "stop_price": stop_px,
                    "stop_rule": f"日线收盘跌破结构止损 ${stop_px}（EMA20/10D低点保护，-{stop_pct}%）",
                    "stop_dist_pct": stop_pct,
                    "notional_1r_pct": size_1r,
                    "score": {
                        "structure": s_struct,
                        "momentum": s_mom,
                        "crowding": s_crowd,
                        "risk_reward": rr_sc,
                        "total": s_struct + s_mom + s_crowd + rr_sc,
                    },
                    "quant_summary": (
                        f"价格突破 20D 高点，量能比 {vr:.2f}x，14D 相对 BTC 强弱 {rs14:+.1f}%，"
                        f"年化资金费率 {fr_ann:+.1f}%。"
                    ),
                })

            # --- 模板 A2: LONG · 多头趋势回踩 EMA20 ---
            if (ema50 and ema20 > ema50 and (m["ema20_rising"] or p >= ema20)
                    and pb_lo <= dist20 <= pb_hi and p > ema50 * 1.005
                    and rs14 >= 2.0 and fr_ann <= 35.0):
                stop_candidate = min(ema50 * 0.99, ema20 - 1.5 * atr)
                stop_px, stop_pct, size_1r, rr_sc = build_risk(p, stop_candidate, True)
                s_struct = 5 if (m.get("ema200") and ema50 > m["ema200"]) else 4
                s_mom = 5 if rs14 >= 10 else (4 if rs14 >= 5 else 3)
                s_crowd = 5 if fr_ann <= 5 else (4 if fr_ann <= 20 else 3)
                coin_setups.append({
                    "direction": "LONG",
                    "setup_type": "pullback_ema20",
                    "setup_label": "多头排列回踩 EMA20",
                    "trigger_price": round_sig(ema20, 5),
                    "trigger_rule": f"回踩日线 EMA20（${round_sig(ema20, 5)}）附近企稳收阳低吸",
                    "stop_price": stop_px,
                    "stop_rule": f"日线收盘失守 EMA50 / 1.5xATR 防守位 ${stop_px}（-{stop_pct}%）",
                    "stop_dist_pct": stop_pct,
                    "notional_1r_pct": size_1r,
                    "score": {
                        "structure": s_struct,
                        "momentum": s_mom,
                        "crowding": s_crowd,
                        "risk_reward": rr_sc,
                        "total": s_struct + s_mom + s_crowd + rr_sc,
                    },
                    "quant_summary": (
                        f"日线 EMA20 > EMA50 多头排列，现价距 EMA20 仅 {dist20:+.1f}%，"
                        f"14D 相对 BTC {rs14:+.1f}%，年化费率 {fr_ann:+.1f}% 持仓负担低。"
                    ),
                })

            # --- 模板 A3: LONG · 逆势抗跌龙头 / 负费率逼空 ---
            if (p > ema20 and rs7 >= 7.0 and (fr_ann <= -8.0 or (rs14 >= 12.0 and fr_ann <= 18.0))
                    and dist_atr <= 2.4):
                stop_candidate = min(ema20 * 0.985, p - 1.8 * atr)
                stop_px, stop_pct, size_1r, rr_sc = build_risk(p, stop_candidate, True)
                if stop_pct <= 18.0:
                    s_struct = 4 if (ema50 and p > ema50) else 3
                    s_mom = 5 if rs7 >= 12 else 4
                    s_crowd = 5 if fr_ann <= -20 else 4
                    coin_setups.append({
                        "direction": "LONG",
                        "setup_type": "rs_leader_squeeze",
                        "setup_label": "逆势抗跌龙头 · 空头回补",
                        "trigger_price": round_sig(max(ema20, p * 0.985), 5),
                        "trigger_rule": f"守稳日线 EMA20（${round_sig(ema20, 5)}）且突破盘整高点 ${round_sig(d20h, 5)} 加仓",
                        "stop_price": stop_px,
                        "stop_rule": f"日线收盘跌破 EMA20 下方保护位 ${stop_px}（-{stop_pct}%）",
                        "stop_dist_pct": stop_pct,
                        "notional_1r_pct": size_1r,
                        "score": {
                            "structure": s_struct,
                            "momentum": s_mom,
                            "crowding": s_crowd,
                            "risk_reward": rr_sc,
                            "total": s_struct + s_mom + s_crowd + rr_sc,
                        },
                        "quant_summary": (
                            f"大盘承压下 7D 跑赢 BTC {rs7:+.1f}%（14D {rs14:+.1f}%），稳居 EMA20 上方，"
                            f"年化费率 {fr_ann:+.1f}% 持仓结构健康。"
                        ),
                    })

            # --- 模板 B1: SHORT · 日线 20D 通道破位 ---
            broke_20d_dn = (c1d <= p20l and p <= p20l * 1.01) or (p < d20l * 0.999)
            if broke_20d_dn and fr_ann >= min_short_fr and dist_atr >= -2.2 and (vr >= 1.15 or (m["chg_24h"] or 0) <= -4.0):
                stop_candidate = min(d10h, ema20 + 0.5 * atr)
                if stop_candidate <= p * 1.025:
                    stop_candidate = p + 1.8 * atr
                stop_px, stop_pct, size_1r, rr_sc = build_risk(p, stop_candidate, False)
                if stop_pct <= 18.0:
                    s_struct = 5 if (ema50 and ema20 < ema50 and c1d < p20l) else 4
                    s_mom = 5 if (vr >= 1.5 and rs14 <= -6) else (4 if (vr >= 1.2 or rs14 <= -2) else 3)
                    s_crowd = 5 if fr_ann >= 5 else (4 if fr_ann >= -12 else 3)
                    coin_setups.append({
                        "direction": "SHORT",
                        "setup_type": "breakdown_20d",
                        "setup_label": "日线 20D 支撑破位",
                        "trigger_price": round_sig(p20l if c1d <= p20l else d20l, 5),
                        "trigger_rule": f"反抽原 20D 低点支撑转阻力 ${round_sig(p20l if c1d <= p20l else d20l, 5)} 受阻做空（勿极度超跌追空）",
                        "stop_price": stop_px,
                        "stop_rule": f"日线收复结构阻力位 ${stop_px} 止损离场（+{stop_pct}%）",
                        "stop_dist_pct": stop_pct,
                        "notional_1r_pct": size_1r,
                        "score": {
                            "structure": s_struct,
                            "momentum": s_mom,
                            "crowding": s_crowd,
                            "risk_reward": rr_sc,
                            "total": s_struct + s_mom + s_crowd + rr_sc,
                        },
                        "quant_summary": (
                            f"跌破 20D 日线通道下沿，量能比 {vr:.2f}x，14D 相对 BTC {rs14:+.1f}%，"
                            f"年化费率 {fr_ann:+.1f}%（未达极端负费率轧空区）。"
                        ),
                    })

            # --- 模板 B2: SHORT · 空头排列反抽 EMA20 ---
            if (ema50 and ema20 < ema50 and not m["ema20_rising"]
                    and bn_lo <= dist20 <= bn_hi and p < ema50 * 0.995
                    and rs14 <= -3.0 and fr_ann >= -18.0):
                stop_candidate = max(ema50 * 1.01, ema20 + 1.5 * atr)
                stop_px, stop_pct, size_1r, rr_sc = build_risk(p, stop_candidate, False)
                s_struct = 5 if (m.get("ema200") and ema50 < m["ema200"]) else 4
                s_mom = 5 if rs14 <= -10 else 4
                s_crowd = 5 if fr_ann >= 5 else 4
                coin_setups.append({
                    "direction": "SHORT",
                    "setup_type": "bounce_ema20_short",
                    "setup_label": "空头排列反抽 EMA20",
                    "trigger_price": round_sig(ema20, 5),
                    "trigger_rule": f"反抽日线 EMA20（${round_sig(ema20, 5)}）滞涨收上影/阴线介入空单",
                    "stop_price": stop_px,
                    "stop_rule": f"日线收盘站回 EMA50 / 1.5xATR 阻力 ${stop_px} 止损（+{stop_pct}%）",
                    "stop_dist_pct": stop_pct,
                    "notional_1r_pct": size_1r,
                    "score": {
                        "structure": s_struct,
                        "momentum": s_mom,
                        "crowding": s_crowd,
                        "risk_reward": rr_sc,
                        "total": s_struct + s_mom + s_crowd + rr_sc,
                    },
                    "quant_summary": (
                        f"日线 EMA20 < EMA50 标准空头趋势，现价反抽距 EMA20 {dist20:+.1f}%，"
                        f"14D 相对 BTC {rs14:+.1f}% 持续弱势，年化费率 {fr_ann:+.1f}%。"
                    ),
                })

            # --- 模板 C: WATCH · 日线波动率极度压缩（Squeeze 变盘前夜） ---
            if (m["bb_width_pctile"] is not None and m["bb_width_pctile"] <= sq_max
                    and m["perp_vol_24h_usd"] >= 35_000_000):
                stop_px, stop_pct, size_1r, rr_sc = build_risk(d20h, ema20, True)
                coin_setups.append({
                    "direction": "WATCH",
                    "setup_type": "volatility_squeeze",
                    "setup_label": "日线波动率压缩待变盘",
                    "trigger_price": round_sig(d20h, 5),
                    "trigger_rule": f"双向突破观察：上破 20D 高点 ${round_sig(d20h, 5)} 做多 / 下破 20D 低点 ${round_sig(d20l, 5)} 做空",
                    "stop_price": round_sig(ema20, 5),
                    "stop_rule": f"突破入场后以日线中轨 EMA20（${round_sig(ema20, 5)}）作为初始防守",
                    "stop_dist_pct": stop_pct,
                    "notional_1r_pct": size_1r,
                    "score": {
                        "structure": 4,
                        "momentum": 3,
                        "crowding": 4,
                        "risk_reward": rr_sc,
                        "total": 11 + rr_sc,
                    },
                    "quant_summary": (
                        f"20D 布林带宽度处于近 60 日 {m['bb_width_pctile']}% 极低分位，"
                        f"蓄势收敛明显，等待放量走出方向。"
                    ),
                })

            if coin_setups:
                # 同一币种保留最高分剧本；优先实质多空信号而非纯 WATCH
                coin_setups.sort(
                    key=lambda s: (s["direction"] != "WATCH", s["score"]["total"]),
                    reverse=True,
                )
                best = coin_setups[0]
                best["id"] = f"{sym.lower()}-{best['setup_type']}-{today_str.replace('-', '')}"
                best["symbol"] = sym
                best["in_watchlist"] = m["in_watchlist"]
                best["price_usd"] = p
                best["close_1d"] = c1d
                best["chg_24h"] = m["chg_24h"]
                best["chg_7d"] = m["chg_7d"]
                best["rs_14d"] = m["rs_14d"]
                best["ema20"] = ema20
                best["ema50"] = ema50
                best["atr14"] = atr
                best["atr_pct"] = m["atr_pct"]
                best["dist_ema20_pct"] = m["dist_ema20_pct"]
                best["dist_ema20_atr"] = m["dist_ema20_atr"]
                best["vol_ratio_1d"] = m["vol_ratio_1d"]
                best["perp_vol_24h_usd"] = m["perp_vol_24h_usd"]
                best["oi_usd"] = m["oi_usd"]
                best["oi_change_24h_pct"] = m["oi_change_24h_pct"]
                best["funding_8h_pct"] = m["funding_8h_pct"]
                best["funding_ann_pct"] = m["funding_ann_pct"]
                best["catalyst_note"] = None
                best["risk_landmine"] = None
                best["source_url"] = None
                candidates.append(best)

        # 按综合评分 + 流动性 + 自选池微调排序
        candidates.sort(
            key=lambda x: (
                x["score"]["total"],
                1 if x["in_watchlist"] else 0,
                math.log10(max(1.0, x["perp_vol_24h_usd"])),
            ),
            reverse=True,
        )
        return candidates[:12]

    # ---------- 5. 大盘趋势择时滤网（Regime Filter） ----------

    def evaluate_regime(self, enriched, fgi, mvrv, stable_delta):
        by_sym = {m["symbol"]: m for m in enriched}
        btc = by_sym.get("BTC", {})
        eth = by_sym.get("ETH", {})

        total = len(enriched) or 1
        above_ema20 = sum(1 for m in enriched if m.get("ema20") and m["price_usd"] > m["ema20"])
        above_ema50 = sum(1 for m in enriched if m.get("ema50") and m["price_usd"] > m["ema50"])
        up_24h = sum(1 for m in enriched if (m.get("chg_24h") or 0) > 0)

        pct_ema20 = round(above_ema20 / total * 100.0, 1)
        pct_ema50 = round(above_ema50 / total * 100.0, 1)
        pct_up24 = round(up_24h / total * 100.0, 1)

        fundings = [m["funding_ann_pct"] for m in enriched if m.get("funding_ann_pct") is not None]
        median_fr_ann = round(statistics.median(fundings), 2) if fundings else None
        total_perp_oi = round(sum(m.get("oi_usd") or 0 for m in enriched), 0)

        # 维度 1: BTC 日线趋势分 (1~5)
        bp = btc.get("price_usd") or 0
        be20 = btc.get("ema20") or 0
        be50 = btc.get("ema50") or 0
        be200 = btc.get("ema200") or 0
        if bp > be20 > be50 and (not be200 or be50 > be200):
            s_btc = 5 if bp >= (btc.get("prev_20d_high") or bp + 1) else 4
        elif bp > be50:
            s_btc = 3
        elif bp < be20 < be50:
            s_btc = 1 if bp <= (btc.get("prev_20d_low") or 0) else 2
        else:
            s_btc = 2 if bp < be50 else 3

        # 维度 2: 合约广度与资金面 (1~5)
        if pct_ema20 >= 65 and (stable_delta or 0) >= 0:
            s_breadth = 5
        elif pct_ema20 >= 50:
            s_breadth = 4
        elif pct_ema20 >= 32:
            s_breadth = 3
        elif pct_ema20 >= 18:
            s_breadth = 2
        else:
            s_breadth = 1

        # 维度 3: 情绪与衍生品拥挤度 (1~5，顺势健康度：极端拥挤或崩盘恐慌扣分)
        if median_fr_ann is not None and -10 <= median_fr_ann <= 25 and (fgi or 50) >= 45:
            s_sent = 4
        elif (fgi or 50) < 25:
            s_sent = 2
        else:
            s_sent = 3

        # 维度 4: 宏观基线默认 3，由 Agent 根据 48h FOMC/CPI 微调
        s_macro = 3
        total_score = s_btc + s_breadth + s_sent + s_macro

        if total_score >= 15:
            regime_code = "BULL_TREND"
            regime_label = "多头趋势期"
            posture = "积极做多强势突破与 EMA20 回踩标的；低倍总杠杆上限 2.0x–3.0x，慎做逆势空单。"
        elif total_score >= 12:
            regime_code = "BULL_LEAN"
            regime_label = "偏多结构期"
            posture = "逢回踩 EMA20 布局相对 BTC 强势币种；总名义仓位建议 1.0x–2.0x，不追高正费率标的。"
        elif total_score >= 9:
            regime_code = "CHOP_SELECTIVE"
            regime_label = "震荡分化期"
            posture = "收缩频率与仓位（建议 ≤1.0x–1.5x），仅做强 α 独立逻辑或多空对冲配对，严防假突破磨损。"
        elif total_score >= 6:
            regime_code = "BEAR_PRESSURE"
            regime_label = "空头承压期"
            posture = "防守为主（总仓位 ≤1.0x–1.5x）：多单仅盯极少数逆势站稳 EMA20 的独立龙头，主流弱势币逢反抽 EMA20 做空；切忌在暴跌破位后低位盲目追空。"
        else:
            regime_code = "DEEP_BEAR"
            regime_label = "单边空头 / 恐慌宣泄期"
            posture = "严控回撤（≤1.0x）：警惕极端负费率暴力反抽轧空，空单等反抽均线再进，抄底须等日线右侧收复 EMA20。"

        return {
            "regime_code": regime_code,
            "regime_label": regime_label,
            "posture": posture,
            "scores": {
                "btc_trend": s_btc,
                "funding": s_breadth,
                "sentiment": s_sent,
                "macro": s_macro,
                "total": total_score,
            },
            "breadth": {
                "universe_count": total,
                "above_ema20": above_ema20,
                "pct_above_ema20": pct_ema20,
                "above_ema50": above_ema50,
                "pct_above_ema50": pct_ema50,
                "up_24h": up_24h,
                "pct_up_24h": pct_up24,
            },
            "derivatives_overview": {
                "universe_total_oi_usd": total_perp_oi,
                "median_funding_ann_pct": median_fr_ann,
            },
            "eth_summary": {
                "price_usd": eth.get("price_usd"),
                "chg_24h": eth.get("chg_24h"),
                "chg_7d": eth.get("chg_7d"),
                "ema20": eth.get("ema20"),
                "ema50": eth.get("ema50"),
                "trend_label": eth.get("trend_label"),
                "eth_btc_ratio": round(eth["price_usd"] / bp, 6) if (eth.get("price_usd") and bp) else None,
            },
        }

    # ---------- 6. 宏观、链上与板块背景指标（保留并修复 Bug） ----------

    def get_categories(self):
        d = self.cg("/coins/categories?order=market_cap_desc")
        self.sources["categories"] = "coingecko" if d else None
        return d or []

    def get_global(self):
        d = self.cg("/global")
        self.sources["global"] = "coingecko" if d else None
        return (d or {}).get("data") or {}

    def get_mvrv(self):
        d = fetch_json(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
            "?assets=btc&metrics=CapMVRVCur&frequency=1d&page_size=1"
        )
        val, ts = None, None
        if d and d.get("data"):
            row = d["data"][0]
            ts = row.get("time")
            try:
                val = float(row.get("CapMVRVCur"))
            except (TypeError, ValueError):
                val = None
        self.sources["mvrv_ratio"] = "coinmetrics" if val is not None else None
        return val, ts

    def get_chains(self):
        d = fetch_json("https://api.llama.fi/v2/chains")
        self.sources["chains_tvl"] = "defillama" if d else None
        return d or []

    def get_stablecoins(self):
        d = fetch_json("https://stablecoins.llama.fi/stablecoins?includePrices=true")
        total, usde = None, None
        if d and d.get("peggedAssets"):
            total = 0.0
            for a in d["peggedAssets"]:
                if a.get("pegType") != "peggedUSD":
                    continue
                circ = (a.get("circulating") or {}).get("peggedUSD") or 0
                total += circ
                if a.get("symbol") == "USDe":
                    usde = circ
        self.sources["stablecoin_supply"] = "defillama" if total else None
        return total, usde

    def get_fgi(self):
        d = fetch_json("https://api.alternative.me/fng/")
        val, label = None, None
        if d and d.get("data"):
            try:
                val = int(d["data"][0]["value"])
                label = d["data"][0].get("value_classification")
            except (KeyError, ValueError, TypeError):
                pass
        self.sources["fear_greed"] = "alternative.me" if val is not None else None
        return val, label

    def sector_rotation(self, categories):
        """已修复 v1 字段名 Bug：读取 market_cap_change_24h（百分比）。"""
        cfg = self.scan_cfg.get("sector_rotation", {})
        tracked = cfg.get("categories_tracked", [])
        min_cap = cfg.get("min_category_market_cap_usd", 0)
        prev = {
            s["category"]: s
            for s in (self.prev or {}).get("market_scan", {}).get("sector_rotation", [])
        }
        out = []
        for cat in categories:
            cid = cat.get("id")
            if cid not in tracked or (cat.get("market_cap") or 0) < min_cap:
                continue
            chg = cat.get("market_cap_change_24h")
            p = prev.get(cid)
            if p is None or chg is None:
                trend = 1
            else:
                prev_chg = p.get("market_cap_change_24h")
                prev_trend = p.get("trend_sessions") or 1
                if prev_chg is not None and (chg >= 0) == (prev_chg >= 0):
                    trend = prev_trend + 1
                else:
                    trend = 1
            out.append({
                "category": cid,
                "name": cat.get("name"),
                "market_cap": cat.get("market_cap"),
                "market_cap_change_24h": round(chg, 2) if chg is not None else None,
                "trend_sessions": trend,
                "note": None,
            })
        out.sort(key=lambda x: x.get("market_cap_change_24h") or -999, reverse=True)
        return out

    def chains_tvl_delta(self, chains):
        prev = {
            c["chain"]: c
            for c in (self.prev or {}).get("market_scan", {}).get("chains_tvl_delta", [])
        }
        top = sorted(chains, key=lambda x: x.get("tvl") or 0, reverse=True)[:12]
        out = []
        for ch in top:
            name = ch.get("name")
            tvl = ch.get("tvl")
            p = prev.get(name)
            delta = None
            if p and p.get("tvl") and tvl is not None:
                delta = round((tvl - p["tvl"]) / p["tvl"] * 100, 2)
            out.append({"chain": name, "tvl": tvl, "tvl_change_pct_vs_prev": delta})
        return out

    def freshness(self, btc_ctx):
        prev_btc = (self.prev or {}).get("market_context", {}).get("btc", {})
        prev_fresh = (self.prev or {}).get("_freshness", {})
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        out = {}
        for f in FRESHNESS_FIELDS:
            now_v = btc_ctx.get(f)
            if now_v is None:
                continue
            prev_v = prev_btc.get(f)
            pf = prev_fresh.get(f, {})
            same = False
            if prev_v is not None:
                if isinstance(now_v, (int, float)) and isinstance(prev_v, (int, float)):
                    same = abs(float(now_v) - float(prev_v)) < 1e-9
                else:
                    same = now_v == prev_v
            if same:
                out[f] = {
                    "value": now_v,
                    "unchanged_since": pf.get("unchanged_since") or today,
                    "sessions_unchanged": (pf.get("sessions_unchanged") or 1) + 1,
                }
            else:
                out[f] = {"value": now_v, "unchanged_since": today, "sessions_unchanged": 0}
        return out

    def prev_events(self, today):
        events = (self.prev or {}).get("events", [])
        out = []
        for e in events:
            e = dict(e)
            if e.get("status") == "passed":
                continue
            try:
                d = datetime.strptime(e["date"], "%Y-%m-%d").date()
                e["days_away"] = (d - today).days
                e["status"] = "passed" if e["days_away"] < 0 else "upcoming"
            except Exception:
                pass
            if e.get("status") == "upcoming":
                out.append(e)
        return out

    # ---------- 主运行流程 ----------

    def run(self, session="daily"):
        now = datetime.now(TZ)
        today = now.date()
        today_str = today.strftime("%Y-%m-%d")
        print(f"[collect 2.0] {now.isoformat()} session={session}", flush=True)

        crypto_whitelist = self.get_crypto_whitelist_symbols()
        selected, all_coins_map = self.fetch_perp_universe(crypto_whitelist)
        snap_24h, snap_4h = self.update_and_calc_oi_deltas(all_coins_map, now.timestamp())
        print(f"[collect 2.0] perp universe selected={len(selected)} (from {len(all_coins_map)} total swaps)", flush=True)

        enriched = self.enrich_universe_metrics(selected, snap_24h, snap_4h)
        print(f"[collect 2.0] daily candles & indicators computed for {len(enriched)} liquid perps", flush=True)

        # 宏观与链上背景
        chains = self.get_chains()
        stable_total, usde = self.get_stablecoins()
        categories = self.get_categories()
        fgi, fgi_label = self.get_fgi()
        glob = self.get_global()
        mvrv, mvrv_ts = self.get_mvrv()

        prev_btc = (self.prev or {}).get("market_context", {}).get("btc", {})
        prev_glob = (self.prev or {}).get("market_context", {}).get("global", {})

        dominance = None
        mcaps = glob.get("market_cap_percentage") or {}
        if mcaps.get("btc") is not None:
            dominance = round(mcaps["btc"], 2)
        dom_change_pp = None
        if dominance is not None and prev_btc.get("dominance") is not None:
            dom_change_pp = round(dominance - prev_btc["dominance"], 2)

        stable_delta = None
        if stable_total and prev_glob.get("stablecoin_total_supply"):
            stable_delta = round(
                (stable_total - prev_glob["stablecoin_total_supply"])
                / prev_glob["stablecoin_total_supply"] * 100,
                2,
            )

        regime = self.evaluate_regime(enriched, fgi, mvrv, stable_delta)
        setups = self.scan_setups(enriched, today_str)
        sectors = self.sector_rotation(categories)
        tvl = self.chains_tvl_delta(chains)

        by_sym = {m["symbol"]: m for m in enriched}
        btc_m = by_sym.get("BTC", {})

        # 衍生品极值榜（负费率逼空监控 & 正费率拥挤监控 & RS 领涨领跌榜，统一过滤微型OI高波动杂币）
        max_atr = self.scan_cfg.get("perp_universe", {}).get("max_atr_pct_filter", 25.0)
        liquid_pool = [
            m for m in enriched
            if (m.get("oi_usd") or 0) >= 8_000_000 and (m.get("atr_pct") or 0) <= max_atr
        ]
        if len(liquid_pool) < 10:
            liquid_pool = enriched
        with_fr = [m for m in liquid_pool if m.get("funding_ann_pct") is not None]
        neg_funding_leaders = sorted(with_fr, key=lambda x: x["funding_ann_pct"])[:6]
        pos_funding_leaders = sorted(with_fr, key=lambda x: x["funding_ann_pct"], reverse=True)[:6]
        rs_leaders = sorted(
            [m for m in liquid_pool if m.get("rs_14d") is not None and m["symbol"] != "BTC"],
            key=lambda x: x["rs_14d"],
            reverse=True,
        )[:8]
        rs_laggards = sorted(
            [m for m in liquid_pool if m.get("rs_14d") is not None and m["symbol"] != "BTC"],
            key=lambda x: x["rs_14d"],
        )[:8]

        watch_order = [str(s).upper() for s in (self.watchlist_cfg.get("coins") or [])]
        watchlist_rows = [by_sym[s] for s in watch_order if s in by_sym]

        # BTC 真实日线结构支撑与阻力（替代旧版假 7d min/max）
        bp = btc_m.get("price_usd")
        support_candidates = [
            v for v in (btc_m.get("donchian_20d_low"), btc_m.get("donchian_55d_low"),
                        btc_m.get("ema50"), btc_m.get("ema200"))
            if v is not None and bp is not None and v < bp
        ]
        resist_candidates = [
            v for v in (btc_m.get("ema20"), btc_m.get("ema50"),
                        btc_m.get("donchian_20d_high"), btc_m.get("donchian_55d_high"))
            if v is not None and bp is not None and v > bp
        ]
        btc_support = max(support_candidates) if support_candidates else btc_m.get("donchian_20d_low")
        btc_resist = min(resist_candidates) if resist_candidates else btc_m.get("donchian_20d_high")

        btc_ctx = {
            "price_usd": btc_m.get("price_usd"),
            "close_1d": btc_m.get("close_1d"),
            "last_closed_date": btc_m.get("last_closed_date"),
            "price_change_24h": btc_m.get("chg_24h"),
            "price_change_7d": btc_m.get("chg_7d"),
            "price_change_30d": btc_m.get("chg_30d"),
            "ema20": btc_m.get("ema20"),
            "ema50": btc_m.get("ema50"),
            "ema200": btc_m.get("ema200"),
            "atr14": btc_m.get("atr14"),
            "atr_pct": btc_m.get("atr_pct"),
            "donchian_20d_high": btc_m.get("donchian_20d_high"),
            "donchian_20d_low": btc_m.get("donchian_20d_low"),
            "donchian_55d_high": btc_m.get("donchian_55d_high"),
            "donchian_55d_low": btc_m.get("donchian_55d_low"),
            "trend_state": btc_m.get("trend_state"),
            "trend_label": btc_m.get("trend_label"),
            "fear_greed": fgi,
            "fear_greed_label": fgi_label,
            "mvrv_ratio": mvrv,
            "mvrv_data_time": mvrv_ts,
            "funding_rate": btc_m.get("funding_8h_pct"),
            "funding_ann_pct": btc_m.get("funding_ann_pct"),
            "open_interest": btc_m.get("oi_usd"),
            "oi_change_24h_pct": btc_m.get("oi_change_24h_pct"),
            "dominance": dominance,
            "dominance_change_pp": dom_change_pp,
            "support": btc_support,
            "resistance": btc_resist,
            "chart_60d": btc_m.get("chart_60d") or {},
        }
        self.sources["funding_rate"] = "okx_v5+hyperliquid" if btc_ctx["funding_rate"] is not None else None
        self.sources["open_interest"] = "okx_v5+hyperliquid" if btc_ctx["open_interest"] is not None else None

        def slim(m):
            keys = (
                "symbol", "price_usd", "close_1d", "chg_24h", "chg_7d", "chg_14d", "rs_7d", "rs_14d",
                "ema20", "ema50", "dist_ema20_pct", "dist_ema20_atr", "donchian_20d_high",
                "donchian_20d_low", "pos_in_20d_pct", "atr14", "atr_pct", "vol_ratio_1d",
                "bb_width_pctile", "trend_state", "trend_label", "perp_vol_24h_usd", "oi_usd",
                "oi_change_24h_pct", "funding_8h_pct", "funding_ann_pct",
            )
            return {k: m.get(k) for k in keys}

        collected = {
            "schema_version": "2.0-daily-perp-trend",
            "collected_at": now.isoformat(),
            "date": today_str,
            "session": session,
            "regime": regime,
            "setups_candidates": setups,
            "watchlist_rows": [slim(m) for m in watchlist_rows],
            "rs_leaders": [slim(m) for m in rs_leaders],
            "rs_laggards": [slim(m) for m in rs_laggards],
            "neg_funding_leaders": [slim(m) for m in neg_funding_leaders],
            "pos_funding_leaders": [slim(m) for m in pos_funding_leaders],
            "sector_rotation": sectors,
            "chains_tvl_delta": tvl,
            "btc": btc_ctx,
            "eth": regime["eth_summary"],
            "global": {
                "total_market_cap_usd": (glob.get("total_market_cap") or {}).get("usd"),
                "stablecoin_total_supply": stable_total,
                "stablecoin_supply_change_pct": stable_delta,
                "usde_circulating": usde,
            },
            "freshness": self.freshness(btc_ctx),
            "previous": {
                "date": (self.prev or {}).get("timestamp", "")[:10] or None,
                "events": self.prev_events(today),
                "market_score": (self.prev or {}).get("market_score"),
            },
            "crypto_universe_symbols": sorted(m["symbol"] for m in enriched),
            "_sources": self.sources,
        }

        out_path = ROOT / "data/collected.json"
        with open(out_path, "w") as f:
            json.dump(collected, f, ensure_ascii=False, indent=2)

        missing = [k for k, v in self.sources.items() if v is None]
        print(
            f"[collect 2.0] done -> {out_path}  setups={len(setups)} watchlist={len(watchlist_rows)} "
            f"sectors={len(sectors)} missing_sources={missing or '无'}",
            flush=True,
        )
        return 0


if __name__ == "__main__":
    sess = sys.argv[1] if len(sys.argv) > 1 else "daily"
    sys.exit(TrendCollector().run(sess))
