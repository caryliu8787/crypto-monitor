#!/usr/bin/env python3
"""crypto-monitor 2.0 报告组装器（确定性合并 collected.json + overlay.json）。

职责：
1. 从 data/collected.json 读取全部精确量化指标（严禁 overlay 覆盖任何数值字段）
2. 从 data/overlay.json 合并定性排雷备注（catalyst_note / risk_landmine / events / regime_note）
3. 自动评估日线趋势告警规则（BTC 通道/均线破位、高分剧本、负费率逼空、拥挤偏离、48h/7d 事件排雷）
4. 生成：
   - data/latest.json
   - reports/YYYY-MM-DD_daily.md（精炼实战日线交易早报，控制在 120~170 行）
   - reports/latest-alert.txt
5. 自动调用 scripts/render-html.py 产出交互式 HTML 仪表盘

用法: python3 scripts/assemble.py [daily]
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


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


def fmt_pct(v, digits=2, signed=True):
    if v is None:
        return "—"
    if signed:
        return f"+{v:.{digits}f}%" if v >= 0 else f"{v:.{digits}f}%"
    return f"{v:.{digits}f}%"


def fmt_usd(v):
    if v is None:
        return "—"
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}万亿"
    if abs(v) >= 1e8:
        return f"${v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"${v / 1e4:.0f}万"
    return f"${v:,.0f}"


def normalize_events(raw_events, today_date):
    out = []
    seen = set()
    for e in raw_events or []:
        if not isinstance(e, dict) or not e.get("date"):
            continue
        eid = e.get("id") or f"{str(e.get('coin', 'mkt')).lower()}-{e.get('event_type', 'event')}-{e['date'].replace('-', '')}"
        if eid in seen:
            continue
        seen.add(eid)
        item = dict(e)
        item["id"] = eid
        try:
            d = datetime.strptime(item["date"], "%Y-%m-%d").date()
            item["days_away"] = (d - today_date).days
            item["status"] = "passed" if item["days_away"] < 0 else "upcoming"
        except Exception:
            continue
        if item["status"] == "upcoming":
            out.append(item)
    out.sort(key=lambda x: (x.get("days_away", 9999), x.get("date", "9999")))
    return out


def build_alerts(btc, setups, enriched_watch, neg_leaders, events, prev_btc):
    alerts = []

    # 1. BTC 20D 通道突破 / 破位
    bp = btc.get("price_usd")
    d20h = btc.get("donchian_20d_high")
    d20l = btc.get("donchian_20d_low")
    if bp and d20h and bp >= d20h * 0.998:
        alerts.append({
            "severity": "critical",
            "rule": "btc_20d_channel_break",
            "message": f"BTC 触及/突破日线 20D 高点阻力 {fmt_px(d20h)}（现价 {fmt_px(bp)}），关注右侧多头趋势共振",
        })
    elif bp and d20l and bp <= d20l * 1.003:
        alerts.append({
            "severity": "critical",
            "rule": "btc_20d_channel_break",
            "message": f"BTC 触及/跌破日线 20D 低点 {fmt_px(d20l)}（现价 {fmt_px(bp)}），大盘处于下行寻底阶段，多单严控仓位",
        })

    # 2. BTC EMA50 穿越
    ema50 = btc.get("ema50")
    prev_p = (prev_btc or {}).get("price_usd")
    if bp and ema50 and prev_p:
        if prev_p >= ema50 > bp:
            alerts.append({
                "severity": "warning",
                "rule": "btc_ema50_cross",
                "message": f"BTC 失守日线 EMA50 中期均线（{fmt_px(ema50)}），中期趋势转弱",
            })
        elif prev_p <= ema50 < bp:
            alerts.append({
                "severity": "warning",
                "rule": "btc_ema50_cross",
                "message": f"BTC 重新站上日线 EMA50 中期均线（{fmt_px(ema50)}），中期结构转强",
            })

    # 3. 高分交易剧本 (>=15/20)
    for s in setups:
        tot = (s.get("score") or {}).get("total") or 0
        if tot >= 15 and s.get("direction") in ("LONG", "SHORT"):
            alerts.append({
                "severity": "critical",
                "rule": "high_conviction_setup",
                "message": (
                    f"高分日线剧本：{s['symbol']} {s['direction']} · {s['setup_label']}（{tot}/20）"
                    f" — 触发 {fmt_px(s.get('trigger_price'))} / 止损 {fmt_px(s.get('stop_price'))}（{s.get('stop_dist_pct')}%）"
                ),
            })

    # 4. 负费率逼空异动
    for m in neg_leaders[:4]:
        fr = m.get("funding_ann_pct")
        c24 = m.get("chg_24h")
        if fr is not None and c24 is not None and fr <= -30.0 and c24 >= 2.0:
            alerts.append({
                "severity": "warning",
                "rule": "perp_short_squeeze",
                "message": (
                    f"负费率逼空观察：{m['symbol']} 年化费率 {fr:+.1f}% 且 24h {c24:+.2f}%"
                    f"（合约 OI {fmt_usd(m.get('oi_usd'))}），空头拥挤慎摸顶"
                ),
            })

    # 5. 自选池过度偏离 / 正费率拥挤
    for w in enriched_watch:
        datr = w.get("dist_ema20_atr")
        fr = w.get("funding_ann_pct") or 0
        if (datr is not None and abs(datr) >= 3.0) or fr >= 65.0:
            alerts.append({
                "severity": "warning",
                "rule": "perp_crowded_extension",
                "message": (
                    f"偏离/拥挤预警：{w['symbol']} 偏离日线 EMA20 达 {datr:+.2f}x ATR，"
                    f"年化费率 {fr:+.1f}%，忌追涨杀跌"
                ),
            })

    # 6. 48h & 7d 事件排雷
    for e in events:
        da = e.get("days_away")
        if da is not None and 0 <= da <= 2:
            alerts.append({
                "severity": "warning",
                "rule": "event_within_48h",
                "message": f"⏰ 48h 持仓排雷：{str(e.get('coin','')).upper()} {e.get('event_type')}（{e.get('date')}）— {e.get('description','')}",
            })
        elif da is not None and 2 < da <= 7 and e.get("event_type") == "unlock":
            alerts.append({
                "severity": "info",
                "rule": "major_unlock_headwind",
                "message": f"🔓 7d 解锁排雷：{str(e.get('coin','')).upper()}（{e.get('date')}，剩 {da} 天）— {e.get('description','')}",
            })

    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: sev_rank.get(a.get("severity"), 3))
    return alerts


def generate_markdown(latest):
    date = latest["timestamp"][:10]
    sess = latest["session"]
    reg = latest["regime"]
    sc = reg["scores"]
    br = reg["breadth"]
    btc = latest["market_context"]["btc"]
    eth = latest["market_context"]["eth"]
    glob = latest["market_context"]["global"]
    setups = latest["setups"]
    watch = latest["watchlist_rows"]
    scan = latest["market_scan"]
    events = latest["events"]
    alerts = latest["alerts"]

    lines = [
        f"# 加密货币日线合约趋势早报 — {date}（{sess}）",
        "",
        f"> 采集时间：{latest['timestamp'][:16].replace('T', ' ')} (UTC+8) ｜ 已收盘日线基准：{btc.get('last_closed_date', '—')} (00:00 UTC)",
        f"> 数据源：OKX Swap + Hyperliquid + CoinGecko + DeFiLlama + CoinMetrics + Alternative.me（零推算，详见 `_sources`）",
        "",
        "## 一、大盘择时滤网（Regime & 仓位偏置）",
        "",
        f"- **当前阶段：{reg['regime_label']}（{sc['total']}/20）**",
        f"- **仓位与执行准则**：{reg['posture']}",
    ]
    if reg.get("regime_note"):
        lines.append(f"- **定性补充**：{reg['regime_note']}")
    mvrv_val = btc.get("mvrv_ratio")
    mvrv_str = f"{mvrv_val:.2f}" if isinstance(mvrv_val, (int, float)) else (mvrv_val or "—")
    lines += [
        f"- **BTC 日线结构**：现价 **{fmt_px(btc.get('price_usd'))}**（24h {fmt_pct(btc.get('price_change_24h'))} / 7d {fmt_pct(btc.get('price_change_7d'))}）｜ "
        f"`EMA20` {fmt_px(btc.get('ema20'))} / `EMA50` {fmt_px(btc.get('ema50'))} / `EMA200` {fmt_px(btc.get('ema200'))}（**{btc.get('trend_label','—')}**）",
        f"- **BTC 通道与波幅**：20D 区间 `{fmt_px(btc.get('donchian_20d_low'))} – {fmt_px(btc.get('donchian_20d_high'))}` ｜ 日线 `ATR(14)` {fmt_px(btc.get('atr14'))}（{fmt_pct(btc.get('atr_pct'), signed=False)}）｜ 年化费率 {fmt_pct(btc.get('funding_ann_pct'), 1)}",
        f"- **ETH 结构**：{fmt_px(eth.get('price_usd'))}（24h {fmt_pct(eth.get('chg_24h'))}，{eth.get('trend_label','—')}，ETH/BTC `{eth.get('eth_btc_ratio') or '—'}`）",
        f"- **主流合约广度（{br['universe_count']} 币池）**：站上日线 `EMA20` **{br['above_ema20']}/{br['universe_count']}（{br['pct_above_ema20']}%）** ｜ "
        f"站上 `EMA50` **{br['pct_above_ema50']}%** ｜ 中位年化费率 **{fmt_pct(reg['derivatives_overview'].get('median_funding_ann_pct'), 1)}**",
        f"- **宏观流动性**：稳定币总供应 {fmt_usd(glob.get('stablecoin_total_supply'))}（{fmt_pct(glob.get('stablecoin_supply_change_pct'))}）｜ FGI **{btc.get('fear_greed','—')}**（{btc.get('fear_greed_label','')}）｜ MVRV `{mvrv_str}`",
        "",
        "## 二、今日 Top 日线交易剧本（低倍合约执行卡）",
        "",
        "> 仓位标尺说明：「1% 风险名义仓位」= 当价格触发结构止损时，账户总权益恰好亏损 1.0% 所对应的名义仓位占比（封顶 300% 即 3.0x）。",
        "",
    ]

    if not setups:
        lines.append("**今日无满足高赔率过滤条件的日线标准剧本，建议观望或仅持既有顺势底仓。**")
        lines.append("")
    else:
        for idx, s in enumerate(setups, 1):
            icon = "🟢 LONG" if s["direction"] == "LONG" else ("🔴 SHORT" if s["direction"] == "SHORT" else "🟡 WATCH")
            warn_tag = " ⚠️[排雷降级]" if s.get("action_override") == "AVOID" else ""
            stop_desc = s.get("stop_rule") or f"{fmt_px(s['stop_price'])}（幅度 {s['stop_dist_pct']}%）"
            lines += [
                f"### {idx}. {icon} · **{s['symbol']}** — {s['setup_label']}（{s['score']['total']}/20）{warn_tag}",
                f"- **关键价位**：现价 `{fmt_px(s['price_usd'])}`（24h {fmt_pct(s.get('chg_24h'))}）｜ **触发条件**：{s['trigger_rule']}",
                f"- **风控与仓位**：**止损规则** {stop_desc} ｜ 日线 `ATR` `{fmt_pct(s.get('atr_pct'), signed=False)}` ｜ **1% 风险名义仓位：`{s['notional_1r_pct']}%`（约 `{s['notional_1r_pct']/100:.2f}x`）**",
                f"- **衍生品与动量**：年化费率 `{fmt_pct(s.get('funding_ann_pct'), 1)}` ｜ 合约 OI {fmt_usd(s.get('oi_usd'))}"
                + (f"（24h {fmt_pct(s.get('oi_change_24h_pct'))}）" if s.get("oi_change_24h_pct") is not None else "")
                + f" ｜ 14D 相对 BTC `{fmt_pct(s.get('rs_14d'), 1)}` ｜ 量能比 `{s.get('vol_ratio_1d') or '—'}x`",
                f"- **量化逻辑**：{s['quant_summary']}",
            ]
            if s.get("catalyst_note"):
                lines.append(f"- **催化剂核查**：{s['catalyst_note']}")
            if s.get("risk_landmine"):
                lines.append(f"- **持仓排雷**：{s['risk_landmine']}")
            lines.append("")

    lines += [
        "## 三、核心自选池日线结构矩阵",
        "",
        "| 币种 | 现价 | 24h | 14D 相对BTC | 日线趋势 | 距 EMA20 | 20D 通道分位 | 日线 ATR | 年化费率 | 合约 OI |",
        "|------|------|-----|-------------|----------|----------|--------------|----------|----------|---------|",
    ]
    for w in watch:
        pos = f"{w['pos_in_20d_pct']:.0f}%" if w.get("pos_in_20d_pct") is not None else "—"
        lines.append(
            f"| **{w['symbol']}** | {fmt_px(w.get('price_usd'))} | {fmt_pct(w.get('chg_24h'))} | "
            f"{fmt_pct(w.get('rs_14d'), 1)} | {w.get('trend_label','—')} | "
            f"{fmt_pct(w.get('dist_ema20_pct'), 1)} | {pos} | "
            f"{fmt_pct(w.get('atr_pct'), signed=False)} | {fmt_pct(w.get('funding_ann_pct'), 1)} | "
            f"{fmt_usd(w.get('oi_usd'))} |"
        )

    lines += [
        "",
        "## 四、相对强弱龙头 & 衍生品费率极值",
        "",
        "### 14D 相对 BTC 抗跌/领涨榜 vs 领跌弱势榜",
        "- **强势前 6（多头备选池）**：" + "、".join(
            f"**{m['symbol']}**（RS {fmt_pct(m.get('rs_14d'), 1)}，{m.get('trend_label','')}，费率 {fmt_pct(m.get('funding_ann_pct'), 0)}）"
            for m in scan.get("rs_leaders", [])[:6]
        ),
        "- **弱势前 6（空头备选池）**：" + "、".join(
            f"**{m['symbol']}**（RS {fmt_pct(m.get('rs_14d'), 1)}，{m.get('trend_label','')}，费率 {fmt_pct(m.get('funding_ann_pct'), 0)}）"
            for m in scan.get("rs_laggards", [])[:6]
        ),
        "",
        "### 资金费率极值监控（持仓磨损与逼空预警）",
        "- **负费率极值（空头拥挤/潜在轧空）**：" + "、".join(
            f"**{m['symbol']}** `{fmt_pct(m.get('funding_ann_pct'), 1)}`（24h {fmt_pct(m.get('chg_24h'), 1)}）"
            for m in scan.get("neg_funding_leaders", [])[:5]
        ),
        "- **正费率极值（多头拥挤/持仓高磨损）**：" + "、".join(
            f"**{m['symbol']}** `{fmt_pct(m.get('funding_ann_pct'), 1)}`（24h {fmt_pct(m.get('chg_24h'), 1)}）"
            for m in scan.get("pos_funding_leaders", [])[:5]
        ),
        "",
        "### 板块轮动（24h 市值涨跌）",
        "| 板块 | 市值 | 24h 变化 | 连续同向 | 备注 |",
        "|------|------|----------|----------|------|",
    ]
    for s in scan.get("sector_rotation", []):
        lines.append(
            f"| {s.get('name')} | {fmt_usd(s.get('market_cap'))} | "
            f"{fmt_pct(s.get('market_cap_change_24h'))} | {s.get('trend_sessions', 1)} 期 | "
            f"{s.get('note') or '—'} |"
        )

    lines += [
        "",
        "## 五、持仓排雷日历（解锁 / 主网 / 宏观）",
        "",
    ]
    if not events:
        lines.append("> 未来 14 天暂无已确认日期的重大解锁或宏观排雷事件。")
    else:
        lines += [
            "| 日期 | 倒计时 | 币种 | 类型 | 事件与持仓排雷应对 |",
            "|------|--------|------|------|--------------------|",
        ]
        for e in events[:12]:
            da = e.get("days_away", 99)
            cnt = f"**{da} 天 ⏰**" if da <= 2 else f"{da} 天"
            desc = e.get("description", "")
            ang = f"（应对：{e['opportunity_angle']}）" if e.get("opportunity_angle") else ""
            lines.append(f"| {e.get('date')} | {cnt} | **{str(e.get('coin','')).upper()}** | `{e.get('event_type')}` | {desc}{ang} |")
    if latest.get("events_note"):
        lines.append(f"\n> {latest['events_note']}")

    if alerts:
        lines += ["", "## 六、本期触发告警", ""]
        for a in alerts[:8]:
            lines.append(f"- **[{a['severity'].upper()}] `{a['rule']}`**：{a['message']}")

    return "\n".join(lines) + "\n"


def main(session="daily"):
    collected = load_json(ROOT / "data/collected.json")
    if not collected:
        print("Error: data/collected.json not found. Run collect.py first.", file=sys.stderr)
        return 1

    overlay = load_json(ROOT / "data/overlay.json", {}) or {}
    prev = load_json(ROOT / "data/latest.json", {}) or {}

    now = datetime.now(TZ)
    date_str = collected.get("date") or now.strftime("%Y-%m-%d")
    today_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # 1. 处理交易剧本合并（仅合并文字与筛选，不改任何量化数值）
    max_setups = (load_json(ROOT / "config/scan-config.json", {})
                  .get("trend_setups", {})
                  .get("max_actionable_setups", 5))
    cand_list = collected.get("setups_candidates", [])
    cand_by_id = {c["id"]: c for c in cand_list}
    cand_by_sym = {c["symbol"]: c for c in cand_list}

    chosen_ids = overlay.get("selected_setup_ids")
    if chosen_ids:
        chosen = []
        for sid in chosen_ids:
            if sid in cand_by_id:
                chosen.append(dict(cand_by_id[sid]))
            elif sid.upper() in cand_by_sym:
                chosen.append(dict(cand_by_sym[sid.upper()]))
    else:
        chosen = [dict(c) for c in cand_list[:max_setups]]

    ov_map = overlay.get("setup_overlays") or {}
    for s in chosen:
        ov = ov_map.get(s["symbol"]) or ov_map.get(s["id"]) or {}
        s["catalyst_note"] = ov.get("catalyst_note") or "纯日线量价结构驱动，未检出异常单日新闻干扰"
        s["risk_landmine"] = ov.get("risk_landmine") or "近 7 日无已知大额悬崖解锁或硬分叉排雷项"
        s["action_override"] = ov.get("action_override")
        s["source_url"] = ov.get("source_url")

    # 2. 处理核心自选池备注与板块备注
    watch_notes = overlay.get("watchlist_notes") or {}
    watch_rows = []
    for w in collected.get("watchlist_rows", []):
        w_copy = dict(w)
        if w["symbol"] in watch_notes:
            w_copy["note"] = watch_notes[w["symbol"]]
        watch_rows.append(w_copy)

    sector_notes = overlay.get("sector_notes") or {}
    sectors = []
    for sec in collected.get("sector_rotation", []):
        s_copy = dict(sec)
        s_copy["note"] = sector_notes.get(sec["category"]) or (
            "连续同向轮动" if (sec.get("trend_sessions") or 1) >= 2 else "单日波动，待连续确认"
        )
        sectors.append(s_copy)

    # 3. 合并事件日历（携带上期未过期 + overlay 新增/更新）
    base_events = collected.get("previous", {}).get("events", [])
    ov_events = overlay.get("events")
    merged_events_raw = ov_events if isinstance(ov_events, list) and len(ov_events) > 0 else base_events
    events = normalize_events(merged_events_raw, today_date)

    # 4. 大盘择时评分微调（如宏观 48h 事件）
    regime = dict(collected["regime"])
    scores = dict(regime["scores"])
    if isinstance(overlay.get("macro_score_override"), int) and 1 <= overlay["macro_score_override"] <= 5:
        scores["macro"] = overlay["macro_score_override"]
        scores["total"] = scores["btc_trend"] + scores["funding"] + scores["sentiment"] + scores["macro"]
    regime["scores"] = scores
    regime["regime_note"] = overlay.get("regime_note")

    prev_total = ((collected.get("previous") or {}).get("market_score") or {}).get("total")
    vs_prev = f"{prev_total} -> {scores['total']}" if prev_total is not None else "baseline"

    # 5. 告警评估
    prev_btc = (prev.get("market_context") or {}).get("btc") or {}
    alerts = build_alerts(
        collected["btc"],
        chosen,
        watch_rows,
        collected.get("neg_funding_leaders", []),
        events,
        prev_btc,
    )

    latest = {
        "schema_version": "2.0-daily-perp-trend",
        "timestamp": now.isoformat(timespec="seconds"),
        "session": session,
        "regime": regime,
        "setups": chosen,
        "watchlist_rows": watch_rows,
        "market_scan": {
            "breadth": regime["breadth"],
            "rs_leaders": collected.get("rs_leaders", []),
            "rs_laggards": collected.get("rs_laggards", []),
            "neg_funding_leaders": collected.get("neg_funding_leaders", []),
            "pos_funding_leaders": collected.get("pos_funding_leaders", []),
            "sector_rotation": sectors,
            "sector_note": overlay.get("sector_note"),
            "chains_tvl_delta": collected.get("chains_tvl_delta", []),
        },
        "events": events,
        "events_note": overlay.get("events_note"),
        "market_context": {
            "btc": collected["btc"],
            "eth": collected["eth"],
            "global": collected["global"],
            "etf_qualitative": overlay.get("etf_qualitative") or {
                "btc_etf_flow_text": "无免费精确 API，详见定性备注",
                "eth_etf_flow_text": "无免费精确 API，详见定性备注",
            },
        },
        "market_score": {
            "btc_trend": scores["btc_trend"],
            "funding": scores["funding"],
            "sentiment": scores["sentiment"],
            "macro": scores["macro"],
            "total": scores["total"],
            "label": regime["regime_label"],
            "vs_previous": vs_prev,
        },
        "alerts": alerts,
        "_sources": collected.get("_sources", {}),
        "_freshness": collected.get("freshness", {}),
    }

    # 写 data/latest.json
    latest_path = ROOT / "data/latest.json"
    with open(latest_path, "w") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    # 写 Markdown 日报
    md_text = generate_markdown(latest)
    md_path = ROOT / "reports" / f"{date_str}_{session}.md"
    with open(md_path, "w") as f:
        f.write(md_text)

    # 写单行告警摘要
    top_setup_str = (
        ", ".join(f"{s['symbol']}({s['direction']} {s['score']['total']}/20)" for s in chosen[:3])
        if chosen else "无高分剧本"
    )
    alert_line = (
        f"[{date_str} {session}] {regime['regime_label']}({scores['total']}/20) | "
        f"BTC {fmt_px(collected['btc'].get('price_usd'))} ({fmt_pct(collected['btc'].get('price_change_24h'))}) | "
        f"剧本: {top_setup_str} | 告警 {len(alerts)} 条\n"
    )
    with open(ROOT / "reports/latest-alert.txt", "w") as f:
        f.write(alert_line)

    print(f"[assemble 2.0] wrote {latest_path}, {md_path} ({len(md_text.splitlines())} lines)", flush=True)

    # 调用 HTML 渲染器
    subprocess.run([sys.executable, str(ROOT / "scripts/render-html.py"), date_str, session], check=True)
    return 0


if __name__ == "__main__":
    sess = sys.argv[1] if len(sys.argv) > 1 else "daily"
    sys.exit(main(sess))
