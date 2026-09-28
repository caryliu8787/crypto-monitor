#!/usr/bin/env python3
"""crypto-monitor HTML 渲染器（确定性环节，替代模型手写 HTML）。

读取 data/latest.json + templates/dashboard.html，替换全部 {{placeholder}}，
输出 reports/YYYY-MM-DD_{session}.html。

所有定性文字（reason/thesis/note/signals/cycle_notes/priority）由模型写进
latest.json 的对应字段；本脚本只做格式化与排版，不生成任何内容。
新增 JSON 字段（模型需填写，均为可选）：
- priority: [{"action": "high|medium|watch|skip", "coin", "headline", "body"}]
- market_context.btc.signals: {"price","fgi","dominance","support","resistance"}
- market_context.cycle_notes: {"mvrv","funding","oi","stablecoin","eth"}

用法: python3 scripts/render-html.py [YYYY-MM-DD] [session]
"""

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))

TRACKING_BOARD_MAX = 10

DIFFUSION_LABEL = {"red": "🔴 未扩散", "yellow": "🟡 早期", "green": "🟢 已扩散"}
DIFFUSION_ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
ACTION_MAP = {
    "high": ("buy", "高优先级"),
    "medium": ("hold", "中优先级"),
    "watch": ("watch", "观察"),
    "skip": ("sell", "不推荐花时间"),
}
SEVERITY_STYLE = {
    "critical": ("alert-box", "🔴 严重告警"),
    "warning": ("alert-box warning", "🟡 警告"),
    "info": ("alert-box info", "🔵 提示"),
}


