#!/usr/bin/env python3
"""crypto-monitor 2.1 一体化组装、渲染与发布脚本（含熔断校验、日期防串、增量日历与自动兜底）。

用法:
  python3 scripts/publish.py                 # 组装 + 渲染 + 推送 GitHub Pages & Telegram（同日默认防重复推 TG）
  python3 scripts/publish.py --force-tg      # 强制重新推送当日 Telegram 消息
  python3 scripts/publish.py --no-push       # 仅在本地生成报告文件，不执行 git push 与 Telegram 推送
  python3 scripts/publish.py --auto-fallback # launchd 兜底模式：避让运行中的主流程，仅在主流程缺席/超时后兜底发布
  python3 scripts/publish.py --restore-bak   # 从 data/latest.json.bak 恢复上一份完好快照
"""

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path

from collect import MIN_VALID_PERPS, TrendCollector, classify_regime, load_json

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))
PAGES_BASE = "https://caryliu8787.github.io/crypto-monitor"
PRIMARY_GRACE_SEC = 2400  # 主流程产生产物后预留 40 分钟供 Step 2 联网核查完成

FGI_CN = {
    "Extreme Fear": "极度恐慌",
    "Fear": "恐慌",
    "Neutral": "中性",
    "Greed": "贪婪",
    "Extreme Greed": "极度贪婪",
}

EVENT_META = {
    "unlock": ("unlock", "🔓 代币解锁", "解锁"),
    "upgrade": ("upgrade", "🚀 主网升级", "升级"),
    "macro": ("macro", "🏛️ 宏观节点", "宏观"),
}


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
    return (f"+{v:.{digits}f}%" if v >= 0 else f"{v:.{digits}f}%") if signed else f"{v:.{digits}f}%"


def pct_span(v, digits=1):
    if v is None:
        return "—"
    return f'<span class="{"up" if v >= 0 else "down"}">{fmt_pct(v, digits)}</span>'


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


