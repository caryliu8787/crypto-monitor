# 加密货币日线永续合约趋势雷达 2.1（精简版）

服务于**低倍永续合约 · 日线级别趋势交易**的每日早报与盘中异动监控系统。

- **固定网页入口**：https://caryliu8787.github.io/crypto-monitor/（同步归档至 `reports/YYYY-MM-DD_daily.html`）
- **核心原则**：UTC 日线收盘确认 ｜ Top 150 主流高流动性合约池（`OI ≥ $10M`）｜ 按进场触发价计 1% 账户风险定仓 ｜ 严禁编造任何数值或未核查结论

---

## 每日早报 3 步流水线（每日 `08:05` UTC+8 自动执行 + `08:20` 系统兜底）

### Step 1: 量化采集与熔断归档
运行 `python3 /Users/cary/projects/crypto-monitor/scripts/collect.py`（**若退出码非 `0`，必须立即中止流水线并汇报上游接口异常，严禁继续执行 Step 2 或 `publish.py`**）：
- 自动轮转过期日志，仅在 `data/latest.json` 完好时备份 `latest.json.bak` 并归档至 `data/history/`；
- 拉取 OKX Swap V5 + Hyperliquid 全市场永续合约，结合 CoinGecko Top 150 纯加密白名单与 `config/config.json`（`OI ≥ $10M`、`24h 成交 ≥ $15M`）筛选高流动性主流合约池（核心接口全挂或有效合约 `< 15` 时自动清理旧 `collected.json` 并以退出码 `2` 熔断）；
- 拉取 220 根 `1Dutc` K 线计算 `EMA20/50/200`、`20D` 前值与现值唐奇安通道、Wilder `ATR(14)`、布林带宽分位 + 20D 振幅、相对 BTC 强弱（`RS 7d/14d`）及 `OKX+HL` 持仓加权资金费率，结合当前市场阶段（`regime_code`）扫描可执行单池（最多 4 个）与窄幅观察池（最多 3 个），输出 `data/collected.json`。

### Step 2: 定向催化验证与解锁排雷（模型职责，WebSearch ≤ 8 次）
读取 `data/collected.json` 中的 `regime`、`setups_candidates` 与 `previous.events`，按当日市场阶段挑选顺势标的并将纯定性结论写入 `data/overlay.json`（**严禁手改任何量化数值；`date` 必须等于 `collected.json` 的 `date`，过期 `overlay.json` 会被自动忽略**）：
- **顺势与排雷规则**：多头趋势期剔除逆势空单，空头承压期仅保留强独立 α 多单或反抽受阻空单；若候选标的近 7 天内有大额悬崖解锁或重大利空，设置 `"action_override": "AVOID"`（发布脚本会自动将其移出可执行单并归零仓位）。
- **日历增量合并**：`overlay.events` 会与 `previous.events` 按 `(coin, event_type, date)` **增量合并**（不会清空旧日历）；如需删除已取消事件，传 `"status": "cancelled"`。

```json
{
  "date": "YYYY-MM-DD",
  "regime_note": "结合宏观窗口与日线盘面的 1-2 句实战提示",
  "macro_score_override": 3,
  "selected_setup_ids": ["..."],
  "setup_overlays": {
    "SYMBOL": {
      "catalyst_note": "近期催化剂验证（无特殊消息则如实写『纯日线量价结构驱动』）",
      "risk_landmine": "经核查的未来 7-14 天解锁或事件排雷结论",
      "action_override": null,
      "source_url": "https://..."
    }
  },
  "watchlist_notes": {},
  "events": [
    {
      "id": "coin-unlock-YYYYMMDD",
      "coin": "SYMBOL",
      "event_type": "unlock|upgrade|macro",
      "date": "YYYY-MM-DD",
      "description": "客观事件描述（无明确日期不入日历）",
      "opportunity_angle": "持仓避险或顺势应对建议",
      "status": "upcoming"
    }
  ],
  "events_note": "排雷日历一句话提示"
}
```

### Step 3: 一键组装、渲染与发布
运行 `python3 /Users/cary/projects/crypto-monitor/scripts/publish.py`（本地预览加 `--no-push`；备份恢复加 `--restore-bak`）：
- 校验 `collected.json` 完整性与日期、核对 `overlay.json` 日期、同步重算 `macro_score_override` 后的 `regime` 阶段与操作原则；
- 生成 `data/latest.json`、`reports/YYYY-MM-DD_daily.md`、`reports/YYYY-MM-DD_daily.html` 并同步更新根目录 `index.html`；
- 自动 `git commit & push` 至 GitHub Pages 并推送移动端精简摘要至 Telegram。

---

## 双层自动调度与盘中脉冲监控
1. **主力早报（`08:05` Antigravity Cron）**：完整执行 Step 1 → Step 2（联网核查催化与解锁）→ Step 3。
2. **系统级兜底早报（`08:20` macOS `launchd` · `com.cary.crypto-daily`）**：运行 `python3 scripts/publish.py --auto-fallback`。若 `08:05` 已成功发布当日早报则秒退；若桌面端未开导致未发，则自动跑 `collect.py` + 纯量化诚实模式发布，确保早报永不断更。
3. **盘中静默脉冲（每 2 小时 macOS `launchd` · `com.cary.crypto-pulse`）**：运行 `python3 scripts/pulse.py`（`--dry-run` 完全只读零落盘），覆盖早报候选剧本、核心自选与高流动性主流币，统一采用 `OKX+HL` 加权费率口径监控盘中新鲜 20D 突破、极端负费率逼空、均线 `3x ATR` 偏离与多头费率过热（6 小时独立冷却）。
