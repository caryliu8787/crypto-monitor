#!/usr/bin/env python3
"""crypto-monitor 2.0 高可读性 HTML 渲染器（读取 data/latest.json + templates/dashboard.html）。

用法: python3 scripts/render-html.py [YYYY-MM-DD] [session]
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))

EVENT_BADGE = {
    "unlock": ("unlock", "🔓 代币解锁"),
    "upgrade": ("upgrade", "🚀 主网升级"),
    "macro": ("macro", "🏛️ 宏观节点"),
}

FGI_CN = {
    "Extreme Fear": "极度恐慌",
    "Fear": "恐慌",
    "Neutral": "中性",
    "Greed": "贪婪",
    "Extreme Greed": "极度贪婪",
}


def esc(text):
    if text is None:
        return ""
    t = str(text)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" style="color:var(--accent);">\1</a>', t)
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


def fmt_pct(v, digits=1, signed=True):
    if v is None:
        return "—"
    if signed:
        return f"+{v:.{digits}f}%" if v >= 0 else f"{v:.{digits}f}%"
    return f"{v:.{digits}f}%"


def pct_span(v, digits=1):
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


def render_regime_hero(reg, btc, eth, glob, alerts):
    sc = reg.get("scores", {})
    code = reg.get("regime_code", "")
    cls = "bull" if "BULL" in code else ("bear" if "BEAR" in code else "chop")
    icon = "🟢" if cls == "bull" else ("🔴" if cls == "bear" else "🟡")

    note_html = (
        f'<div class="hero-note"><strong>盘面重点解读：</strong>{esc(reg["regime_note"])}</div>'
        if reg.get("regime_note") else ""
    )

    # 只提取真正需要置顶提醒的 1~3 条盘面风险（过滤掉与下方卡片重复的 high_conviction_setup 噪音）
    key_alerts = [
        a for a in (alerts or [])
        if a.get("rule") in ("btc_20d_channel_break", "btc_ema50_cross", "perp_crowded_extension", "event_within_48h")
    ][:3]
    kw_html = ""
    if key_alerts:
        items = []
        for a in key_alerts:
            ic = "🚨" if a.get("severity") == "critical" else "⏰"
            c_cls = "kw-item crit" if a.get("severity") == "critical" else "kw-item"
            items.append(f'<div class="{c_cls}"><span>{ic}</span><span>{esc(a.get("message", ""))}</span></div>')
        kw_html = f'<div class="key-warnings">{"".join(items)}</div>'

    hero = (
        f'<div class="hero-card {cls}">'
        f'<div class="hero-top">'
        f'<div class="regime-pill {cls}">{icon} 当前市场：{esc(reg.get("regime_label", "—"))}（{sc.get("total","—")}/20 分）</div>'
        f'<div class="score-chips">'
        f'<span>大饼趋势 {sc.get("btc_trend","—")}/5</span>'
        f'<span>全场广度 {sc.get("funding","—")}/5</span>'
        f'<span>情绪费率 {sc.get("sentiment","—")}/5</span>'
        f'<span>宏观环境 {sc.get("macro","—")}/5</span>'
        f'</div></div>'
        f'<div class="hero-posture">👉 今日操作原则：{esc(reg.get("posture", ""))}</div>'
        f'{note_html}'
        f'{kw_html}'
        f'</div>'
    )

    br = reg.get("breadth", {})
    deriv = reg.get("derivatives_overview", {})
    fgi_lbl = FGI_CN.get(btc.get("fear_greed_label", ""), btc.get("fear_greed_label", ""))

    kpis = [
        (
            "BTC 现价 / 均线压力",
            f'{fmt_px(btc.get("price_usd"))} {pct_span(btc.get("price_change_24h"), 1)}',
            f'{esc(btc.get("trend_label","—"))} · 20日线 {fmt_px(btc.get("ema20"))} / 200日线 {fmt_px(btc.get("ema200"))}',
        ),
        (
            "ETH 现价 / 强弱汇率",
            f'{fmt_px(eth.get("price_usd"))} {pct_span(eth.get("chg_24h"), 1)}',
            f'{esc(eth.get("trend_label","—"))} · ETH/BTC {eth.get("eth_btc_ratio") or "—"}',
        ),
        (
            "市场多头广度（站上20日线）",
            f'{br.get("pct_above_ema20","—")}% <span style="font-size:14px;font-weight:500;color:var(--text-muted);">({br.get("above_ema20",0)}/{br.get("universe_count",0)} 币)</span>',
            f'站上50日线 {br.get("pct_above_ema50","—")}% · 全场中位年化费率 {fmt_pct(deriv.get("median_funding_ann_pct"), 1)}',
        ),
        (
            "市场情绪 / 稳定币底池",
            f'{btc.get("fear_greed","—")} <span style="font-size:15px;font-weight:600;color:var(--amber);">{esc(fgi_lbl)}</span>',
            f'稳定币总市值 {fmt_usd(glob.get("stablecoin_total_supply"))} ({fmt_pct(glob.get("stablecoin_supply_change_pct"), 1)})',
        ),
    ]
    kpi_html = "".join(
        f'<div class="kpi-box"><div class="k-label">{k[0]}</div>'
        f'<div class="k-val">{k[1]}</div><div class="k-sub">{k[2]}</div></div>'
        for k in kpis
    )
    return hero, kpi_html


def render_setups(setups):
    if not setups:
        return '<div class="card"><div class="muted">今日无满足高赔率过滤条件的日线剧本，建议空仓休息或维持既有顺势底仓。</div></div>'

    action_list = [s for s in setups if s.get("direction") in ("LONG", "SHORT")]
    watch_list = [s for s in setups if s.get("direction") == "WATCH"]
    parts = []

    if not action_list:
        parts.append('<div class="card"><div class="muted">今日暂无直接入场的多空信号，请重点关注下方「待突破观察池」，等日线走出方向再跟进。</div></div>')
    else:
        for idx, s in enumerate(action_list, 1):
            d = s.get("direction", "LONG")
            avoid = s.get("action_override") == "AVOID"
            dir_cn = "🟢 做多 LONG" if d == "LONG" else "🔴 做空 SHORT"
            if avoid:
                dir_cn += " · ⚠️排雷规避"
            sc = s.get("score", {})
            lev = (s.get("notional_1r_pct") or 0) / 100.0
            src_link = (
                f' <a href="{esc(s["source_url"])}" target="_blank" style="font-size:13px;color:var(--accent);">[查看信源 ↗]</a>'
                if s.get("source_url") else ""
            )
            fr = s.get("funding_ann_pct")
            fr_hint = "（空头付钱补贴多单）" if (d == "LONG" and fr is not None and fr < -3) else ""

            parts.append(
                f'<div class="ticket-card {d}">'
                f'<div class="ticket-head">'
                f'<div class="ticket-title">'
                f'<span class="act-badge {d}">{dir_cn}</span>'
                f'<span class="coin-sym">{idx}. {esc(s["symbol"])}</span>'
                f'<span class="setup-tag">{esc(s.get("setup_label", ""))} · 现价 {fmt_px(s.get("price_usd"))} ({pct_span(s.get("chg_24h"), 1)})</span>'
                f'</div>'
                f'<div class="score-pill">综合评分 {sc.get("total","—")}/20</div>'
                f'</div>'
                f'<div class="order-steps">'
                f'<div class="step-box">'
                f'<div class="s-label">① 怎么进场（参考位）</div>'
                f'<div class="s-main">{fmt_px(s.get("trigger_price"))} 附近</div>'
                f'<div class="s-desc">{esc(s.get("trigger_rule", ""))}</div>'
                f'</div>'
                f'<div class="step-box">'
                f'<div class="s-label">② 错了在哪砍（日线结构止损）</div>'
                f'<div class="s-main" style="color:var(--red);">{fmt_px(s.get("stop_price"))} <span style="font-size:14px;">(-{s.get("stop_dist_pct")}%)</span></div>'
                f'<div class="s-desc">{esc(s.get("stop_rule", ""))}</div>'
                f'</div>'
                f'<div class="step-box">'
                f'<div class="s-label">③ 建议仓位上限（按最多亏1%计）</div>'
                f'<div class="s-main" style="color:var(--accent);">{lev:.2f}x 杠杆 <span style="font-size:14px;">({s.get("notional_1r_pct")}% 本金)</span></div>'
                f'<div class="s-desc">止损宽 {s.get("stop_dist_pct")}%，若打止损总账户仅回撤 1.0%</div>'
                f'</div>'
                f'</div>'
                f'<div class="reason-list">'
                f'<div class="reason-row"><strong>💡 为什么做它：</strong><span>{esc(s.get("catalyst_note") or s.get("quant_summary", ""))}{src_link}</span></div>'
                f'<div class="reason-row"><strong>🛡️ 持仓排雷：</strong><span>{esc(s.get("risk_landmine", ""))}</span></div>'
                f'</div>'
                f'<div class="meta-pills">'
                f'<span class="meta-pill">14天相对大饼：{fmt_pct(s.get("rs_14d"), 1)}</span>'
                f'<span class="meta-pill">年化资金费率：{fmt_pct(fr, 1)}{fr_hint}</span>'
                f'<span class="meta-pill">日均波幅(ATR)：{fmt_pct(s.get("atr_pct"), 1, False)}</span>'
                f'<span class="meta-pill">合约持仓(OI)：{fmt_usd(s.get("oi_usd"))}</span>'
                f'</div>'
                f'</div>'
            )

    if watch_list:
        w_cards = []
        for s in watch_list:
            d20h = fmt_px(s.get("donchian_20d_high") or s.get("trigger_price"))
            d20l = fmt_px(s.get("donchian_20d_low"))
            src_link = (
                f' <a href="{esc(s["source_url"])}" target="_blank" style="font-size:12.5px;color:var(--accent);">[信源 ↗]</a>'
                if s.get("source_url") else ""
            )
            w_cards.append(
                f'<div class="watch-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
                f'<div><strong style="font-size:19px;">{esc(s["symbol"])}</strong> '
                f'<span class="muted" style="font-size:13.5px;">现价 {fmt_px(s.get("price_usd"))} ({pct_span(s.get("chg_24h"), 1)})</span></div>'
                f'<span class="trend-pill DOWN_BOUNCE">极度缩量收敛</span>'
                f'</div>'
                f'<div class="watch-triggers">'
                f'<div class="wt-box"><div class="wt-lbl">🟢 放量突破做多位</div><div class="wt-val up">{d20h}</div></div>'
                f'<div class="wt-box"><div class="wt-lbl">🔴 放量跌破做空位</div><div class="wt-val down">{d20l}</div></div>'
                f'</div>'
                f'<div style="font-size:13.5px;color:var(--text-body);line-height:1.6;">'
                f'<strong>关注逻辑：</strong>{esc(s.get("catalyst_note") or s.get("quant_summary", ""))}{src_link}'
                f'<div class="muted" style="font-size:12.5px;margin-top:4px;">排雷：{esc(s.get("risk_landmine", ""))}</div>'
                f'</div>'
                f'</div>'
            )
        parts.append(
            '<div class="watch-subhead">👀 待变盘观察池（区间极度压缩，突破前观望勿猜方向）</div>'
            f'<div class="watch-grid">{"".join(w_cards)}</div>'
        )

    return "\n".join(parts)


def render_watchlist(rows):
    if not rows:
        return '<div class="muted">自选池为空</div>'
    trs = []
    for w in rows:
        ts = w.get("trend_state", "RANGE_CHOP")
        pos_num = w.get("pos_in_20d_pct")
        if pos_num is not None:
            bar_color = "var(--green)" if pos_num >= 65 else ("var(--red)" if pos_num <= 25 else "var(--amber)")
            pos_html = (
                f'<div class="pos-cell">'
                f'<div class="pos-track"><div class="pos-fill" style="width:{max(4, pos_num):.0f}%;background:{bar_color};"></div></div>'
                f'<span>{pos_num:.0f}%</span></div>'
            )
        else:
            pos_html = "—"
        note = f'<div style="font-size:12px;color:var(--text-muted);">{esc(w["note"])}</div>' if w.get("note") else ""
        trs.append(
            f'<tr>'
            f'<td><strong style="color:var(--text);font-size:15px;">{esc(w["symbol"])}</strong>{note}</td>'
            f'<td><strong style="color:var(--text);">{fmt_px(w.get("price_usd"))}</strong> ({pct_span(w.get("chg_24h"), 1)})</td>'
            f'<td><span class="trend-pill {ts}">{esc(w.get("trend_label","—"))}</span></td>'
            f'<td>{pos_html}</td>'
            f'<td>{fmt_px(w.get("ema20"))} ({pct_span(w.get("dist_ema20_pct"), 1)})</td>'
            f'<td>{pct_span(w.get("rs_14d"), 1)}</td>'
            f'<td>{pct_span(w.get("funding_ann_pct"), 1)}</td>'
            f'<td>{fmt_usd(w.get("oi_usd"))}</td>'
            f'</tr>'
        )
    return (
        '<table class="data-table"><thead><tr>'
        '<th>币种</th><th>现价 (24h)</th><th>日线结构</th><th>近20日高低位置</th>'
        '<th>20日均线 (偏离)</th><th>14天相对大饼</th><th>年化费率</th><th>合约持仓</th>'
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
            f'<tr><td><strong style="color:var(--text);">{esc(m["symbol"])}</strong></td>'
            f'<td>{fmt_px(m.get("price_usd"))} ({pct_span(m.get("chg_24h"), 1)})</td>'
            f'<td>{col3}</td><td>{col4}</td></tr>'
        )
    hdr3, hdr4 = ("14天跑赢幅度", "日线趋势") if mode == "rs" else ("年化资金费率", "合约持仓")
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
            f'<tr><td><strong style="color:var(--text);">{esc(s.get("name") or s.get("category"))}</strong></td>'
            f'<td>{fmt_usd(s.get("market_cap"))}</td>'
            f'<td>{pct_span(s.get("market_cap_change_24h"), 2)}</td>'
            f'<td class="muted">{esc(s.get("note") or "")}</td></tr>'
        )
    return (
        '<table class="data-table"><thead><tr><th>赛道板块</th><th>板块市值</th><th>24h涨跌</th>'
        '<th>轮动状态</th></tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
    )


def render_events(events):
    if not events:
        return '<div class="muted">未来 14 天暂无已确认日期的重大排雷事件</div>'
    trs = []
    for e in events[:12]:
        da = e.get("days_away", 99)
        row_cls = ' class="urgent-row"' if da <= 3 else ""
        if da <= 0:
            cd = '<span class="warn">⏰ 今天</span>'
        elif da == 1:
            cd = '<span class="warn">⏰ 明天 (1天)</span>'
        elif da <= 3:
            cd = f'<span class="warn">⏰ {da} 天后</span>'
        else:
            cd = f"{da} 天后"

        b_cls, b_txt = EVENT_BADGE.get(e.get("event_type"), ("macro", e.get("event_type", "事件")))
        angle_html = (
            f'<div style="color:var(--amber);font-size:13px;margin-top:4px;">👉 应对：{esc(e["opportunity_angle"])}</div>'
            if e.get("opportunity_angle") else ""
        )
        trs.append(
            f'<tr{row_cls}>'
            f'<td><strong>{esc(e.get("date"))}</strong><div style="font-size:12px;">{cd}</div></td>'
            f'<td><strong style="color:var(--text);font-size:15px;">{esc(str(e.get("coin","")).upper())}</strong></td>'
            f'<td><span class="ev-badge {b_cls}">{b_txt}</span></td>'
            f'<td class="wrap">{esc(e.get("description"))}{angle_html}</td>'
            f'</tr>'
        )
    return (
        '<table class="data-table"><thead><tr><th>日期 / 倒计时</th><th>标的</th>'
        '<th>事件类型</th><th>事件内容与交易应对</th></tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
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

    hero_html, kpis_html = render_regime_hero(reg, btc, eth, glob, d.get("alerts"))

    ph = {
        "report_date": date,
        "report_session": session,
        "closed_candle_date": btc.get("last_closed_date") or "—",
        "report_timestamp": ts.replace("T", " ")[:16] + " (北京时间)" if ts else "",
        "regime_hero_html": hero_html,
        "regime_kpis_html": kpis_html,
        "btc_20d_range": f'{fmt_px(btc.get("donchian_20d_low"))} ~ {fmt_px(btc.get("donchian_20d_high"))}',
        "btc_atr_text": f'{fmt_px(btc.get("atr14"))} ({fmt_pct(btc.get("atr_pct"), 1, False)})',
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
