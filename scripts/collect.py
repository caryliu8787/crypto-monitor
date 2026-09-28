#!/usr/bin/env python3
"""crypto-monitor 数据预采集器（确定性环节，替代模型逐条调 API）。

职责：
- 抓取全部免费 API（CoinGecko / DeFiLlama / CoinMetrics / Alternative.me）
- 币池过滤 + 异动候选排序 + 上涨广度
- 板块轮动 trend_sessions、链 TVL 动量、稳定币供应、新鲜度计数
- 从上期 data/latest.json 提取对比基线（机会/事件/评分）
- 产出 data/collected.json 供模型做定性归因与评分

模型不接触原始 API；数值全部来自本脚本。
用法: python3 scripts/collect.py [daily]
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

CG = "https://api.coingecko.com/api/v3"
CG_CALL_GAP = 7          # 匿名限速 5-15 次/分钟，CoinGecko 调用间隔
RETRY_WAIT_429 = 60

# markets 端点不返回 category，用符号黑名单近似 exclude_categories
EXCLUDE_SYMBOLS = {
    "usdt", "usdc", "dai", "usde", "usds", "fdusd", "tusd", "usdd", "pyusd",
    "wbtc", "weth", "wbnb", "steth", "wsteth", "cbbtc", "cbeth", "reth",
    "bsc-usd", "usdtb", "susde", "usdn", "frax", "lusd", "busd", "aaveusdc",
}

FRESHNESS_FIELDS = ["mvrv_ratio", "funding_rate", "open_interest", "fear_greed", "dominance"]


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fetch_json(url, headers=None, timeout=60, retries_on_429=1):
    """GET JSON；429 等待后重试；失败返回 None。"""
    for attempt in range(1 + retries_on_429):
        try:
            req = urllib.request.Request(url, headers=headers or {})
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
            print(f"  fetch failed: {e}: {url[:80]}", flush=True)
            return None
    return None


class Collector:
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
        """CoinGecko 调用，强制间隔，避免匿名 429。"""
        gap = time.time() - self._last_cg
        if gap < CG_CALL_GAP:
            time.sleep(CG_CALL_GAP - gap)
        self._last_cg = time.time()
        return fetch_json(CG + path, headers=self._cg_headers)

    # ---------- 各数据源 ----------
    def get_markets(self):
        uni = self.scan_cfg.get("universe", {})
        per_page = uni.get("movers_pool_size", 250)
        d = self.cg(f"/coins/markets?vs_currency=usd&order=market_cap_desc"
                    f"&per_page={per_page}&page=1&price_change_percentage=24h,7d,30d")
        self.sources["markets_250"] = "coingecko" if d else None
        return d or []

    def get_trending(self):
        d = self.cg("/search/trending")
        self.sources["trending"] = "coingecko" if d else None
        out = []
        for item in (d or {}).get("coins", []):
            c = item.get("item", {})
            out.append({"coin_id": c.get("id"), "symbol": c.get("symbol"), "name": c.get("name")})
        return out

    def get_categories(self):
        d = self.cg("/coins/categories")
        self.sources["categories"] = "coingecko" if d else None
        return d or []

    def get_global(self):
        d = self.cg("/global")
        self.sources["global"] = "coingecko" if d else None
        return (d or {}).get("data") or {}

    def get_btc_sparkline(self):
        d = self.cg("/coins/bitcoin?sparkline=true")
        ok = d and d.get("market_data", {}).get("sparkline_7d", {}).get("price")
        self.sources["btc_sparkline"] = "coingecko" if ok else None
        return (d or {}).get("market_data", {}).get("sparkline_7d", {}).get("price") or []

    def get_derivatives(self):
        d = self.cg("/derivatives?include_tickers=unexpired")
        funding, oi = None, None
        if d:
            for item in d:
                if item.get("market") == "Binance (Futures)" and item.get("symbol") == "BTCUSDT":
                    funding = item.get("funding_rate")
                    oi = item.get("open_interest")
                    break
        self.sources["funding_rate"] = "coingecko_derivatives" if funding is not None else None
        self.sources["open_interest"] = "coingecko_derivatives" if oi is not None else None
        return funding, oi

    def get_mvrv(self):
        d = fetch_json("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
                       "?assets=btc&metrics=CapMVRVCur&frequency=1d&page_size=1")
        val, ts = None, None
        if d and d.get("data"):
            row = d["data"][0]
            val = row.get("CapMVRVCur")
            ts = row.get("time")
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = None
        self.sources["mvrv_ratio"] = "coinmetrics" if val is not None else None
        return val, ts

    def get_chains(self):
        d = fetch_json("https://api.llama.fi/v2/chains")
        self.sources["chains_tvl"] = "defillama" if d else None
        return d or []

    def get_stablecoins(self):
        """全部稳定币资产；返回 (USD 锚定总供应, USDe 流通量)。"""
        d = fetch_json("https://stablecoins.llama.fi/stablecoins?includePrices=true")
        total, usde = None, None
        if d and d.get("peggedAssets"):
            total = 0.0
            for a in d["peggedAssets"]:
                if a.get("pegType") != "peggedUSD":
                    continue  # 与历史口径一致：只统计 USD 锚定
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

    # ---------- 计算 ----------
    def filter_movers(self, markets, trending):
        uni = self.scan_cfg.get("universe", {})
        min_mc = uni.get("min_market_cap_usd", 30_000_000)
        min_vol = uni.get("min_volume_24h_usd", 3_000_000)
        top_n = uni.get("top_movers_reported", 12)
        trending_ids = {t["coin_id"] for t in trending}

        def eligible(c, bypass):
            if (c.get("symbol") or "").lower() in EXCLUDE_SYMBOLS:
                return False
            if bypass:
                return True  # 新币 bypass：trending 内不受门槛限制
            return (c.get("market_cap") or 0) >= min_mc and (c.get("total_volume") or 0) >= min_vol

        pool = [c for c in markets if eligible(c, c.get("id") in trending_ids)]
        # 上涨广度（不过 bypass，只统计达标池，口径与历史报告一致）
        qualified = [c for c in markets
                     if (c.get("symbol") or "").lower() not in EXCLUDE_SYMBOLS
                     and (c.get("market_cap") or 0) >= min_mc
                     and (c.get("total_volume") or 0) >= min_vol]
        up = sum(1 for c in qualified if (c.get("price_change_percentage_24h_in_currency") or 0) > 0)
        breadth = {"up": up, "total": len(qualified),
                   "pct": round(up / len(qualified) * 100, 1) if qualified else None}

        def rank_key(c):
            p24 = abs(c.get("price_change_percentage_24h_in_currency") or 0)
            p7d = abs(c.get("price_change_percentage_7d_in_currency") or 0)
            return p24 + p7d  # 综合排序：|24h| + |7d|

        pool.sort(key=rank_key, reverse=True)
        movers = []
        for c in pool[:top_n]:
            movers.append({
                "coin_id": c.get("id"),
                "symbol": (c.get("symbol") or "").upper(),
                "price_usd": c.get("current_price"),
                "price_change_24h": c.get("price_change_percentage_24h_in_currency"),
                "price_change_7d": c.get("price_change_percentage_7d_in_currency"),
                "price_change_30d": c.get("price_change_percentage_30d_in_currency"),
                "market_cap": c.get("market_cap"),
                "volume_24h": c.get("total_volume"),
                "circulating_supply": c.get("circulating_supply"),
                "total_supply": c.get("total_supply"),
                "in_trending": c.get("id") in trending_ids,
                "reason": None,          # 模型填
                "narrative_tag": None,   # 模型填
                "source_url": None,      # 模型填
            })
        return movers, breadth

    def sector_rotation(self, categories):
        cfg = self.scan_cfg.get("sector_rotation", {})
        tracked = cfg.get("categories_tracked", [])
        min_cap = cfg.get("min_category_market_cap_usd", 0)
        prev = {s["category"]: s for s in
                (self.prev or {}).get("market_scan", {}).get("sector_rotation", [])}
        out = []
        for cat in categories:
            cid = cat.get("id")
            if cid not in tracked or (cat.get("market_cap") or 0) < min_cap:
                continue
            chg = cat.get("market_cap_change_24h_usd")
            p = prev.get(cid)
            if p is None or chg is None:
                trend = 1  # 基线
            else:
                prev_chg = p.get("market_cap_change_24h")
                prev_trend = p.get("trend_sessions") or 1
                if prev_chg is not None and (chg > 0) == (prev_chg > 0):
                    trend = prev_trend + 1
                else:
                    trend = 1
            out.append({
                "category": cid,
                "name": cat.get("name"),
                "market_cap": cat.get("market_cap"),
                "market_cap_change_24h": chg,
                "trend_sessions": trend,
                "note": None,  # 模型填
            })
        return out

    def chains_tvl_delta(self, chains):
        prev = {c["chain"]: c for c in
                (self.prev or {}).get("market_scan", {}).get("chains_tvl_delta", [])}
        top = sorted(chains, key=lambda x: x.get("tvl") or 0, reverse=True)[:16]
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

    def freshness(self, btc_now):
        """与上期逐字段比对，返回 _freshness 结构。"""
        prev_btc = (self.prev or {}).get("market_context", {}).get("btc", {})
        prev_fresh = (self.prev or {}).get("_freshness", {})
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        out = {}
        for f in FRESHNESS_FIELDS:
            now_v = btc_now.get(f)
            if now_v is None:
                continue  # null 不参与校验
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
        """上期事件跨期携带，重算 days_away。"""
        events = (self.prev or {}).get("events", [])
        out = []
        for e in events:
            e = dict(e)
            # 上期已 passed 的保留一期后删除
            if e.get("status") == "passed":
                continue
            try:
                d = datetime.strptime(e["date"], "%Y-%m-%d").date()
                e["days_away"] = (d - today).days
                e["status"] = "passed" if e["days_away"] < 0 else "upcoming"
            except Exception:
                pass
            out.append(e)
        return out

    def watchlist(self, markets):
        ids = (self.watchlist_cfg or {}).get("coins") or []
        if not ids:
            return {}
        by_id = {c.get("id"): c for c in markets}
        missing = [i for i in ids if i not in by_id]
        if missing:
            extra = self.cg("/coins/markets?vs_currency=usd&ids=" + ",".join(missing)
                            + "&price_change_percentage=24h,7d")
            for c in extra or []:
                by_id[c.get("id")] = c
        out = {}
        for i in ids:
            c = by_id.get(i)
            if c:
                out[i] = {
                    "price_usd": c.get("current_price"),
                    "price_change_24h": c.get("price_change_percentage_24h_in_currency"),
                    "price_change_7d": c.get("price_change_percentage_7d_in_currency"),
                    "market_cap": c.get("market_cap"),
                    "note": None,
                }
            else:
                out[i] = {"price_usd": None, "price_change_24h": None,
                          "price_change_7d": None, "market_cap": None,
                          "note": "不在扫描池且定向查询失败"}
        return out

    def run(self, session):
        now = datetime.now(TZ)
        today = now.date()
        print(f"[collect] {now.isoformat()} session={session}", flush=True)

        # CoinGecko 与其他来源交错，避免连发 429
        markets = self.get_markets()
        chains = self.get_chains()
        trending = self.get_trending()
        stable_total, usde = self.get_stablecoins()
        categories = self.get_categories()
        fgi, fgi_label = self.get_fgi()
        glob = self.get_global()
        mvrv, mvrv_ts = self.get_mvrv()
        sparkline = self.get_btc_sparkline()
        funding, oi = self.get_derivatives()

        movers, breadth = self.filter_movers(markets, trending)
        sectors = self.sector_rotation(categories)
        tvl = self.chains_tvl_delta(chains)

        by_id = {c.get("id"): c for c in markets}
        btc_m = by_id.get("bitcoin", {})
        eth_m = by_id.get("ethereum", {})
        prev_btc = (self.prev or {}).get("market_context", {}).get("btc", {})
        prev_glob = (self.prev or {}).get("market_context", {}).get("global", {})

        dominance = None
        mcaps = glob.get("market_cap_percentage") or {}
        if mcaps.get("btc") is not None:
            dominance = round(mcaps["btc"], 4)
        dom_change_pp = None
        if dominance is not None and prev_btc.get("dominance") is not None:
            dom_change_pp = round(dominance - prev_btc["dominance"], 2)

        stable_delta = None
        if stable_total and prev_glob.get("stablecoin_total_supply"):
            stable_delta = round((stable_total - prev_glob["stablecoin_total_supply"])
                                 / prev_glob["stablecoin_total_supply"] * 100, 2)

        btc = {
            "price_usd": btc_m.get("current_price"),
            "price_change_24h": btc_m.get("price_change_percentage_24h_in_currency"),
            "price_change_7d": btc_m.get("price_change_percentage_7d_in_currency"),
            "price_change_30d": btc_m.get("price_change_percentage_30d_in_currency"),
            "fear_greed": fgi,
            "fear_greed_label": fgi_label,
            "mvrv_ratio": mvrv,
            "mvrv_data_time": mvrv_ts,
            "funding_rate": funding,
            "open_interest": oi,
            "dominance": dominance,
            "dominance_change_pp": dom_change_pp,
            "sparkline_7d": sparkline,
            "support": min(sparkline) if sparkline else None,
            "resistance": max(sparkline) if sparkline else None,
        }
        eth_price = eth_m.get("current_price")
        eth = {
            "price_usd": eth_price,
            "price_change_24h": eth_m.get("price_change_percentage_24h_in_currency"),
            "price_change_7d": eth_m.get("price_change_percentage_7d_in_currency"),
            "eth_btc_ratio": (eth_price / btc["price_usd"]) if eth_price and btc["price_usd"] else None,
        }

        collected = {
            "collected_at": now.isoformat(),
            "date": today.strftime("%Y-%m-%d"),
            "session": session,
            "movers": movers,
            "breadth": breadth,
            "sector_rotation": sectors,
            "trending": trending,
            "chains_tvl_delta": tvl,
            "btc": btc,
            "eth": eth,
            "global": {
                "total_market_cap_usd": (glob.get("total_market_cap") or {}).get("usd"),
                "stablecoin_total_supply": stable_total,
                "stablecoin_supply_change_pct": stable_delta,
                "usde_circulating": usde,
            },
            "watchlist": self.watchlist(markets),
            "freshness": self.freshness(btc),
            "previous": {
                "date": (self.prev or {}).get("timestamp", "")[:10] or None,
                "opportunities": (self.prev or {}).get("opportunities", []),
                "events": self.prev_events(today),
                "market_score": (self.prev or {}).get("market_score"),
                "macro": (self.prev or {}).get("market_context", {}).get("macro"),
                "open_interest": prev_btc.get("open_interest"),
                "funding_rate": prev_btc.get("funding_rate"),
            },
            "_sources": self.sources,
        }

        out = ROOT / "data/collected.json"
        with open(out, "w") as f:
            json.dump(collected, f, ensure_ascii=False, indent=1)
        missing = [k for k, v in self.sources.items() if v is None]
        print(f"[collect] done -> {out}  movers={len(movers)} sectors={len(sectors)} "
              f"chains={len(tvl)} missing_sources={missing or '无'}", flush=True)
        return 0


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "daily"
    sys.exit(Collector().run(session))
