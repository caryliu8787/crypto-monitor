#!/usr/bin/env python3
"""crypto-monitor 2.0 HTML 渲染器（读取 data/latest.json + templates/dashboard.html）。

用法: python3 scripts/render-html.py [YYYY-MM-DD] [session]
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))

SEVERITY_STYLE = {
    "critical": ("alert-box", "🔴 关键结构/剧本告警"),
    "warning": ("alert-box warning", "🟡 持仓与费率预警"),
    "info": ("alert-box info", "🔵 前瞻排雷提示"),
}


def esc(text):
    if text is None:
        return ""
    t = str(text)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" style="color:var(--accent);">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


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


def pct_span(v, digits=2):
    if v is None:
        return "—"
    cls = "up" if v >= 0 else "down"
    return f'<span class="{cls}">{fmt_pct(v, digits)}</span>'


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


def render_alerts(alerts):
    if not alerts:
        return ""
    groups = {}
    for a in alerts:
        sev = a.get("severity", "info")
        groups.setdefault(sev, []).append(a)
    out = []
    for sev in ("critical", "warning", "info"):
        if sev not in groups:
            continue
        cls, title = SEVERITY_STYLE[sev]
        lis = "".join(f'<li><code>{esc(a.get("rule",""))}</code> — {esc(a.get("message",""))}</li>' for a in groups[sev])
        out.append(f'<div class="{cls}"><strong>{title}（{len(groups[sev])}）</strong><ul style="margin:6px 0 0;padding-left:18px;">{lis}</ul></div>')
    return "\n".join(out)


def render_regime(reg, btc, eth, glob):
    sc = reg.get("scores", {})
    code = reg.get("regime_code", "")
    cls = "bull" if "BULL" in code else ("bear" if "BEAR" in code else "chop")
    note = f'<div style="margin-top:8px;font-size:13px;color:var(--text-secondary);">{esc(reg["regime_note"])}</div>' if reg.get("regime_note") else ""
    banner = (
        f'<div class="regime-banner {cls}">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;">'
        f'<div style="font-size:20px;font-weight:700;">{esc(reg.get("regime_label", "—"))} '
        f'<span style="font-size:15px;color:var(--text-secondary);">({sc.get("total","—")}/20)</span></div>'
        f'<div style="font-size:12px;color:var(--text-secondary);">'
        f'BTC趋势 {sc.get("btc_trend","—")}/5 · 广度资金 {sc.get("funding","—")}/5 · '
        f'情绪费率 {sc.get("sentiment","—")}/5 · 宏观 {sc.get("macro","—")}/5</div></div>'
        f'<div style="margin-top:8px;font-size:14px;"><strong>操作准则：</strong>{esc(reg.get("posture",""))}</div>'
        f'{note}</div>'
    )

    br = reg.get("breadth", {})
    deriv = reg.get("derivatives_overview", {})
    kpis = [
        ("BTC 现价 / 趋势", fmt_px(btc.get("price_usd")),
         f'{pct_span(btc.get("price_change_24h"))} · {esc(btc.get("trend_label","—"))} (EMA20 {fmt_px(btc.get("ema20"))})'),
        ("ETH 现价 / 汇率", fmt_px(eth.get("price_usd")),
         f'{pct_span(eth.get("chg_24h"))} · ETH/BTC {eth.get("eth_btc_ratio") or "—"}'),
        ("合约站上日线 EMA20", f'{br.get("pct_above_ema20","—")}%',
         f'{br.get("above_ema20",0)}/{br.get("universe_count",0)} 币 · 站上EMA50 {br.get("pct_above_ema50","—")}%'),
        ("衍生品中位年化费率", fmt_pct(deriv.get("median_funding_ann_pct"), 1),
         f'主流池总 OI {fmt_usd(deriv.get("universe_total_oi_usd"))}'),
        ("稳定币总供应 / FGI", fmt_usd(glob.get("stablecoin_total_supply")),
         f'环比 {fmt_pct(glob.get("stablecoin_supply_change_pct"))} · FGI {btc.get("fear_greed","—")} ({esc(btc.get("fear_greed_label",""))})'),
    ]
    kpi_html = "".join(
        f'<div class="kpi-box"><div class="k-label">{k[0]}</div>'
        f'<div class="k-val">{k[1]}</div><div class="k-sub">{k[2]}</div></div>'
        for k in kpis
    )
    return banner, kpi_html


def render_setups(setups):
    if not setups:
        return '<div class="card"><div class="muted">今日无满足高赔率过滤条件的日线标准剧本，建议观望或维持既有顺势仓位。</div></div>'
    cards = []
    for idx, s in enumerate(setups, 1):
        d = s.get("direction", "WATCH")
        avoid = s.get("action_override") == "AVOID"
        badge_txt = f"{d} · 排雷规避" if avoid else d
        sc = s.get("score", {})
        src_html = (
            f' <a href="{esc(s["source_url"])}" style="font-size:12px;color:var(--accent);">[信源]</a>'
            if s.get("source_url") else ""
        )
        cards.append(
            f'<div class="setup-card {d}">'
            f'<div class="setup-top">'
            f'<div><span class="dir-badge {d}">{badge_txt}</span> '
            f'<strong style="font-size:17px;margin-left:6px;">{idx}. {esc(s["symbol"])}</strong> '
            f'<span style="font-size:14px;color:var(--text-secondary);">— {esc(s.get("setup_label",""))}</span></div>'
            f'<div style="font-size:12px;color:var(--text-secondary);">'
            f'量化评分 <strong>{sc.get("total","—")}/20</strong> '
            f'(结构{sc.get("structure","—")} 动量{sc.get("momentum","—")} 拥挤{sc.get("crowding","—")} 赔率{sc.get("risk_reward","—")})</div>'
            f'</div>'
            f'<div class="setup-metrics">'
            f'<div class="m-item"><div class="m-lbl">当前价 (24h)</div><div class="m-num">{fmt_px(s.get("price_usd"))} {pct_span(s.get("chg_24h"), 1)}</div></div>'
            f'<div class="m-item"><div class="m-lbl">参考触发位</div><div class="m-num">{fmt_px(s.get("trigger_price"))}</div></div>'
            f'<div class="m-item"><div class="m-lbl">日线结构止损</div><div class="m-num">{fmt_px(s.get("stop_price"))} <span class="down">(-{s.get("stop_dist_pct")}%)</span></div></div>'
            f'<div class="m-item"><div class="m-lbl">日线 ATR(14)</div><div class="m-num">{fmt_pct(s.get("atr_pct"), 2, False)}</div></div>'
            f'<div class="m-item"><div class="m-lbl">年化资金费率</div><div class="m-num">{pct_span(s.get("funding_ann_pct"), 1)}</div></div>'
            f'<div class="m-item"><div class="m-lbl">1%风险建议仓位</div><div class="m-num" style="color:var(--accent);">{s.get("notional_1r_pct")}% ({(s.get("notional_1r_pct") or 0)/100:.2f}x)</div></div>'
            f'</div>'
            f'<div class="setup-lines">'
            f'<div><strong>触发执行：</strong>{esc(s.get("trigger_rule",""))}</div>'
            f'<div><strong>证伪止损：</strong>{esc(s.get("stop_rule",""))}</div>'
            f'<div><strong>量化结构：</strong>{esc(s.get("quant_summary",""))}（合约 OI {fmt_usd(s.get("oi_usd"))}，24h 成交 {fmt_usd(s.get("perp_vol_24h_usd"))}）</div>'
            f'<div><strong>催化核查：</strong>{esc(s.get("catalyst_note",""))}{src_html}</div>'
            f'<div><strong>持仓排雷：</strong>{esc(s.get("risk_landmine",""))}</div>'
            f'</div></div>'
        )
    return "\n".join(cards)


def render_watchlist(rows):
    if not rows:
        return '<div class="muted">自选池为空</div>'
    trs = []
    for w in rows:
        ts = w.get("trend_state", "RANGE_CHOP")
        pos = f'{w["pos_in_20d_pct"]:.0f}%' if w.get("pos_in_20d_pct") is not None else "—"
        note = f'<div style="font-size:11px;color:var(--text-secondary);">{esc(w["note"])}</div>' if w.get("note") else ""
        trs.append(
            f'<tr>'
            f'<td><strong>{esc(w["symbol"])}</strong>{note}</td>'
            f'<td>{fmt_px(w.get("price_usd"))}</td>'
            f'<td>{pct_span(w.get("chg_24h"))}</td>'
            f'<td>{pct_span(w.get("rs_14d"), 1)}</td>'
            f'<td><span class="trend-pill {ts}">{esc(w.get("trend_label","—"))}</span></td>'
            f'<td>{fmt_px(w.get("ema20"))} ({pct_span(w.get("dist_ema20_pct"), 1)})</td>'
            f'<td>{pos}</td>'
            f'<td>{fmt_pct(w.get("atr_pct"), 2, False)}</td>'
            f'<td>{pct_span(w.get("funding_ann_pct"), 1)}</td>'
            f'<td>{fmt_usd(w.get("oi_usd"))}</td>'
            f'</tr>'
        )
    return (
        '<table class="data-table"><thead><tr>'
        '<th>币种</th><th>现价</th><th>24h</th><th>14D相对BTC</th><th>日线结构</th>'
        '<th>EMA20 (偏离)</th><th>20D分位</th><th>ATR%</th><th>年化费率</th><th>合约OI</th>'
        '</tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
    )


def render_mini_coin_table(rows, mode="rs"):
    if not rows:
        return '<div class="muted">数据暂缺</div>'
    trs = []
    for m in rows[:6]:
        ts = m.get("trend_state", "RANGE_CHOP")
        if mode == "rs":
            col3 = pct_span(m.get("rs_14d"), 1)
            col4 = f'<span class="trend-pill {ts}">{esc(m.get("trend_label",""))}</span>'
        else:
            col3 = pct_span(m.get("funding_ann_pct"), 1)
            col4 = fmt_usd(m.get("oi_usd"))
        trs.append(
            f'<tr><td><strong>{esc(m["symbol"])}</strong></td>'
            f'<td>{fmt_px(m.get("price_usd"))} ({pct_span(m.get("chg_24h"), 1)})</td>'
            f'<td>{col3}</td><td>{col4}</td></tr>'
        )
    hdr3, hdr4 = ("14D RS", "趋势") if mode == "rs" else ("年化费率", "合约OI")
    return (
        f'<table class="data-table"><thead><tr><th>币种</th><th>现价 (24h)</th>'
        f'<th>{hdr3}</th><th>{hdr4}</th></tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
    )


def render_sectors(sectors):
    if not sectors:
        return '<div class="muted">数据暂缺</div>'
    trs = []
    for s in sectors:
        trs.append(
            f'<tr><td><strong>{esc(s.get("name") or s.get("category"))}</strong></td>'
            f'<td>{fmt_usd(s.get("market_cap"))}</td>'
            f'<td>{pct_span(s.get("market_cap_change_24h"))}</td>'
            f'<td>{s.get("trend_sessions", 1)} 期</td>'
            f'<td class="wrap muted">{esc(s.get("note") or "")}</td></tr>'
        )
    return (
        '<table class="data-table"><thead><tr><th>板块</th><th>市值</th><th>24h变化</th>'
        '<th>连续同向</th><th>备注</th></tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
    )


def render_events(events):
    if not events:
        return '<div class="muted">未来 14 天暂无已确认日期的重大排雷事件</div>'
    trs = []
    for e in events[:12]:
        da = e.get("days_away", 99)
        if da <= 0:
            cd = '<span class="warn"><strong>⏰ 今天</strong></span>'
        elif da <= 2:
            cd = f'<span class="warn"><strong>⏰ {da} 天</strong></span>'
        else:
            cd = f"{da} 天"
        trs.append(
            f'<tr><td>{esc(e.get("date"))}</td><td>{cd}</td>'
            f'<td><strong>{esc(str(e.get("coin","")).upper())}</strong></td>'
            f'<td><code>{esc(e.get("event_type"))}</code></td>'
            f'<td class="wrap">{esc(e.get("description"))}</td>'
            f'<td class="wrap muted">{esc(e.get("opportunity_angle") or "")}</td></tr>'
        )
    return (
        '<table class="data-table"><thead><tr><th>日期</th><th>倒计时</th><th>币种</th>'
        '<th>类型</th><th>事件详情</th><th>持仓应对</th></tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
    )


def render(date=None, session="daily"):
    d = json.load(open(ROOT / "data/latest.json"))
    tpl = open(ROOT / "templates/dashboard.html").read()

    ts = d.get("timestamp", "")
    date = date or ts[:10] or datetime.now(TZ).strftime("%Y-%m-%d")
    session = d.get("session", session)

    reg = d.get("regime", {})
    mc = d.get("market_context", {})
    btc = mc.get("btc", {})
    eth = mc.get("eth", {})
    glob = mc.get("global", {})
    scan = d.get("market_scan", {})

    banner_html, kpis_html = render_regime(reg, btc, eth, glob)

    ph = {
        "report_date": date,
        "report_session": session,
        "closed_candle_date": btc.get("last_closed_date") or "—",
        "report_timestamp": ts.replace("T", " ")[:16] + " UTC+8" if ts else "",
        "alerts_html": render_alerts(d.get("alerts")),
        "regime_banner_html": banner_html,
        "regime_kpis_html": kpis_html,
        "btc_20d_range": f'{fmt_px(btc.get("donchian_20d_low"))} – {fmt_px(btc.get("donchian_20d_high"))}',
        "btc_atr_text": f'{fmt_px(btc.get("atr14"))} ({fmt_pct(btc.get("atr_pct"), 2, False)})',
        "btc_chart_json": json.dumps(btc.get("chart_60d") or {}),
        "setups_html": render_setups(d.get("setups")),
        "watchlist_table_html": render_watchlist(d.get("watchlist_rows")),
        "rs_leaders_html": render_mini_coin_table(scan.get("rs_leaders"), "rs"),
        "rs_laggards_html": render_mini_coin_table(scan.get("rs_laggards"), "rs"),
        "neg_funding_html": render_mini_coin_table(scan.get("neg_funding_leaders"), "fr"),
        "pos_funding_html": render_mini_coin_table(scan.get("pos_funding_leaders"), "fr"),
        "sector_rotation_html": render_sectors(scan.get("sector_rotation")),
        "sector_note_html": f'<div class="note-box">{esc(scan["sector_note"])}</div>' if scan.get("sector_note") else "",
        "event_calendar_html": render_events(d.get("events")),
        "events_note_html": f'<div class="note-box">{esc(d["events_note"])}</div>' if d.get("events_note") else "",
    }

    html = tpl
    for k, v in ph.items():
        html = html.replace("{{" + k + "}}", str(v))

    leftover = re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", html)
    if leftover:
        print(f"[render 2.0] WARNING leftover placeholders: {sorted(set(leftover))}", flush=True)

    out_path = ROOT / "reports" / f"{date}_{session}.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"[render 2.0] done -> {out_path} ({len(html)} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(render(sys.argv[1] if len(sys.argv) > 1 else None,
                    sys.argv[2] if len(sys.argv) > 2 else "daily"))