def esc(text):
    if text is None:
        return ""
    t = html_escape(str(text), quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" style="color:var(--accent);">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def size_text_cn(notional_pct):
    pct = int(notional_pct or 0)
    usd_per_10k = pct * 100
    return f"每 $1万本金开 ${usd_per_10k:,}（占 {pct}%）"


def smart_truncate(text, max_len=36):
    """按语义与词法边界截断摘要，避免把『11/16』『9260』『v1.21』等日期/数字切碎。"""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= max_len:
        return s
    for sep in ("；", "。", "｜", "，", ", "):
        pos = s.find(sep, 12, max_len + 1)
        if pos != -1:
            return s[:pos].rstrip("，、；： ") + "…"
    cut = s[:max_len]
    # 若刚好切在 ASCII 连续词/数字/日期串（如 11/16, 9260, v1.21）中间，回退到该词起点前
    if max_len < len(s) and re.match(r"[0-9A-Za-z./_%$-]", s[max_len - 1]) and re.match(r"[0-9A-Za-z./_%$-]", s[max_len]):
        m = re.search(r"[0-9A-Za-z./_%$-]+$", cut)
        if m and m.start() >= 10:
            cut = cut[:m.start()]
    cut = cut.rstrip("（(【『「《-—/，、；： ")
    return cut + "…"


def risk_labels(latest):
    unit_pct = float(latest.get("unit_risk_equity_pct") or 1.0)
    pct_str = f"{unit_pct:g}"
    loss_10k = int(round(10000.0 * unit_pct / 100.0))
    return pct_str, loss_10k


def restore_latest_from_bak():
    bak_path = ROOT / "data/latest.json.bak"
    latest_path = ROOT / "data/latest.json"
    bak = load_json(bak_path, {}) or {}
    if ((bak.get("market_context") or {}).get("btc") or {}).get("price_usd"):
        shutil.copy2(bak_path, latest_path)
        print("[publish] restored data/latest.json from data/latest.json.bak", file=sys.stderr)
        return True
    return False


# ---------- 1. 数据校验、增量日历合并与告警 ----------

def validate_collected(collected):
    if not isinstance(collected, dict):
        return "data/collected.json missing or invalid JSON"
    btc = collected.get("btc") or {}
    if not (btc.get("price_usd") and btc["price_usd"] > 0 and btc.get("ema20")):
        return "collected BTC price_usd / ema20 missing (upstream API failure)"
    uni_cnt = (((collected.get("regime") or {}).get("breadth") or {}).get("universe_count")) or 0
    if uni_cnt < MIN_VALID_PERPS:
        return f"collected universe_count ({uni_cnt}) < {MIN_VALID_PERPS}"
    return None


def merge_and_normalize_events(prev_events, overlay_events, today_date):
    """以 previous.events 为底表增量合并 overlay.events（status=cancelled 可显式删除），杜绝整表误清空。"""
    merged = {}

    def _canon_key(e):
        coin = str(e.get("coin") or "MKT").strip().upper()
        etype = str(e.get("event_type") or "ev").strip().lower()
        dt = str(e.get("date") or "").strip()
        return (coin, etype, dt)

    id_to_ckey = {}
    for e in prev_events or []:
        if not isinstance(e, dict) or not e.get("date"):
            continue
        if e.get("status") in ("cancelled", "deleted", "passed"):
            continue
        ck = _canon_key(e)
        eid = e.get("id") or f"{ck[0].lower()}-{ck[1]}-{ck[2].replace('-', '')}"
        item = dict(e, id=eid)
        merged[ck] = item
        id_to_ckey[eid] = ck

    for e in overlay_events or []:
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        ck = _canon_key(e) if e.get("date") else id_to_ckey.get(eid)
        if not ck or not ck[2]:
            continue
        if e.get("status") in ("cancelled", "deleted", "passed"):
            merged.pop(ck, None)
            if eid and eid in id_to_ckey:
                merged.pop(id_to_ckey[eid], None)
            continue
        if eid and eid in id_to_ckey and id_to_ckey[eid] != ck:
            merged.pop(id_to_ckey[eid], None)
        final_id = eid or (merged.get(ck) or {}).get("id") or f"{ck[0].lower()}-{ck[1]}-{ck[2].replace('-', '')}"
        base = dict(merged.get(ck) or {})
        base.update(e)
        base["id"] = final_id
        merged[ck] = base
        id_to_ckey[final_id] = ck

    out = []
    for item in merged.values():
        try:
            d = datetime.strptime(item["date"], "%Y-%m-%d").date()
            days_away = (d - today_date).days
            if days_away >= 0:
                item["days_away"] = days_away
                item["status"] = "upcoming"
                out.append(item)
        except Exception:
            continue
    out.sort(key=lambda x: (x.get("days_away", 9999), x.get("date", "9999"), str(x.get("coin", ""))))
    return out


def resolve_risk_landmine_text(setup, events):
    """如实展示排雷状态：未人工核查时绝不谎称『无解锁』，自动关联日历已知项并提示人工未核查。"""
    if setup.get("risk_landmine"):
        return setup["risk_landmine"]
    sym = str(setup.get("symbol") or "").upper()
    hits = [e for e in (events or []) if str(e.get("coin") or "").upper() == sym and 0 <= e.get("days_away", 99) <= 14]
    if hits:
        e0 = hits[0]
        return f"日历预警：{e0.get('date')}（{e0.get('days_away')}天后）{e0.get('description', '')}"
    return "单币解锁未专项核查（请对照下方排雷日历）"


def partition_setups(setups):
    action_list = [s for s in (setups or []) if s.get("direction") in ("LONG", "SHORT") and s.get("action_override") != "AVOID"]
    avoid_list = [s for s in (setups or []) if s.get("action_override") == "AVOID"]
    watch_list = [s for s in (setups or []) if s.get("direction") == "WATCH" and s.get("action_override") != "AVOID"]
    return action_list, avoid_list, watch_list


def build_key_warnings(btc, watch_rows, events):
    warnings = []
    bp, d20h, d20l = btc.get("price_usd"), btc.get("donchian_20d_high"), btc.get("donchian_20d_low")
    if bp and d20h and bp >= d20h * 0.998:
        warnings.append({"severity": "critical", "message": f"BTC 突破近 20 日高点 {fmt_px(d20h)}（现价 {fmt_px(bp)}），多头趋势扩张"})
    elif bp and d20l and bp <= d20l * 1.003:
        warnings.append({"severity": "critical", "message": f"BTC 跌破近 20 日低点 {fmt_px(d20l)}（现价 {fmt_px(bp)}），下行寻底阶段严控多单仓位"})

    for w in watch_rows:
        datr = w.get("dist_ema20_atr")
        if datr is not None and abs(datr) >= 3.0:
            warnings.append({"severity": "warning", "message": f"{w['symbol']} 短线偏离 20 日均线已达 {datr:+.1f} 倍波幅（ATR），切忌顺向追涨杀跌"})

    for e in events:
        da = e.get("days_away", 99)
        if 0 <= da <= 2:
            t_cn = EVENT_META.get(e.get("event_type"), ("", "", "事件"))[2]
            warnings.append({"severity": "warning", "message": f"48h 内排雷：{str(e.get('coin','')).upper()} {t_cn}（{e.get('date')}）— {e.get('description','')}"})
    return warnings[:4]


# ---------- 2. Markdown 渲染 ----------

def render_markdown(latest):
    date = latest["report_date"]
    reg = latest["regime"]
    sc = reg["scores"]
    br = reg["breadth"]
    btc = latest["market_context"]["btc"]
    eth = latest["market_context"]["eth"]
    glob = latest["market_context"]["global"]
    watch = latest["watchlist_rows"]
    scan = latest["market_scan"]
    events = latest["events"]

    action_list, avoid_list, watch_list = partition_setups(latest.get("setups"))
    risk_pct_str, _ = risk_labels(latest)
    fgi_cn = FGI_CN.get(btc.get("fear_greed_label", ""), btc.get("fear_greed_label", ""))

    lines = [
        f"# 加密货币日线合约趋势早报（{date}）",
        "",
        f"> 更新时间：{latest['timestamp'][:16].replace('T', ' ')} (北京时间) ｜ 昨日收盘K线基准：{btc.get('last_closed_date','—')}",
        "",
        "## 一、今日大盘总纲",
        "",
        f"- **市场阶段**：**{reg['regime_label']}（{sc['total']}/20 分）** ｜ 市场情绪 **{btc.get('fear_greed','—')} {fgi_cn}**",
        f"- **操作纪律**：{reg['posture']}",
    ]
    if reg.get("regime_note"):
        lines.append(f"- **重点解读**：{reg['regime_note']}")

    lines += [
        "",
        "| 核心基准 | 现价 (24h) | 日线状态 | 20日 / 200日均线 | 近20日高低区间 | 日均波幅(ATR) | 年化费率 |",
        "|----------|------------|----------|------------------|----------------|---------------|----------|",
        f"| **BTC** | **{fmt_px(btc.get('price_usd'))}** ({fmt_pct(btc.get('price_change_24h'))}) | {btc.get('trend_label','—')} | {fmt_px(btc.get('ema20'))} / {fmt_px(btc.get('ema200'))} | {fmt_px(btc.get('donchian_20d_low'))} ~ {fmt_px(btc.get('donchian_20d_high'))} | {fmt_px(btc.get('atr14'))} ({fmt_pct(btc.get('atr_pct'), 1, False)}) | {fmt_pct(btc.get('funding_ann_pct'))} |",
        f"| **ETH** | **{fmt_px(eth.get('price_usd'))}** ({fmt_pct(eth.get('chg_24h'))}) | {eth.get('trend_label','—')} | 20日线 {fmt_px(eth.get('ema20'))} / 50日线 {fmt_px(eth.get('ema50'))} | ETH/BTC `{eth.get('eth_btc_ratio') or '—'}` | — | — |",
        "",
        f"- **全场广度**：{br['universe_count']} 个主流合约中 **{br['above_ema20']} 个（{br['pct_above_ema20']}%）** 站上 20 日均线 ｜ 中位年化费率 **{fmt_pct(reg['derivatives_overview'].get('median_funding_ann_pct'))}** ｜ 稳定币底池 {fmt_usd(glob.get('stablecoin_total_supply'))}",
        "",
        "---",
        "",
        "## 二、今日交易计划",
        "",
    ]

    if not action_list:
        lines += ["> 今日无满足过滤条件的直接可执行单，建议观望或关注下方变盘观察池。", ""]
    else:
        for idx, s in enumerate(action_list, 1):
            d_cn = "🟢 做多 LONG" if s["direction"] == "LONG" else "🔴 做空 SHORT"
            stop_sign = "-" if s["direction"] == "LONG" else "+"
            risk_txt = resolve_risk_landmine_text(s, events)
            lines += [
                f"### {idx}. {d_cn} · **{s['symbol']}**（{s['setup_label']} · {s['score']['total']}/20 分）",
                f"- **① 怎么进场**：{s['trigger_rule']}（现价 `{fmt_px(s['price_usd'])}`，24h `{fmt_pct(s.get('chg_24h'))}`）",
                f"- **② 错了在哪砍**：`{fmt_px(s.get('stop_price'))}`（`{stop_sign}{s.get('stop_dist_pct')}%`）— {s['stop_rule']}",
                f"- **③ 建议开多大**：**{size_text_cn(s.get('notional_1r_pct'))}**（按进场位 `{fmt_px(s.get('trigger_price'))}` 计，若打止损总账户亏 ≤{risk_pct_str}%）",
                f"- **📊 量化信号**：{s.get('quant_summary') or '—'}",
            ]
            if s.get("catalyst_note"):
                lines.append(f"- **💡 催化核查**：{s['catalyst_note']}")
            lines += [
                f"- **🛡️ 持仓排雷**：{risk_txt}（年化费率 `{fmt_pct(s.get('funding_ann_pct'))}` · 14天相对大饼 `{fmt_pct(s.get('rs_14d'))}` · 持仓 {fmt_usd(s.get('oi_usd'))}）",
                "",
            ]

    if avoid_list:
        lines += ["### ⛔ 排雷剔除（存在重大事件/解锁风险，不纳入可执行单）", ""]
        for s in avoid_list:
            risk_txt = resolve_risk_landmine_text(s, events)
            lines.append(f"- **{s['symbol']}**（原技术信号：{s.get('setup_label','')}）：因「{risk_txt}」规避开仓。")
        lines.append("")

    if watch_list:
        lines += [
            "### 👀 待变盘观察池（窄幅收敛，突破前勿提前猜方向）",
            "",
            "| 币种 | 现价 (24h) | 向上突破做多位 | 向下跌破做空位 | 量化结构与催化 |",
            "|------|------------|----------------|----------------|----------------|",
        ]
        for s in watch_list:
            logic = s.get("quant_summary") or ""
            if s.get("catalyst_note"):
                logic = f"{logic} ｜ 催化：{s['catalyst_note']}" if logic else s["catalyst_note"]
            lines.append(
                f"| **{s['symbol']}** | {fmt_px(s.get('price_usd'))} ({fmt_pct(s.get('chg_24h'))}) | "
                f"**{fmt_px(s.get('donchian_20d_high'))}** | **{fmt_px(s.get('donchian_20d_low'))}** | {logic} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 三、核心自选体检",
        "",
        "| 币种 | 现价 (24h) | 日线状态 | 20日位置 | 20日均线 (偏离) | 14天相对大饼 | 年化费率 | 合约持仓 |",
        "|------|------------|----------|----------|-----------------|--------------|----------|----------|",
    ]
    for w in watch:
        pos = f"{w['pos_in_20d_pct']:.0f}%" if w.get("pos_in_20d_pct") is not None else "—"
        lines.append(
            f"| **{w['symbol']}** | {fmt_px(w.get('price_usd'))} ({fmt_pct(w.get('chg_24h'))}) | {w.get('trend_label','—')} | "
            f"{pos} | {fmt_px(w.get('ema20'))} ({fmt_pct(w.get('dist_ema20_pct'))}) | {fmt_pct(w.get('rs_14d'))} | "
            f"{fmt_pct(w.get('funding_ann_pct'))} | {fmt_usd(w.get('oi_usd'))} |"
        )

    lines += ["", "---", "", "## 四、未来持仓排雷日历", ""]
    if not events:
        lines.append("> 未来 14 天暂无已确认日期的重大排雷事件。")
    else:
        lines += ["| 日期 | 倒计时 | 标的 | 类型 | 事件说明与应对 |", "|------|--------|------|------|----------------|"]
        for e in events[:12]:
            da = e.get("days_away", 99)
            cnt = f"**⏰ {da}天**" if da <= 3 else f"{da}天"
            t_cn = EVENT_META.get(e.get("event_type"), ("", "", "事件"))[2]
            ang = f" **应对：{e['opportunity_angle']}**" if e.get("opportunity_angle") else ""
            lines.append(f"| {e.get('date')} | {cnt} | **{str(e.get('coin','')).upper()}** | {t_cn} | {e.get('description','')}{ang} |")

    lines += [
        "",
        "---",
        "",
        "## 五、多空选币备选池",
        "",
        "- **🚀 多头备选（抗跌/逼空 Top 6）**：" + "、".join(
            f"**{m['symbol']}**（跑赢大饼 {fmt_pct(m.get('rs_14d'))}，费率 {fmt_pct(m.get('funding_ann_pct'))}）"
            for m in scan.get("bull_radar", [])[:6]
        ),
        "- **🩸 空头备选（领跌弱势 Top 6）**：" + "、".join(
            f"**{m['symbol']}**（跑输大饼 {fmt_pct(m.get('rs_14d'))}，费率 {fmt_pct(m.get('funding_ann_pct'))}）"
            for m in scan.get("bear_radar", [])[:6]
        ),
    ]
    return "\n".join(lines) + "\n"


# ---------- 3. HTML 渲染 ----------

def render_html(latest, date_str):
    tpl = (ROOT / "templates/dashboard.html").read_text()
    reg = latest["regime"]
    sc = reg["scores"]
    br = reg["breadth"]
    deriv = reg["derivatives_overview"]
    btc = latest["market_context"]["btc"]
    eth = latest["market_context"]["eth"]
    glob = latest["market_context"]["global"]
    scan = latest["market_scan"]
    events = latest.get("events") or []

    code = reg.get("regime_code", "")
    cls = "bull" if "BULL" in code else ("bear" if "BEAR" in code else "chop")
    icon = "🟢" if cls == "bull" else ("🔴" if cls == "bear" else "🟡")
    note_html = f'<div class="hero-note"><strong>盘面解读：</strong>{esc(reg["regime_note"])}</div>' if reg.get("regime_note") else ""

    kw_items = [
        f'<div class="{"kw-item crit" if a["severity"] == "critical" else "kw-item"}">'
        f'<span>{"🚨" if a["severity"] == "critical" else "⏰"}</span><span>{esc(a["message"])}</span></div>'
        for a in latest.get("warnings", [])
    ]
    kw_html = f'<div class="key-warnings">{"".join(kw_items)}</div>' if kw_items else ""

    breadth_sc = sc.get("breadth") if sc.get("breadth") is not None else sc.get("funding", "—")
    hero_html = (
        f'<div class="hero-card {cls}">'
        f'<div class="hero-top">'
        f'<div class="regime-pill {cls}">{icon} 当前市场：{esc(reg.get("regime_label","—"))}（{sc.get("total","—")}/20 分）</div>'
        f'<div class="score-chips">'
        f'<span>大饼趋势 {sc.get("btc_trend","—")}/5</span><span>全场广度 {breadth_sc}/5</span>'
        f'<span>情绪费率 {sc.get("sentiment","—")}/5</span><span>宏观环境 {sc.get("macro","—")}/5</span>'
        f'</div></div>'
        f'<div class="hero-posture">👉 今日操作原则：{esc(reg.get("posture",""))}</div>'
        f'{note_html}{kw_html}</div>'
    )

    fgi_cn = FGI_CN.get(btc.get("fear_greed_label", ""), btc.get("fear_greed_label", ""))
    kpis = [
        ("BTC 现价 / 均线压力", f'{fmt_px(btc.get("price_usd"))} {pct_span(btc.get("price_change_24h"))}',
         f'{esc(btc.get("trend_label","—"))} · 20日线 {fmt_px(btc.get("ema20"))} / 200日线 {fmt_px(btc.get("ema200"))}'),
        ("ETH 现价 / 汇率", f'{fmt_px(eth.get("price_usd"))} {pct_span(eth.get("chg_24h"))}',
         f'{esc(eth.get("trend_label","—"))} · ETH/BTC {eth.get("eth_btc_ratio") or "—"}'),
        ("市场多头广度（站上20日线）", f'{br.get("pct_above_ema20","—")}% <span style="font-size:13.5px;font-weight:500;color:var(--text-muted);">({br.get("above_ema20",0)}/{br.get("universe_count",0)} 币)</span>',
         f'站上50日线 {br.get("pct_above_ema50","—")}% · 中位年化费率 {fmt_pct(deriv.get("median_funding_ann_pct"))}'),
        ("市场情绪 / 稳定币底池", f'{btc.get("fear_greed","—")} <span style="font-size:15px;font-weight:600;color:var(--amber);">{esc(fgi_cn)}</span>',
         f'稳定币总市值 {fmt_usd(glob.get("stablecoin_total_supply"))} ({fmt_pct(glob.get("stablecoin_supply_change_pct"))})'),
    ]
    kpis_html = "".join(
        f'<div class="kpi-box"><div class="k-label">{k[0]}</div><div class="k-val">{k[1]}</div><div class="k-sub">{k[2]}</div></div>'
        for k in kpis
    )

    action_list, avoid_list, watch_list = partition_setups(latest.get("setups"))
    risk_pct_str, loss_per_10k = risk_labels(latest)
    s_parts = []
    if not action_list:
        s_parts.append('<div class="card"><div class="muted">今日无满足过滤条件的直接入场单，建议观望或留意下方待变盘观察池。</div></div>')
    else:
        for idx, s in enumerate(action_list, 1):
            d = s["direction"]
            dir_cn = "🟢 做多 LONG" if d == "LONG" else "🔴 做空 SHORT"
            stop_sign = "-" if d == "LONG" else "+"
            pct_sz = int(s.get("notional_1r_pct") or 0)
            usd_10k = pct_sz * 100
            src_html = f' <a href="{esc(s["source_url"])}" target="_blank" style="font-size:13px;color:var(--accent);">[信源 ↗]</a>' if s.get("source_url") else ""
            fr = s.get("funding_ann_pct")
            fr_hint = "（空头补贴多单）" if (d == "LONG" and fr is not None and fr < -5) else ""
            cat_row = (
                f'<div class="reason-row"><strong>💡 催化核查：</strong><span>{esc(s["catalyst_note"])}{src_html}</span></div>'
                if s.get("catalyst_note")
                else ""
            )
            risk_txt = resolve_risk_landmine_text(s, events)
            s_parts.append(
                f'<div class="ticket-card {d}">'
                f'<div class="ticket-head"><div class="ticket-title">'
                f'<span class="act-badge {d}">{dir_cn}</span>'
                f'<span class="coin-sym">{idx}. {esc(s["symbol"])}</span>'
                f'<span class="setup-tag">{esc(s.get("setup_label",""))} · 现价 {fmt_px(s.get("price_usd"))} ({pct_span(s.get("chg_24h"))})</span>'
                f'</div><div class="score-pill">评分 {s["score"]["total"]}/20</div></div>'
                f'<div class="order-steps">'
                f'<div class="step-box"><div class="s-label">① 怎么进场（计划触发位）</div><div class="s-main">{fmt_px(s.get("trigger_price"))}</div><div class="s-desc">{esc(s.get("trigger_rule",""))}</div></div>'
                f'<div class="step-box"><div class="s-label">② 错了在哪砍（日线止损）</div><div class="s-main" style="color:var(--red);">{fmt_px(s.get("stop_price"))} <span style="font-size:13.5px;">({stop_sign}{s.get("stop_dist_pct")}%)</span></div><div class="s-desc">{esc(s.get("stop_rule",""))}</div></div>'
                f'<div class="step-box"><div class="s-label">③ 建议开多大（按最多亏{risk_pct_str}%计）</div><div class="s-main" style="color:var(--accent);">${usd_10k:,} <span style="font-size:13.5px;">/ 每$1万本金 ({pct_sz}%)</span></div><div class="s-desc">按 {fmt_px(s.get("trigger_price"))} 进场打止损（宽 {s.get("stop_dist_pct")}%），每$1万本金亏 ≤${loss_per_10k:,}</div></div>'
                f'</div>'
                f'<div class="reason-list">'
                f'<div class="reason-row"><strong>📊 量化信号：</strong><span>{esc(s.get("quant_summary",""))}</span></div>'
                f'{cat_row}'
                f'<div class="reason-row"><strong>🛡️ 持仓排雷：</strong><span>{esc(risk_txt)}</span></div>'
                f'</div>'
                f'<div class="meta-pills">'
                f'<span class="meta-pill">14天相对大饼：{fmt_pct(s.get("rs_14d"))}</span>'
                f'<span class="meta-pill">年化资金费率：{fmt_pct(fr)}{fr_hint}</span>'
                f'<span class="meta-pill">日均波幅(ATR)：{fmt_pct(s.get("atr_pct"), 1, False)}</span>'
                f'<span class="meta-pill">合约持仓：{fmt_usd(s.get("oi_usd"))}</span>'
                f'</div></div>'
            )

    if avoid_list:
        av_rows = []
        for s in avoid_list:
            risk_txt = resolve_risk_landmine_text(s, events)
            av_rows.append(
                f'<div class="kw-item crit"><span>⛔</span><span><strong>排雷剔除 · {esc(s["symbol"])}</strong>'
                f'（原量化候选：{esc(s.get("setup_label",""))}）：因「{esc(risk_txt)}」已剔除出可执行单，建议空仓规避。</span></div>'
            )
        s_parts.append(f'<div class="key-warnings" style="margin-bottom:16px;">{"".join(av_rows)}</div>')

    if watch_list:
        w_cards = []
        for s in watch_list:
            src_html = f' <a href="{esc(s["source_url"])}" target="_blank" style="font-size:12px;color:var(--accent);">[信源 ↗]</a>' if s.get("source_url") else ""
            cat_div = f'<div style="margin-top:3px;"><strong>催化核查：</strong>{esc(s["catalyst_note"])}{src_html}</div>' if s.get("catalyst_note") else ""
            risk_txt = resolve_risk_landmine_text(s, events)
            w_cards.append(
                f'<div class="watch-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
                f'<div><strong style="font-size:18px;">{esc(s["symbol"])}</strong> <span class="muted" style="font-size:13px;">现价 {fmt_px(s.get("price_usd"))} ({pct_span(s.get("chg_24h"))})</span></div>'
                f'<span class="trend-pill DOWN_BOUNCE">窄幅收敛待变盘</span></div>'
                f'<div class="watch-triggers">'
                f'<div class="wt-box"><div class="wt-lbl">🟢 向上突破做多位</div><div class="wt-val up">{fmt_px(s.get("donchian_20d_high"))}</div></div>'
                f'<div class="wt-box"><div class="wt-lbl">🔴 向下跌破做空位</div><div class="wt-val down">{fmt_px(s.get("donchian_20d_low"))}</div></div>'
                f'</div>'
                f'<div style="font-size:13px;color:var(--text-body);line-height:1.55;">'
                f'<strong>量化结构：</strong>{esc(s.get("quant_summary",""))}'
                f'{cat_div}'
                f'<div class="muted" style="font-size:12px;margin-top:3px;">排雷：{esc(risk_txt)}</div>'
                f'</div></div>'
            )
        s_parts.append(f'<div class="watch-subhead">👀 待变盘观察池（突破前观望，勿提前猜方向）</div><div class="watch-grid">{"".join(w_cards)}</div>')

    w_trs = []
    for w in latest.get("watchlist_rows") or []:
        ts = w.get("trend_state", "RANGE_CHOP")
        pos = w.get("pos_in_20d_pct")
        if pos is not None:
            col = "var(--green)" if pos >= 65 else ("var(--red)" if pos <= 25 else "var(--amber)")
            pos_html = f'<div class="pos-cell"><div class="pos-track"><div class="pos-fill" style="width:{max(4, pos):.0f}%;background:{col};"></div></div><span>{pos:.0f}%</span></div>'
        else:
            pos_html = "—"
        note = f'<div style="font-size:11.5px;color:var(--text-muted);">{esc(w["note"])}</div>' if w.get("note") else ""
        w_trs.append(
            f'<tr><td><strong style="color:var(--text);font-size:14.5px;">{esc(w["symbol"])}</strong>{note}</td>'
            f'<td><strong style="color:var(--text);">{fmt_px(w.get("price_usd"))}</strong> ({pct_span(w.get("chg_24h"))})</td>'
            f'<td><span class="trend-pill {ts}">{esc(w.get("trend_label","—"))}</span></td>'
            f'<td>{pos_html}</td>'
            f'<td>{fmt_px(w.get("ema20"))} ({pct_span(w.get("dist_ema20_pct"))})</td>'
            f'<td>{pct_span(w.get("rs_14d"))}</td>'
            f'<td>{pct_span(w.get("funding_ann_pct"))}</td>'
            f'<td>{fmt_usd(w.get("oi_usd"))}</td></tr>'
        )
    watch_table = (
        '<table class="data-table"><thead><tr>'
        '<th>币种</th><th>现价 (24h)</th><th>日线结构</th><th>近20日位置</th>'
        '<th>20日均线 (偏离)</th><th>14天相对大饼</th><th>年化费率</th><th>合约持仓</th>'
        '</tr></thead><tbody>' + "".join(w_trs) + '</tbody></table>'
    )

    def radar_table(rows):
        if not rows:
            return '<div class="muted">暂无数据</div>'
        trs = []
        for m in rows[:6]:
            ts = m.get("trend_state", "RANGE_CHOP")
            trs.append(
                f'<tr><td><strong style="color:var(--text);">{esc(m["symbol"])}</strong></td>'
                f'<td>{fmt_px(m.get("price_usd"))} ({pct_span(m.get("chg_24h"))})</td>'
                f'<td>{pct_span(m.get("rs_14d"))}</td>'
                f'<td>{pct_span(m.get("funding_ann_pct"))}</td>'
                f'<td><span class="trend-pill {ts}">{esc(m.get("trend_label",""))}</span></td></tr>'
            )
        return (
            '<table class="data-table"><thead><tr>'
            '<th>币种</th><th>现价 (24h)</th><th>14天相对大饼</th><th>年化费率</th><th>日线趋势</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
        )

    if not events:
        ev_html = '<div class="muted">未来 14 天暂无已确认日期的重大排雷事件</div>'
    else:
        ev_trs = []
        for e in events[:12]:
            da = e.get("days_away", 99)
            r_cls = ' class="urgent-row"' if da <= 3 else ""
            cd = '<span class="warn">⏰ 今天</span>' if da <= 0 else (f'<span class="warn">⏰ {da} 天后</span>' if da <= 3 else f"{da} 天后")
            b_cls, b_txt, _ = EVENT_META.get(e.get("event_type"), ("macro", "事件", "事件"))
            ang = f'<div style="color:var(--amber);font-size:12.5px;margin-top:3px;">👉 应对：{esc(e["opportunity_angle"])}</div>' if e.get("opportunity_angle") else ""
            ev_trs.append(
                f'<tr{r_cls}><td><strong>{esc(e.get("date"))}</strong><div style="font-size:12px;">{cd}</div></td>'
                f'<td><strong style="color:var(--text);font-size:14.5px;">{esc(str(e.get("coin","")).upper())}</strong></td>'
                f'<td><span class="ev-badge {b_cls}">{b_txt}</span></td>'
                f'<td class="wrap">{esc(e.get("description"))}{ang}</td></tr>'
            )
        ev_html = '<table class="data-table"><thead><tr><th>日期 / 倒计时</th><th>标的</th><th>类型</th><th>事件内容与应对建议</th></tr></thead><tbody>' + "".join(ev_trs) + '</tbody></table>'

    ph = {
        "report_date": date_str,
        "closed_candle_date": btc.get("last_closed_date") or "—",
        "report_timestamp": latest["timestamp"].replace("T", " ")[:16] + " (北京时间)",
        "unit_risk_pct": risk_pct_str,
        "regime_hero_html": hero_html,
        "regime_kpis_html": kpis_html,
        "btc_20d_range": f'{fmt_px(btc.get("donchian_20d_low"))} ~ {fmt_px(btc.get("donchian_20d_high"))}',
        "btc_atr_text": f'{fmt_px(btc.get("atr14"))} ({fmt_pct(btc.get("atr_pct"), 1, False)})',
        "btc_chart_json": json.dumps(btc.get("chart_60d") or {}),
        "setups_html": "\n".join(s_parts),
        "watchlist_table_html": watch_table,
        "bull_radar_html": radar_table(scan.get("bull_radar")),
        "bear_radar_html": radar_table(scan.get("bear_radar")),
        "event_calendar_html": ev_html,
        "events_note_html": f'<div class="note-box">{esc(latest["events_note"])}</div>' if latest.get("events_note") else "",
    }
    html = tpl
    for k, v in ph.items():
        html = html.replace("{{" + k + "}}", str(v))
    return html


# ---------- 4. Telegram 摘要与 Git 推送 ----------

def build_telegram_message(latest, date_str):
    reg = latest["regime"]
    sc = reg["scores"]
    br = reg["breadth"]
    btc = latest["market_context"]["btc"]
    eth = latest["market_context"]["eth"]
    events = latest.get("events") or []
    code = reg.get("regime_code", "")
    r_icon = "🟢" if "BULL" in code else ("🔴" if "BEAR" in code else "🟡")
    fgi_cn = FGI_CN.get(btc.get("fear_greed_label", ""), "")

    lines = [
        f"🧭 <b>日线合约早报</b>  <code>{date_str}</code>",
        "",
        f"{r_icon} <b>{html_escape(reg.get('regime_label','—'))}</b>（{sc.get('total','—')}/20分 · 情绪 {btc.get('fear_greed','—')} {fgi_cn}）",
        f"👉 {html_escape(reg.get('posture',''))}",
        "",
        f"• <b>BTC</b> {fmt_px(btc.get('price_usd'))}（{fmt_pct(btc.get('price_change_24h'))}）{html_escape(btc.get('trend_label',''))}｜20日线 {fmt_px(btc.get('ema20'))}",
        f"• <b>ETH</b> {fmt_px(eth.get('price_usd'))}（{fmt_pct(eth.get('chg_24h'))}）｜全场 <b>{br.get('pct_above_ema20','—')}%</b> 站上20日线",
        "",
        "━━━━━━━━━━━━━━━",
    ]

    action_list, avoid_list, watch_list = partition_setups(latest.get("setups"))

    if not action_list:
        lines.append("🎯 <b>今日可执行单：暂无</b>（建议观望等右侧突破）")
    else:
        lines.append(f"🎯 <b>今日可执行单（共 {len(action_list)} 个）</b>")
        for idx, s in enumerate(action_list[:4], 1):
            tag = "🟢 做多" if s["direction"] == "LONG" else "🔴 做空"
            stop_sign = "-" if s["direction"] == "LONG" else "+"
            q_txt = (s.get("quant_summary") or "").strip()
            c_txt = (s.get("catalyst_note") or "").strip()
            why = smart_truncate(f"{q_txt}｜{c_txt}" if (q_txt and c_txt) else (q_txt or c_txt), 64)
            lines += [
                "",
                f"<b>{idx}. {tag} {html_escape(s['symbol'])}</b>（{html_escape(s.get('setup_label',''))} · {s['score']['total']}分）",
                f"• 现价：{fmt_px(s.get('price_usd'))}（{fmt_pct(s.get('chg_24h'))}）｜年化费率 {fmt_pct(s.get('funding_ann_pct'))}",
                f"• 进场：{fmt_px(s.get('trigger_price'))}",
                f"• 止损：{fmt_px(s.get('stop_price'))}（{stop_sign}{s.get('stop_dist_pct')}%）",
                f"• 仓位：<b>{size_text_cn(s.get('notional_1r_pct'))}</b>",
                f"• 信号：{html_escape(why)}",
            ]

    if avoid_list:
        av_syms = "、".join(
            f"{html_escape(s['symbol'])}（{html_escape(smart_truncate(resolve_risk_landmine_text(s, events), 36))}）"
            for s in avoid_list[:3]
        )
        lines += ["", f"⛔ <b>排雷剔除</b>：{av_syms}"]

    if watch_list:
        lines += ["", "👀 <b>变盘观察池（等突破再动）</b>"]
        for s in watch_list[:3]:
            lines.append(
                f"• <b>{html_escape(s['symbol'])}</b>（现价 {fmt_px(s.get('price_usd'))}）：上破 <b>{fmt_px(s.get('donchian_20d_high'))}</b> 做多 / 跌破 <b>{fmt_px(s.get('donchian_20d_low'))}</b> 做空"
            )

    ev_lines = []
    for e in events:
        da = e.get("days_away")
        if da is not None and 0 <= da <= 7:
            when = "今天" if da == 0 else ("明天" if da == 1 else f"{da}天后")
            t_cn = EVENT_META.get(e.get("event_type"), ("", "", "事件"))[2]
            ev_lines.append(f"• {when} ({e.get('date','')[5:]}) <b>{html_escape(str(e.get('coin','')).upper())}</b> {t_cn}：{html_escape(smart_truncate(e.get('description',''), 38))}")
    if ev_lines:
        lines += ["", "━━━━━━━━━━━━━━━", "⚠️ <b>近 7 天持仓排雷</b>", *ev_lines[:4]]

    lines += ["", f"📈 <a href=\"{PAGES_BASE}/\"><b>点击打开网页图表与自选池 →</b></a>"]
    return "\n".join(lines)


def push_git_and_telegram(html_rel_path, date_str, tg_message, force_tg=False):
    subprocess.run(["git", "add", "index.html", html_rel_path, "data/latest.json"], cwd=ROOT, check=False)
    diff_rc = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode
    if diff_rc != 0:
        subprocess.run(["git", "commit", "-m", f"Report: {date_str}"], cwd=ROOT, check=True)
    ahead = subprocess.check_output(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=ROOT).decode().strip()
    if int(ahead or 0) > 0:
        subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)

    state_path = ROOT / "data/publish-state.json"
    pub_state = load_json(state_path, {}) or {}
    if pub_state.get("last_tg_date") == date_str and not force_tg:
        print(f"[publish] Telegram already pushed for {date_str}, skipped duplicate push (pass --force-tg to resend).", flush=True)
        return

    out_cfg = load_json(ROOT / "config/output.json", {}) or {}
    tg_cfg = (out_cfg.get("formats") or {}).get("telegram") or {}
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg_cfg.get("bot_token") or ""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or tg_cfg.get("chat_id") or ""
    if not token or not chat_id:
        print("[publish] warning: telegram token/chat_id missing, skipped push")
        return

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "text": tg_message,
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read().decode())
    if resp.get("ok"):
        with open(state_path, "w") as sf:
            json.dump({"last_tg_date": date_str, "pushed_at": datetime.now(TZ).isoformat(timespec="seconds")}, sf, indent=2)
    print(f"[publish] Telegram: {'OK' if resp.get('ok') else resp.get('description', 'error')}", flush=True)