# ---------- 格式化 ----------
def fmt_price(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"${v:,.0f}"
    if v >= 1:
        return f"${v:.2f}"
    if v >= 0.01:
        return f"${v:.4f}"
    return f"${v:.6f}"


def fmt_pct(v, digits=2):
    if v is None:
        return "—"
    return f"+{v:.{digits}f}%" if v >= 0 else f"{v:.{digits}f}%"


def pct_span(v, digits=2):
    if v is None:
        return "—"
    cls = "up" if v >= 0 else "down"
    return f'<span class="{cls}">{fmt_pct(v, digits)}</span>'


def fmt_cap(v):
    if v is None:
        return "—"
    if v >= 1e12:
        return f"${v / 1e12:.2f} 万亿"
    if v >= 1e8:
        return f"${v / 1e8:.2f} 亿"
    if v >= 1e4:
        return f"${v / 1e4:,.0f} 万"
    return f"${v:,.0f}"


def md(text):
    """内联 markdown → HTML：转义后处理链接/粗体/行内代码/换行。"""
    if not text:
        return ""
    t = str(text)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" style="color:var(--text-muted);">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = t.replace("\n", "<br>")
    return t


def source_div(url):
    if not url:
        return ""
    disp = url if len(url) <= 70 else url[:70] + "…"
    return (f'<div class="source">来源: <a href="{url}" '
            f'style="color:var(--text-muted);">{disp}</a></div>')


# ---------- 各区块 ----------
def alerts_html(alerts):
    if not alerts:
        return ""
    groups = {}
    for a in alerts:
        sev = a.get("severity", "info") if isinstance(a, dict) else "info"
        groups.setdefault(sev, []).append(a)
    out = []
    for sev in ("critical", "warning", "info"):
        if sev not in groups:
            continue
        cls, title = SEVERITY_STYLE[sev]
        items = "".join(
            f'<li><code>{a.get("rule", "")}</code> — {md(a.get("message", str(a)))}</li>'
            for a in groups[sev])
        out.append(f'<div class="{cls}"><strong>{title}（{len(groups[sev])} 条）</strong>'
                   f'<ul style="margin:8px 0 0;padding-left:18px;">{items}</ul></div>')
    return "\n".join(out)


def opp_card(o):
    diff = o.get("diffusion") or "gray"
    s = o.get("score", {})
    dims = (f'催化{s.get("catalyst_strength", "—")} 窗口{s.get("time_window", "—")} '
            f'拥挤{s.get("crowding", "—")} 风险{s.get("risk", "—")}')
    status = o.get("status")
    if status == "new":
        state = f'首见 {o.get("first_seen", "")}'
    elif status == "triggered":
        state = "✅ 已触发"
    elif status == "expired":
        state = "❌ 已过期"
    else:
        state = (f'跟踪 {o.get("sessions_tracked", "—")} 期 · '
                 f'无进展 {o.get("sessions_since_progress", "—")} 期')
    meta = (f'{s.get("total", "—")}/20 · {dims} · '
            f'{DIFFUSION_LABEL.get(diff, diff)} · {state}')
    return (f'<div class="alpha-card {diff}"><span class="coin-tag">'
            f'{str(o.get("coin", "")).upper()}</span><strong>{md(o.get("title", ""))}</strong> '
            f'<span style="font-size:11px;color:var(--text-secondary);">{meta}</span>'
            f'<div style="margin-top:6px;">{md(o.get("thesis", ""))}</div>'
            f'{source_div(o.get("source_url"))}</div>')


def opportunity_board_html(opps):
    new = [o for o in opps if o.get("status") == "new"]
    tracking = sorted([o for o in opps if o.get("status") == "tracking"],
                      key=lambda o: (o.get("score", {}).get("total") or 0), reverse=True)
    closed = [o for o in opps if o.get("status") in ("triggered", "expired")]
    stale = [o for o in opps if o.get("status") == "stale"]

    out = []
    if new:
        out.append(f'<h3 style="margin-top:4px;">🆕 本期新发现（{len(new)} 项）</h3>')
        out += [opp_card(o) for o in new]
    else:
        out.append('<div class="alpha-card gray"><strong>本期无新机会</strong></div>')

    shown = tracking[:TRACKING_BOARD_MAX]
    overflow = tracking[TRACKING_BOARD_MAX:]
    if shown:
        out.append(f'<h3>📌 持续跟踪（{len(tracking)} 项，按评分降序取前 '
                   f'{len(shown)}；其余并入末尾折叠行）</h3>')
        out += [opp_card(o) for o in shown]

    if closed:
        out.append('<h3>✅ 已触发 / 已过期</h3>')
        out += [opp_card(o) for o in closed]

    collapsed = stale + overflow
    if collapsed:
        collapsed.sort(key=lambda o: (o.get("score", {}).get("total") or 0), reverse=True)
        syms = " · ".join(f'{str(o.get("coin", "")).upper()} '
                          f'{o.get("score", {}).get("total", "—")}' for o in collapsed)
        out.append(f'<div class="alpha-card gray"><strong>{len(collapsed)} 项机会持续静默跟踪'
                   f'</strong>（完整条目见 <code>data/latest.json</code>，按 4.7(c) 不逐条展示）'
                   f'<div style="margin-top:6px;color:var(--text-secondary);">{syms}</div></div>')
    return "\n".join(out)


def opportunity_priority_html(priority):
    out = []
    for i, p in enumerate(priority or [], 1):
        cls, label = ACTION_MAP.get(p.get("action"), ("watch", "观察"))
        out.append(
            f'<div class="rec-card {cls}"><div class="rec-header">'
            f'<span class="rec-coin">{"①②③④⑤⑥"[i - 1] if i <= 6 else str(i)} '
            f'{md(p.get("headline", p.get("coin", "")))}</span>'
            f'<span class="rec-action {cls}">{label}</span></div>'
            f'<div class="rec-body">{md(p.get("body", ""))}</div></div>')
    return "\n".join(out)


def movers_table_html(movers):
    rows = []
    for m in movers or []:
        reason = md(m.get("reason")) if m.get("reason") else "原因未明"
        rows.append(
            f'<tr><td><strong>{m.get("symbol", "")}</strong></td>'
            f'<td>{fmt_price(m.get("price_usd"))}</td>'
            f'<td class="{"up" if (m.get("price_change_24h") or 0) >= 0 else "down"}">'
            f'{fmt_pct(m.get("price_change_24h"))}</td>'
            f'<td class="{"up" if (m.get("price_change_7d") or 0) >= 0 else "down"}">'
            f'{fmt_pct(m.get("price_change_7d"))}</td>'
            f'<td class="{"up" if (m.get("price_change_30d") or 0) >= 0 else "down"}">'
            f'{fmt_pct(m.get("price_change_30d"))}</td>'
            f'<td>{fmt_cap(m.get("market_cap"))}</td>'
            f'<td class="meaning">{reason}</td></tr>')
    if not rows:
        return '<div class="no-data">数据暂缺</div>'
    return ('<table class="data-table"><thead><tr><th>币种</th><th>价格</th><th>24h</th>'
            '<th>7d</th><th>30d</th><th>市值</th><th>原因</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def sector_rotation_html(sectors):
    rows = []
    for s in sectors or []:
        chg = s.get("market_cap_change_24h")
        rows.append(
            f'<tr><td><strong>{s.get("name") or s.get("category", "")}</strong></td>'
            f'<td>{fmt_cap(s.get("market_cap"))}</td>'
            f'<td class="{"up" if (chg or 0) >= 0 else "down"}">{fmt_pct(chg)}</td>'
            f'<td>{s.get("trend_sessions", 1)} 期</td>'
            f'<td class="meaning">{md(s.get("note"))}</td></tr>')
    if not rows:
        return '<div class="no-data">数据暂缺</div>'
    return ('<table class="data-table"><thead><tr><th>板块</th><th>市值</th><th>24h</th>'
            '<th>连续同向</th><th>备注</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def trending_html(trending):
    tag = ('<span class="coin-tag" style="background:rgba(88,166,255,.12);'
           'color:var(--accent);font-size:12px;padding:3px 8px;">{}</span>')
    return " ".join(tag.format(str(t.get("symbol", "")).upper()) for t in trending or [])


def countdown_cell(e):
    da = e.get("days_away")
    if da is None:
        return "—"
    if da < 0 or e.get("status") == "passed":
        return "已过"
    if da == 0:
        return '<span class="warn"><strong>⏰ 今天</strong></span>'
    if da <= 2:
        return f'<span class="warn"><strong>⏰ {da} 天</strong></span>'
    return f"{da} 天"


def event_calendar_html(events):
    evs = sorted(events or [], key=lambda e: e.get("date") or "9999")
    rows = []
    for e in evs:
        rows.append(
            f'<tr><td>{e.get("date", "")}</td><td>{countdown_cell(e)}</td>'
            f'<td><strong>{str(e.get("coin", "")).upper()}</strong></td>'
            f'<td><code>{e.get("event_type", "")}</code></td>'
            f'<td class="meaning">{md(e.get("description"))}</td>'
            f'<td class="meaning">{md(e.get("opportunity_angle"))}</td></tr>')
    if not rows:
        return '<div class="no-data">本期无明确日期的事件</div>'
    return ('<table class="data-table"><thead><tr><th>日期</th><th>倒计时</th><th>币种</th>'
            '<th>类型</th><th>事件</th><th>机会角度</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def macro_calendar_html(events):
    rows = []
    for e in sorted((e for e in events or [] if e.get("event_type") == "macro"),
                    key=lambda e: e.get("date") or "9999"):
        rows.append(
            f'<tr><td style="white-space:nowrap;"><strong>{e.get("date", "")}</strong></td>'
            f'<td style="white-space:nowrap;">{countdown_cell(e)}</td>'
            f'<td>{md(e.get("description"))}</td>'
            f'<td class="meaning">{md(e.get("opportunity_angle"))}</td></tr>')
    if not rows:
        return '<div class="no-data">本期无宏观事件</div>'
    return '<table class="macro-table"><tbody>' + "".join(rows) + "</tbody></table>"


def cycle_table_html(mc, freshness):
    btc = mc.get("btc", {})
    glob = mc.get("global", {})
    eth = mc.get("eth", {})
    notes = mc.get("cycle_notes") or {}

    def fresh(field, default="当期"):
        f = (freshness or {}).get(field)
        if f and (f.get("sessions_unchanged") or 0) >= 3:
            return f'⚠️ 数据已 {f["sessions_unchanged"]} 期未更新'
        return default

    rows = []
    mvrv = btc.get("mvrv_ratio")
    rows.append(
        f'<tr><td>MVRV 比率</td><td><strong>{f"{mvrv:.4f}" if mvrv is not None else "—"}</strong></td>'
        f'<td class="meaning">{md(notes.get("mvrv"))}</td>'
        f'<td class="meaning">{("数据时点 " + btc["mvrv_data_time"][:10]) if btc.get("mvrv_data_time") else fresh("mvrv_ratio", "数据暂缺")}</td></tr>')
    fr = btc.get("funding_rate")
    rows.append(
        f'<tr><td>资金费率</td><td><strong>{fmt_pct(fr, 6) if fr is not None else "—"}</strong></td>'
        f'<td class="meaning">{md(notes.get("funding"))}</td>'
        f'<td class="meaning">{fresh("funding_rate")}</td></tr>')
    oi = btc.get("open_interest")
    rows.append(
        f'<tr><td>未平仓合约</td><td><strong>{fmt_cap(oi)}</strong></td>'
        f'<td class="meaning">{md(notes.get("oi"))}</td>'
        f'<td class="meaning">{fresh("open_interest")}</td></tr>')
    rows.append(
        f'<tr><td>稳定币总供应</td><td><strong>{fmt_cap(glob.get("stablecoin_total_supply"))}</strong></td>'
        f'<td class="meaning">{md(notes.get("stablecoin"))}</td><td class="meaning">当期</td></tr>')
    ratio = eth.get("eth_btc_ratio")
    rows.append(
        f'<tr><td>ETH / ETH-BTC</td><td><strong>{fmt_price(eth.get("price_usd"))}</strong> / '
        f'<strong>{f"{ratio:.6f}" if ratio is not None else "—"}</strong></td>'
        f'<td class="meaning">{md(notes.get("eth"))}</td><td class="meaning">当期</td></tr>')
    return ('<table class="data-table"><thead><tr><th>指标</th><th>数值</th><th>信号</th>'
            '<th>新鲜度</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


def note_box(text, cls="key-changes"):
    """可选自由补充块（模型写进 JSON 的 *_note 字段）。"""
    if not text:
        return ""
    return f'<div class="{cls}">{md(text)}</div>'


def watchlist_section_html(watchlist):
    if not watchlist:
        return ('<div class="key-changes"><strong>关注名单</strong> — '
                '<code>config/watchlist.json</code> 为空，本节按规则不渲染内容。'
                '发现值得长期钉住的标的时，把 CoinGecko coin id 加进该文件。</div>')
    items = []
    for cid, w in watchlist.items():
        items.append(
            f'<div class="watchlist-item"><span class="ticker">{cid}</span><br>'
            f'{fmt_price(w.get("price_usd"))} {pct_span(w.get("price_change_24h"))} / '
            f'7d {fmt_pct(w.get("price_change_7d"))}<br>'
            f'<span style="color:var(--text-secondary);">{fmt_cap(w.get("market_cap"))}'
            f'{" · " + md(w.get("note")) if w.get("note") else ""}</span></div>')
    return ('<h2>五、关注名单</h2><div class="watchlist-row">'
            + "".join(items) + "</div>")


# ---------- 主流程 ----------
def render(date=None, session="daily"):
    d = json.load(open(ROOT / "data/latest.json"))
    tpl = open(ROOT / "templates/dashboard.html").read()

    ts = d.get("timestamp", "")
    date = date or ts[:10] or datetime.now(TZ).strftime("%Y-%m-%d")
    session = d.get("session", session)

    mc = d.get("market_context", {})
    btc = mc.get("btc", {})
    glob = mc.get("global", {})
    score = d.get("market_score", {})
    signals = btc.get("signals") or {}
    scan = d.get("market_scan", {})

    label = score.get("label", "")
    phase = re.split(r"[（(]", label)[0] if label else ""

    spark = btc.get("sparkline_7d") or []
    pos = None
    if spark and btc.get("price_usd") and max(spark) > min(spark):
        pos = round((btc["price_usd"] - min(spark)) / (max(spark) - min(spark)) * 100, 1)

    default_price_signal = (f'7d {fmt_pct(btc.get("price_change_7d"))}'
                            + (f'，位于 7d 区间 {pos}% 分位' if pos is not None else ""))
    dom_pp = btc.get("dominance_change_pp")

    tvl = scan.get("chains_tvl_delta", [])[:6]

    ph = {
        "report_date": date,
        "report_session": session,
        "report_timestamp": ts.replace("T", " ")[:16] + " UTC+8" if ts else "",
        "alerts_html": alerts_html(d.get("alerts")),
        "opportunity_board_html": opportunity_board_html(d.get("opportunities")),
        "opportunity_priority_html": (opportunity_priority_html(d.get("priority"))
                                      + note_box(d.get("board_note"))),
        "movers_table_html": movers_table_html(scan.get("movers")),
        "movers_narrative": md(scan.get("movers_narrative")),
        "sector_rotation_html": (sector_rotation_html(scan.get("sector_rotation"))
                                 + note_box(scan.get("sector_note"), "etf-text-summary")),
        "trending_html": (trending_html(scan.get("trending"))
                          + note_box(scan.get("trending_note"), "etf-text-summary")),
        "tvl_chart_labels": json.dumps([c["chain"] for c in tvl]),
        "tvl_chart_data": json.dumps([round((c.get("tvl") or 0) / 1e9, 2) for c in tvl]),
        "event_calendar_html": (event_calendar_html(d.get("events"))
                                + note_box(d.get("events_note"), "etf-text-summary")),
        "macro_calendar_html": (macro_calendar_html(d.get("events"))
                                + note_box(mc.get("analysis_note"), "analysis-block")),
        "market_score_total": str(score.get("total", "—")),
        "market_phase": phase,
        "score_btc_trend": str(score.get("btc_trend", "")),
        "score_funding": str(score.get("funding", "")),
        "score_sentiment": str(score.get("sentiment", "")),
        "score_macro": str(score.get("macro", "")),
        "btc_price": fmt_price(btc.get("price_usd")),
        "btc_24h_change": pct_span(btc.get("price_change_24h")),
        "btc_price_signal": md(signals.get("price")) or default_price_signal,
        "fgi_value": str(btc.get("fear_greed", "—")),
        "fgi_label": btc.get("fear_greed_label", ""),
        "fgi_signal": md(signals.get("fgi")) or btc.get("fear_greed_label", ""),
        "btc_dominance": f'{btc.get("dominance"):.2f}' if btc.get("dominance") is not None else "—",
        "btc_dominance_change": (f'<span class="{"up" if dom_pp >= 0 else "down"}">'
                                 f'{"+" if dom_pp >= 0 else ""}{dom_pp}pp</span>')
                                if dom_pp is not None else "--",
        "btc_dominance_signal": md(signals.get("dominance")),
        "total_market_cap": fmt_cap(glob.get("total_market_cap_usd")),
        "btc_etf_flow_text": md((mc.get("etf_qualitative") or {}).get("btc_etf_flow_text")),
        "eth_etf_flow_text": md((mc.get("etf_qualitative") or {}).get("eth_etf_flow_text")),
        "cycle_table_html": cycle_table_html(mc, d.get("_freshness")),
        "btc_support_text": (f'<strong>${btc["support"]:,.0f}</strong>（7d 低点）'
                             + (" — " + md(signals["support"]) if signals.get("support") else ""))
                            if btc.get("support") else "数据暂缺",
        "btc_resistance_text": (f'<strong>${btc["resistance"]:,.0f}</strong>（7d 高点）'
                                + (" — " + md(signals["resistance"]) if signals.get("resistance") else ""))
                               if btc.get("resistance") else "数据暂缺",
        "btc_trend_text": md(btc.get("trend")),
        "btc_support": f'{btc["support"]:.2f}' if btc.get("support") else "",
        "btc_resistance": f'{btc["resistance"]:.2f}' if btc.get("resistance") else "",
        "btc_sparkline_data": json.dumps(spark),
        "watchlist_section_html": watchlist_section_html(d.get("watchlist")),
    }

    html = tpl
    for k, v in ph.items():
        html = html.replace("{{" + k + "}}", str(v))
    leftover = re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", html)
    if leftover:
        print(f"[render] WARNING leftover placeholders: {sorted(set(leftover))}", flush=True)

    out = ROOT / "reports" / f"{date}_{session}.html"
    with open(out, "w") as f:
        f.write(html)
    print(f"[render] done -> {out} ({len(html)} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else None,
           sys.argv[2] if len(sys.argv) > 2 else "daily")
