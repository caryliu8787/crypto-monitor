# 加密货币日线永续合约趋势雷达 2.0

服务于**低倍永续合约 · 日线级别趋势交易**的自动化决策辅助系统。
每日 **08:05 (UTC+8，即 UTC 00:00 日线刚收线后 5 分钟)** 执行早报，配合 `scripts/pulse.py` 每 2 小时纯脚本静默巡检盘中异动。

**核心原则：** 日线收盘结构确认 | 高流动性合约池 | 客观止损与 1% 风险仓位标尺 | 禁止编造任何数值 | API 确定性计算优先

---

## 架构与执行流水线（每次定时运行严格按此 6 步执行，耗时 ~2-3 分钟）

### Step 1: 运行前归档与备份
执行 `./scripts/pre-run.sh`：清理过期日志、将上期 `data/latest.json` 归档至 `data/history/`、生成 `data/latest.json.bak` 失败回滚备份。

### Step 2: 确定性量化采集与日线结构扫描
执行 `python3 scripts/collect.py daily`，产出 `data/collected.json`：
- **合约池**：自动拉取 OKX Swap V5 + Hyperliquid 全市场永续合约实时成交额、持仓量（OI）与资金费率，筛选 Top 75 高流动性主流合约 + `config/watchlist.json` 核心自选池。
- **日线指标**：拉取 200 根 `1Dutc` K 线（严格区分已收盘日线 `close_1d` 与实时价 `price_usd`），精确计算 `EMA20 / EMA50 / EMA200`、`20D / 55D` 唐奇安通道高低点、Wilder `ATR(14)`、20D 量能比、布林带宽压缩分位、相对 BTC 强弱（`RS 7d/14d/30d`）。
- **日线剧本扫描器**：自动筛选 5 类标准结构（`20D 通道突破`、`多头回踩 EMA20`、`逆势抗跌逼空`、`20D 支撑破位`、`空头反抽 EMA20` 及 `波动率极度压缩`），并计算触发位、日线结构止损位与 **1% 账户风险名义仓位占比**。
- **宏观与板块**：采集 DeFiLlama 稳定币与链 TVL、CoinGecko 板块轮动（`market_cap_change_24h`）与主导率、CoinMetrics MVRV、Alternative.me FGI。

### Step 3: 定向定性核查与持仓排雷（模型核心职责，预算受控）
读取 `data/collected.json` 中的 `setups_candidates`（前 5–8 名）、`watchlist_rows` 与 `previous.events`：
1. **剧本排雷与催化验证**（WebSearch ≤ 6 次）：仅对入围 Top 剧本的币种检索近期重大催化剂（主网/提案/回购/安全事件）与**未来 7–14 天大额代币解锁**。
   - 若某候选币种在 48h 内面临巨额解锁或突发安全负面，可在 `overlay.json` 中将其标注 `"action_override": "AVOID"` 或从 `selected_setup_ids` 剔除并换入下一顺位干净结构。
   - 若无特殊单日新闻，如实写「纯日线量价结构驱动，无异常新闻干扰」，**绝不强行编造消息归因**。
2. **前瞻事件排雷日历**（WebSearch ≤ 4 次）：维护未来 14–30 天有**明确日期**的大额代币解锁（尤其流通占比 ≥2%）、重要升级与宏观 FOMC / CPI 发布日。

### Step 4: 写入定性叠加层 `data/overlay.json`
模型**不手改任何量化数值**，仅写纯定性文件 `data/overlay.json`：
```json
{
  "date": "YYYY-MM-DD",
  "regime_note": "结合日线均线广度、ETF/宏观窗口的 1-2 句定性补充",
  "macro_score_override": 3,
  "selected_setup_ids": ["...", "..."],
  "setup_overlays": {
    "SYMBOL": {
      "catalyst_note": "定性催化或链上基本面验证结论",
      "risk_landmine": "7-14d 解锁/事件排雷核查结果",
      "action_override": null,
      "source_url": "https://..."
    }
  },
  "watchlist_notes": {
    "SOL": "可选简短备注"
  },
  "sector_note": "板块强弱简评",
  "etf_qualitative": {
    "btc_etf_flow_text": "定性描述（禁止把搜索摘要数字填进数值字段）",
    "eth_etf_flow_text": "定性描述"
  },
  "events": [
    {
      "id": "coin-unlock-YYYYMMDD",
      "coin": "SYMBOL",
      "event_type": "unlock|upgrade|macro",
      "date": "YYYY-MM-DD",
      "description": "事件客观描述",
      "opportunity_angle": "多单避险或顺空头结构应对建议",
      "source_url": "https://...",
      "status": "upcoming"
    }
  ],
  "events_note": "排雷日历补充说明"
}
```

### Step 5: 确定性组装与渲染
执行 `python3 scripts/assemble.py daily`：
- 自动合并 `collected.json`（100% 数值来源）+ `overlay.json`（定性文字），评估 `config/alerts.json` 告警规则；
- 生成 `data/latest.json`、`reports/YYYY-MM-DD_daily.md`、`reports/latest-alert.txt`；
- 自动调用 `scripts/render-html.py` 生成交互式图表页面 `reports/YYYY-MM-DD_daily.html`。
- 验证 `.md` 与 `.html` 存在且非空；若中途失败，用 `cp data/latest.json.bak data/latest.json` 恢复上期快照。

### Step 6: 推送发布
执行 `./scripts/telegram-push.sh <YYYY-MM-DD> daily`：提交并推送 HTML 与 `latest.json` 至 GitHub Pages，向 Telegram 发送今日交易剧本摘要与完整报告链接。

---

## 盘中脉冲监控（纯脚本，零模型消耗）
- 脚本：`python3 scripts/pulse.py`（支持 `--dry-run` 测试）
- 调度：macOS `launchd`（`scripts/com.cary.crypto-pulse.plist`）每 2 小时运行一次
- 作用：持续积累 4h/24h 真实 OI 历史快照；仅在主流合约出现**盘中放量突破日线 20D 高低点**、**极端负费率逼空**或**自选池偏离 EMA20 达 3x ATR** 时推送 Telegram（同币种同类信号 6 小时冷却防刷屏）。

---

## 数据真实性硬规则（不可违反）
1. **全部价格、均线、ATR、涨跌幅、成交额、OI、资金费率、市值数值必须 100% 来自 `collect.py` API 返回与确定性计算**，严禁手填或从 WebSearch 估算。
2. **没有高赔率剧本时如实留空或仅列观察项**，严禁为了凑数硬凑低质量信号。
3. **事件无明确日期不入日历**；查不到单日新闻时如实标注「纯量价结构驱动」。
