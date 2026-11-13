# 加密货币日线永续合约趋势雷达 2.0（精简版）

服务于**低倍永续合约 · 日线级别趋势交易**的每日早报与盘中异动监控系统。

- **固定网页入口**：https://caryliu8787.github.io/crypto-monitor/（同步归档至 `reports/YYYY-MM-DD_daily.html`）
- **核心原则**：UTC 日线收盘确认 ｜ Top 200 主流高流动性合约池（`OI ≥ $15M`）｜ 1% 账户风险定仓 ｜ 严禁编造任何数值

---

## 每日早报 3 步流水线（每日 `08:05` UTC+8 自动执行）

### Step 1: 量化采集与归档
运行 `python3 /Users/cary/projects/crypto-monitor/scripts/collect.py`：
- 自动轮转过期日志、归档上期 `data/latest.json` 至 `data/history/` 并生成 `.bak` 备份；
- 拉取 OKX Swap V5 + Hyperliquid 全市场永续合约，结合 CoinGecko Top 200 纯加密白名单与 `config/config.json` 筛选高流动性合约池；
- 拉取 220 根 `1Dutc` K 线计算 `EMA20/50/200`、`20D/55D` 唐奇安通道、Wilder `ATR(14)`、布林带宽压缩分位、相对 BTC 强弱（`RS 7d/14d`）及资金费率/OI，扫描日线标准交易剧本并输出 `data/collected.json`。

### Step 2: 定向催化验证与解锁排雷（模型职责，WebSearch ≤ 8 次）
读取 `data/collected.json` 中的 `setups_candidates`（前 5 名）与 `previous.events`，将纯定性结论写入 `data/overlay.json`（**严禁手改任何量化数值**）：
```json
{
  "date": "YYYY-MM-DD",
  "regime_note": "结合宏观窗口与日线盘面的 1-2 句实战提示",
  "macro_score_override": 3,
  "selected_setup_ids": ["..."],
  "setup_overlays": {
    "SYMBOL": {
      "catalyst_note": "近期催化剂验证（无特殊消息则如实写『纯日线量价结构驱动』）",
      "risk_landmine": "未来 7-14 天解锁或事件排雷结论",
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
运行 `python3 /Users/cary/projects/crypto-monitor/scripts/publish.py`（本地仅预览不推送可加 `--no-push`）：
- 合并 `collected.json`（100% 数值来源）+ `overlay.json`（定性文字）；
- 生成 `data/latest.json`、`reports/YYYY-MM-DD_daily.md`、`reports/YYYY-MM-DD_daily.html` 并同步更新根目录 `index.html`；
- 自动 `git commit & push` 至 GitHub Pages 并推送移动端精简摘要至 Telegram。

---

## 盘中静默脉冲监控（纯脚本，零模型消耗）
- 脚本：`python3 /Users/cary/projects/crypto-monitor/scripts/pulse.py`（支持 `--dry-run`），由 macOS `launchd` 每 2 小时运行一次。
- 仅在主流合约盘中破 20D 日线高低点、极端负费率逼空或自选币偏离 `EMA20` 达 `3x ATR` 时推送 Telegram（6 小时冷却防刷屏）。