# ---------- 主入口 ----------

def _pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def primary_pipeline_in_progress(today_str, now_ts, grace_sec=PRIMARY_GRACE_SEC):
    """检测 08:05 主流程是否正在采集中或正处于 Step 2 联网核查窗口内，防止兜底任务抢跑撞车。"""
    pipe = load_json(ROOT / "data/.pipeline-run.json", {}) or {}
    if pipe.get("date") == today_str:
        if pipe.get("stage") == "collect" and (now_ts - (pipe.get("started_ts") or 0)) < 600 and _pid_alive(pipe.get("pid")):
            return f"collect.py pid={pipe.get('pid')} actively running"

    col_path = ROOT / "data/collected.json"
    col = load_json(col_path)
    if isinstance(col, dict) and col.get("date") == today_str:
        col_ts = col.get("collected_ts")
        if not col_ts and col.get("collected_at"):
            try:
                col_ts = datetime.fromisoformat(col["collected_at"]).timestamp()
            except Exception:
                col_ts = None
        if not col_ts and col_path.is_file():
            col_ts = col_path.stat().st_mtime
        if col_ts:
            age = now_ts - col_ts
            if 0 <= age < grace_sec:
                return f"today's collected.json is fresh ({int(age)}s < {grace_sec}s), waiting for Step 2"
    return None


