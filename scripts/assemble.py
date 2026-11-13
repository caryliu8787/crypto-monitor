#!/usr/bin/env python3
"""crypto-monitor 2.0 报告组装器（确定性合并 collected.json + overlay.json）。

职责：
1. 从 data/collected.json 读取全部精确量化指标（严禁 overlay 覆盖任何数值字段）
2. 从 data/overlay.json 合并定性排雷备注（catalyst_note / risk_landmine / events / regime_note）
3. 自动评估日线趋势告警规则（BTC 通道/均线破位、高分剧本、负费率逼空、拥挤偏离、48h/7d 事件排雷）
4. 生成：
   - data/latest.json
   - reports/YYYY-MM-DD_daily.md（高可读性实战日线交易早报）
   - reports/latest-alert.txt
5. 自动调用 scripts/render-html.py 产出交互式 HTML 仪表盘

用法: python3 scripts/assemble.py [daily]
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))

EVENT_TYPE_CN = {
    "unlock": "代币解锁",
    "upgrade": "主网升级",
    "macro": "宏观节点",
}


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

    bp = btc.get("price_usd")
    d20h = btc.get("donchian_20d_high")
    d20l = btc.get("donchian_20d_low")
    if bp and d20h and bp >= d20h * 0.998:
        alerts.append({
            "severity": "critical",
            "rule": "btc_20d_channel_break",
            "message": f"BTC 突破日线 20 日高点 {fmt_px(d20h)}（现价 {fmt_px(bp)}），多头趋势共振",
        })
    elif bp and d20l and bp <= d20l * 1.003:
        alerts.append({
            "severity": "critical",
            "rule": "btc_20d_channel_break",
            "message": f"BTC 跌破近 20 日低点 {fmt_px(d20l)}（现价 {fmt_px(bp)}），下行寻底阶段严控多单仓位",
        })

    ema50 = btc.get("ema50")
    prev_p = (prev_btc or {}).get("price_usd")
    if bp and ema50 and prev_p:
        if prev_p >= ema50 > bp:
            alerts.append({
                "severity": "warning",
                "rule": "btc_ema50_cross",
                "message": f"BTC 失守日线 50 日均线（{fmt_px(ema50)}），中期趋势转弱",
            })
        elif prev_p <= ema50 < bp:
            alerts.append({
                "severity": "warning",
                "rule": "btc_ema50_cross",
                "message": f"BTC 收复日线 50 日均线（{fmt_px(ema50)}），中期结构修复",
            })

    for s in setups:
        if s.get("direction") in ("LONG", "SHORT") and s.get("action_override") != "AVOID" and s["score"]["total"] >= 16:
            alerts.append({
                "severity": "critical",
                "rule": "high_conviction_setup",
                "message": (
                    f"高分剧本：{s['symbol']} {s['direction']} · {s['setup_label']}（{s['score']['total']}/20）"
                    f" — 进场参考 {fmt_px(s['trigger_price'])} / 止损 {fmt_px(s['stop_price'])}"
                ),
            })

    for m in neg_leaders[:3]:
        fr = m.get("funding_ann_pct")
        chg = m.get("chg_24h") or 0
        if fr is not None and fr <= -25.0 and chg >= 1.5:
            alerts.append({
                "severity": "warning",
                "rule": "perp_short_squeeze",
                "message": f"负费率逼空：{m['symbol']} 年化费率 {fr:+.1f}% 且 24h {chg:+.2f}%，空头拥挤勿盲目摸顶",
            })

    for w in enriched_watch:
        datr = w.get("dist_ema20_atr")
        fr = w.get("funding_ann_pct") or 0
        if datr is not None and (abs(datr) >= 3.0 or abs(fr) >= 60.0):
            alerts.append({
                "severity": "warning",
                "rule": "perp_crowded_extension",
                "message": f"{w['symbol']} 短线偏离 20 日均线达 {datr:+.1f} 倍波幅（ATR），切忌顺向追单",
            })

    for e in events:
        da = e.get("days_away", 99)
        t_cn = EVENT_TYPE_CN.get(e.get("event_type"), e.get("event_type", "事件"))
        if 0 <= da <= 2:
            alerts.append({
                "severity": "warning",
                "rule": "event_within_48h",
                "message": f"48h 内排雷：{str(e.get('coin','')).upper()} {t_cn}（{e.get('date')}）— {e.get('description','')}",
            })
        elif 3 <= da <= 7 and e.get("event_type") == "unlock":
            alerts.append({
                "severity": "info",
                "rule": "major_unlock_headwind",
                "message": f"7天内解锁：{str(e.get('coin','')).upper()}（{e.get('date')}，剩 {da} 天）— {e.get('description','')}",
            })

    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: sev_rank.get(a.get("severity"), 3))
    return alerts


def generate_markdown(latest):
    date = latest["timestamp"][:10]
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

    mvrv_val = btc.get("mvrv_ratio")
    mvrv_str = f"{mvrv_val:.2f}" if isinstance(mvrv_val, (int, float)) else (mvrv_val or "—")

    action_setups = [s for s in setups if s.get("direction") in ("LONG", "SHORT")]
    watch_setups = [s for s in setups if s.get("direction") == "WATCH"]

    lines = [
        f"# 加密货币日线合约趋势早报（{date}）",
        "",
        f"> 生成时间：{latest['timestamp'][:16].replace('T', ' ')} (UTC+8) ｜ 日线收盘基准：{btc.get('last_closed_date', '—')} 00:00 UTC",
        "",
        "## 一、今日大盘总纲：能不能做？仓位开多大？",
        "",
        f"- **市场环境**：**{reg['regime_label']}（{sc['total']}/20 分）** ｜ 恐慌贪婪指数 **{btc.get('fear_greed','—')}**（{btc.get('fear_greed_label','')}）",
        f"- **今日行动准则**：{reg['posture']}",
    ]
    if reg.get("regime_note"):
        lines.append(f"- **盘面解读**：{reg['regime_note']}")

    lines += [
        "",
        "| 核心基准 | 现价 (24h) | 日线趋势状态 | 关键均线参考 | 20日高低区间 | 日均波幅 (ATR) | 年化资金费率 |",
        "|----------|------------|--------------|--------------|--------------|----------------|--------------|",
        f"| **BTC** | **{fmt_px(btc.get('price_usd'))}** ({fmt_pct(btc.get('price_change_24h'), 1)}) | {btc.get('trend_label','—')} | 20日均线 {fmt_px(btc.get('ema20'))} / 200日均线 {fmt_px(btc.get('ema200'))} | {fmt_px(btc.get('donchian_20d_low'))} ~ {fmt_px(btc.get('donchian_20d_high'))} | {fmt_px(btc.get('atr14'))} ({fmt_pct(btc.get('atr_pct'), 1, False)}) | {fmt_pct(btc.get('funding_ann_pct'), 1)} |",
        f"| **ETH** | **{fmt_px(eth.get('price_usd'))}** ({fmt_pct(eth.get('chg_24h'), 1)}) | {eth.get('trend_label','—')} | 20日均线 {fmt_px(eth.get('ema20'))} / 50日均线 {fmt_px(eth.get('ema50'))} | ETH/BTC 汇率 `{eth.get('eth_btc_ratio') or '—'}` | — | — |",
        "",
        f"- **市场广度与资金**：52 个主流合约中仅 **{br['above_ema20']} 个（{br['pct_above_ema20']}%）** 站上 20 日均线 ｜ 中位年化费率 **{fmt_pct(reg['derivatives_overview'].get('median_funding_ann_pct'), 1)}** ｜ 稳定币总市值 {fmt_usd(glob.get('stablecoin_total_supply'))} ｜ MVRV `{mvrv_str}`",
        "",
        "---",
        "",
        "## 二、今日交易计划",
        "",
        "### 🎯 可执行方向单（挂单 / 企稳介入）",
        "",
    ]

    if not action_setups:
        lines.append("> 今日无满足高胜率过滤条件的直接做多/做空日线信号，建议空仓等待或只盯下方变盘观察池。")
        lines.append("")
    else:
        for idx, s in enumerate(action_setups, 1):
            dir_cn = "🟢 做多 LONG" if s["direction"] == "LONG" else "🔴 做空 SHORT"
            warn_tag = " ⚠️【排雷规避】" if s.get("action_override") == "AVOID" else ""
            lev = (s.get("notional_1r_pct") or 0) / 100.0
            lines += [
                f"#### {idx}. {dir_cn} · **{s['symbol']}**（{s['setup_label']} · 评分 {s['score']['total']}/20）{warn_tag}",
                "",
                f"- **怎么进场**：{s['trigger_rule']}（当前价 `{fmt_px(s['price_usd'])}`，24h `{fmt_pct(s.get('chg_24h'), 1)}`）",
                f"- **错了在哪砍**：{s['stop_rule']}",
                f"- **建议开多大**：**名义仓位不超过本金的 `{s['notional_1r_pct']}%`（即 `{lev:.2f}x` 杠杆）** —— 按触及止损最多亏损总资金 1% 反推",
                f"- **为什么选它**：{s.get('catalyst_note') or s.get('quant_summary')}",
                f"- **持仓排雷**：{s.get('risk_landmine')}（年化费率 `{fmt_pct(s.get('funding_ann_pct'), 1)}` · 14天相对BTC `{fmt_pct(s.get('rs_14d'), 1)}` · 合约持仓 {fmt_usd(s.get('oi_usd'))}）",
                "",
            ]

    if watch_setups:
        lines += [
            "### 👀 蓄势待变盘观察池（区间极度收敛，突破前勿提前猜方向）",
            "",
            "| 币种 | 现价 (24h) | 向上突破做多位 | 向下跌破做空位 | 收敛状态与关注逻辑 |",
            "|------|------------|----------------|----------------|--------------------|",
        ]
        for s in watch_setups:
            d20h = fmt_px(s.get("donchian_20d_high") or s.get("trigger_price"))
            d20l = fmt_px(s.get("donchian_20d_low"))
            why = s.get("catalyst_note") or s.get("quant_summary") or ""
            lines.append(
                f"| **{s['symbol']}** | {fmt_px(s.get('price_usd'))} ({fmt_pct(s.get('chg_24h'), 1)}) | "
                f"**站稳 {d20h}** | **跌破 {d20l}** | {why} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 三、核心自选池日线体检",
        "",
        "| 币种 | 现价 (24h) | 日线趋势 | 距20日均线 | 20日区间位置 | 日均波幅(ATR) | 年化费率 | 合约持仓(OI) |",
        "|------|------------|----------|------------|--------------|---------------|----------|--------------|",
    ]
    for w in watch:
        pos = f"{w['pos_in_20d_pct']:.0f}%" if w.get("pos_in_20d_pct") is not None else "—"
        lines.append(
            f"| **{w['symbol']}** | {fmt_px(w.get('price_usd'))} ({fmt_pct(w.get('chg_24h'), 1)}) | "
            f"{w.get('trend_label','—')} | {fmt_pct(w.get('dist_ema20_pct'), 1)} (均线 {fmt_px(w.get('ema20'))}) | "
            f"{pos} | {fmt_pct(w.get('atr_pct'), 1, signed=False)} | {fmt_pct(w.get('funding_ann_pct'), 1)} | "
            f"{fmt_usd(w.get('oi_usd'))} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 四、强弱选币与资金费率雷达",
        "",
        "- **🚀 抗跌领涨前 6（行情企稳首选做多）**：" + "、".join(
            f"**{m['symbol']}**（跑赢BTC {fmt_pct(m.get('rs_14d'), 1)}，{m.get('trend_label','')}）"
            for m in scan.get("rs_leaders", [])[:6]
        ),
        "- **🩸 领跌弱势前 6（反抽均线首选做空）**：" + "、".join(
            f"**{m['symbol']}**（跑输BTC {fmt_pct(m.get('rs_14d'), 1)}，{m.get('trend_label','')}）"
            for m in scan.get("rs_laggards", [])[:6]
        ),
        "- **🔥 空头拥挤负费率（提防逼空反弹）**：" + "、".join(
            f"**{m['symbol']}**（年化 `{fmt_pct(m.get('funding_ann_pct'), 1)}`，24h {fmt_pct(m.get('chg_24h'), 1)}）"
            for m in scan.get("neg_funding_leaders", [])[:5]
        ),
        "- **⚠️ 多头拥挤高费率（持仓成本偏高）**：" + "、".join(
            f"**{m['symbol']}**（年化 `{fmt_pct(m.get('funding_ann_pct'), 1)}`，24h {fmt_pct(m.get('chg_24h'), 1)}）"
            for m in scan.get("pos_funding_leaders", [])[:5]
        ),
        "",
        "---",
        "",
        "## 五、未来持仓排雷日历（解锁 / 升级 / 宏观）",
        "",
    ]

    if not events:
        lines.append("> 未来 14 天暂无已确认日期的重大解锁或宏观排雷事件。")
    else:
        lines += [
            "| 日期 | 倒计时 | 标的 | 类型 | 事件说明与应对建议 |",
            "|------|--------|------|------|--------------------|",
        ]
        for e in events[:12]:
            da = e.get("days_away", 99)
            cnt = f"**⏰ {da} 天**" if da <= 3 else f"{da} 天"
            t_cn = EVENT_TYPE_CN.get(e.get("event_type"), e.get("event_type", "事件"))
            desc = e.get("description", "")
            ang = f" **应对：{e['opportunity_angle']}**" if e.get("opportunity_angle") else ""
            lines.append(f"| {e.get('date')} | {cnt} | **{str(e.get('coin','')).upper()}** | {t_cn} | {desc}{ang} |")
    if latest.get("events_note"):
        lines.append(f"\n> {latest['events_note']}")

    return "\n".join(lines) + "\n"


def enrich_setup_channels(s, collected):
    """确保每条 setup 均带有 donchian_20d_high / donchian_20d_low 字段。"""
    if s.get("donchian_20d_high") is not None and s.get("donchian_20d_low") is not None:
        return
    sym = s.get("symbol")
    for pool_key in ("watchlist_rows", "rs_leaders", "rs_laggards", "neg_funding_leaders", "pos_funding_leaders"):
        for m in collected.get(pool_key) or []:
            if m.get("symbol") == sym and m.get("donchian_20d_high") is not None:
                s["donchian_20d_high"] = m.get("donchian_20d_high")
                s["donchian_20d_low"] = m.get("donchian_20d_low")
                s.setdefault("bb_width_pctile", m.get("bb_width_pctile"))
                return
    # 从 trigger_rule 解析双向突破高低点兜底
    nums = re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", s.get("trigger_rule") or "")
    if len(nums) >= 2 and s.get("direction") == "WATCH":
        s["donchian_20d_high"] = float(nums[0])
        s["donchian_20d_low"] = float(nums[1])


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
        enrich_setup_channels(s, collected)
        ov = ov_map.get(s["symbol"]) or ov_map.get(s["id"]) or {}
        s["catalyst_note"] = ov.get("catalyst_note") or "纯日线量价结构驱动，无异常单日消息干扰"
        s["risk_landmine"] = ov.get("risk_landmine") or "近 7 日无已知大额悬崖解锁或硬分叉排雷项"
        s["action_override"] = ov.get("action_override")
        s["source_url"] = ov.get("source_url")

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

    base_events = collected.get("previous", {}).get("events", [])
    ov_events = overlay.get("events")
    merged_events_raw = ov_events if isinstance(ov_events, list) and len(ov_events) > 0 else base_events
    events = normalize_events(merged_events_raw, today_date)

    regime = dict(collected["regime"])
    scores = dict(regime["scores"])
    if isinstance(overlay.get("macro_score_override"), int) and 1 <= overlay["macro_score_override"] <= 5:
        scores["macro"] = overlay["macro_score_override"]
        scores["total"] = scores["btc_trend"] + scores["funding"] + scores["sentiment"] + scores["macro"]
    regime["scores"] = scores
    regime["regime_note"] = overlay.get("regime_note")

    prev_total = ((collected.get("previous") or {}).get("market_score") or {}).get("total")
    vs_prev = f"{prev_total} -> {scores['total']}" if prev_total is not None else "baseline"

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

    latest_path = ROOT / "data/latest.json"
    with open(latest_path, "w") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    md_text = generate_markdown(latest)
    md_path = ROOT / "reports" / f"{date_str}_{session}.md"
    with open(md_path, "w") as f:
        f.write(md_text)

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

    subprocess.run([sys.executable, str(ROOT / "scripts/render-html.py"), date_str, session], check=True)
    return 0


if __name__ == "__main__":
    sess = sys.argv[1] if len(sys.argv) > 1 else "daily"
    sys.exit(main(sess))