def already_published_today(today_str):
    html_path = ROOT / "reports" / f"{today_str}_daily.html"
    latest = load_json(ROOT / "data/latest.json", {}) or {}
    btc_ok = (((latest.get("market_context") or {}).get("btc") or {}).get("price_usd") or 0) > 0
    if not (html_path.is_file() and html_path.stat().st_size > 2000 and btc_ok and latest.get("report_date") == today_str):
        return False
    st = subprocess.run(
        ["git", "status", "--porcelain", f"reports/{today_str}_daily.html", "index.html", "data/latest.json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    ahead = subprocess.run(
        ["git", "rev-list", "--count", "origin/main..HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    )
    is_clean = (st.returncode == 0 and not st.stdout.strip())
    is_pushed = (ahead.returncode == 0 and int((ahead.stdout or "0").strip() or 0) == 0)
    return is_clean and is_pushed


def main():
    if "--restore-bak" in sys.argv:
        return 0 if restore_latest_from_bak() else 1

    no_push = "--no-push" in sys.argv
    force_tg = "--force-tg" in sys.argv
    auto_fallback = "--auto-fallback" in sys.argv

    (ROOT / "data").mkdir(exist_ok=True)
    lock_file = open(ROOT / "data/.publish.lock", "w")
    try:
        lock_flags = (fcntl.LOCK_EX | fcntl.LOCK_NB) if auto_fallback else fcntl.LOCK_EX
        fcntl.flock(lock_file.fileno(), lock_flags)
    except BlockingIOError:
        print("[publish] another publish.py holds the lock, auto-fallback skipped.", flush=True)
        return 0

    now = datetime.now(TZ)
    now_ts = time.time()
    now_date_str = now.strftime("%Y-%m-%d")

    if auto_fallback:
        if already_published_today(now_date_str):
            print(f"[publish] {now_date_str} report already live, auto-fallback skipped.", flush=True)
            return 0
        busy_reason = primary_pipeline_in_progress(now_date_str, now_ts)
        if busy_reason:
            print(f"[publish] {now_date_str} primary pipeline active ({busy_reason}); auto-fallback deferred.", flush=True)
            return 0
        # 若主流程 Step 1 已成功但 Step 2 超时未发（40m~2h 内），直接复用当日完好 collected.json，无需重复拉接口
        existing_col = load_json(ROOT / "data/collected.json")
        col_age = now_ts - ((existing_col or {}).get("collected_ts") or 0)
        if isinstance(existing_col, dict) and existing_col.get("date") == now_date_str and validate_collected(existing_col) is None and col_age < 7200:
            print(f"[publish] {now_date_str} reusing valid collected.json (age={int(col_age)}s) after Step 2 timeout...", flush=True)
        else:
            print(f"[publish] {now_date_str} report not yet published at {now.strftime('%H:%M')}; running pure-quant fallback...", flush=True)
            rc = TrendCollector().run("daily", mark_pipeline=False)
            if rc != 0:
                print(f"[publish] FATAL: fallback collect failed with code {rc}; aborting.", file=sys.stderr)
                return rc

    collected = load_json(ROOT / "data/collected.json")
    err = validate_collected(collected)
    if err:
        print(f"[publish] FATAL: {err}. Refusing to overwrite latest.json or push.", file=sys.stderr)
        return 2

    date_str = collected.get("date")
    if date_str != now_date_str and "--allow-stale-collected" not in sys.argv:
        print(
            f"[publish] FATAL: collected.json date ({date_str}) != today ({now_date_str}). Run collect.py first.",
            file=sys.stderr,
        )
        return 2

    today_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    cfg = load_json(ROOT / "config/config.json", {}) or {}
    unit_risk_pct = float(((cfg.get("setups") or {}).get("unit_risk_equity_pct")) or 1.0)
    raw_overlay = load_json(ROOT / "data/overlay.json", {}) or {}

    overlay_fresh = bool(raw_overlay and raw_overlay.get("date") == date_str)
    if raw_overlay and not overlay_fresh:
        print(
            f"[publish] WARNING: overlay.json date ({raw_overlay.get('date')}) != report date ({date_str}); "
            "ignoring stale qualitative overlay fields.",
            file=sys.stderr,
        )
    overlay = raw_overlay if overlay_fresh else {}

    cands = collected.get("setups_candidates", [])
    by_id = {c["id"]: c for c in cands}
    by_sym = {c["symbol"]: c for c in cands}

    chosen_ids = overlay.get("selected_setup_ids")
    if chosen_ids:
        chosen = []
        seen_syms = set()
        for sid in chosen_ids:
            m = by_id.get(sid) or by_sym.get(str(sid).upper())
            if m and m["symbol"] not in seen_syms:
                chosen.append(dict(m))
                seen_syms.add(m["symbol"])
    else:
        chosen = [dict(c) for c in cands]
    if not chosen and cands:
        chosen = [dict(c) for c in cands]

    events = merge_and_normalize_events(
        (collected.get("previous") or {}).get("events", []),
        overlay.get("events") if isinstance(overlay.get("events"), list) else [],
        today_date,
    )

    ov_map = overlay.get("setup_overlays") or {}
    for s in chosen:
        ov = ov_map.get(s["symbol"]) or ov_map.get(s["id"]) or {}
        s["catalyst_note"] = (ov.get("catalyst_note") or "").strip() or None
        s["risk_landmine"] = (ov.get("risk_landmine") or "").strip() or None
        s["action_override"] = ov.get("action_override")
        s["source_url"] = ov.get("source_url")
        if s["action_override"] == "AVOID":
            s["notional_1r_pct"] = 0

    watch_notes = overlay.get("watchlist_notes") or {}
    watch_rows = [
        dict(w, note=watch_notes[w["symbol"]]) if w["symbol"] in watch_notes else dict(w)
        for w in collected.get("watchlist_rows", [])
    ]

    regime = dict(collected["regime"])
    raw_scores = dict(regime["scores"])
    s_br = raw_scores.get("breadth") if raw_scores.get("breadth") is not None else raw_scores.get("funding", 3)
    s_macro = raw_scores.get("macro", 3)
    if isinstance(overlay.get("macro_score_override"), int) and 1 <= overlay["macro_score_override"] <= 5:
        s_macro = overlay["macro_score_override"]
    total_sc = raw_scores["btc_trend"] + s_br + raw_scores["sentiment"] + s_macro
    r_code, r_label, r_posture = classify_regime(total_sc)

    regime.update({
        "regime_code": r_code,
        "regime_label": r_label,
        "posture": r_posture,
        "scores": {
            "btc_trend": raw_scores["btc_trend"],
            "breadth": s_br,
            "sentiment": raw_scores["sentiment"],
            "macro": s_macro,
            "total": total_sc,
        },
        "regime_note": (overlay.get("regime_note") or "").strip() or None,
    })

    warnings = build_key_warnings(collected["btc"], watch_rows, events)

    latest = {
        "schema_version": "2.1-slim",
        "report_date": date_str,
        "overlay_applied": overlay_fresh,
        "unit_risk_equity_pct": unit_risk_pct,
        "timestamp": now.isoformat(timespec="seconds"),
        "session": "daily",
        "regime": regime,
        "setups": chosen,
        "watchlist_rows": watch_rows,
        "market_scan": {
            "breadth": regime["breadth"],
            "bull_radar": collected.get("bull_radar", []),
            "bear_radar": collected.get("bear_radar", []),
            "neg_funding_leaders": collected.get("neg_funding_leaders", []),
        },
        "events": events,
        "events_note": (overlay.get("events_note") or "").strip() or None,
        "market_context": {
            "btc": collected["btc"],
            "eth": collected["eth"],
            "global": collected["global"],
        },
        "warnings": warnings,
        "_sources": collected.get("_sources", {}),
    }

    replaced_latest = False
    try:
        (ROOT / "reports").mkdir(exist_ok=True)
        md_path = ROOT / "reports" / f"{date_str}_daily.md"
        md_text = render_markdown(latest)

        html_rel = f"reports/{date_str}_daily.html"
        html_path = ROOT / html_rel
        html_text = render_html(latest, date_str)

        leftover = re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", html_text)
        if leftover:
            raise RuntimeError(f"Unfilled HTML template placeholders: {leftover}")

        tmp_latest = ROOT / "data/latest.json.tmp"
        with open(tmp_latest, "w") as f:
            json.dump(latest, f, ensure_ascii=False, indent=2)
        os.replace(tmp_latest, ROOT / "data/latest.json")
        replaced_latest = True

        md_path.write_text(md_text)
        html_path.write_text(html_text)
        shutil.copy2(html_path, ROOT / "index.html")
        (ROOT / "data/.pipeline-run.json").unlink(missing_ok=True)
    except Exception as exc:
        print(f"[publish] FATAL build error: {exc}", file=sys.stderr)
        if replaced_latest:
            restore_latest_from_bak()
        return 2

    print(
        f"[publish] built {md_path.name} ({len(md_text.splitlines())}L) + {html_path.name} + index.html "
        f"(overlay={'fresh' if overlay_fresh else 'none/stale'}, events={len(events)})",
        flush=True,
    )

    if not no_push:
        tg_msg = build_telegram_message(latest, date_str)
        push_git_and_telegram(html_rel, date_str, tg_msg, force_tg=force_tg)
        print(f"[publish] live -> {PAGES_BASE}/", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
