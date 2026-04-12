## 市场环境

### BTC 核心指标
| 指标 | 当前值 | 24h 变化 | 信号 |
|------|--------|----------|------|
| 价格 | {{btc_price}} | {{btc_24h_change}} | {{price_signal}} |
| 恐惧贪婪指数 | {{fear_greed_index}} | 上期: {{fear_greed_prev}} | {{fear_greed_label}} |
| BTC 主导率 | {{btc_dominance}} | {{dominance_change}} | {{dominance_signal}} |

### ETF 资金流向
| 指标 | 数值 | 趋势 |
|------|------|------|
| 今日净流入 | {{etf_daily_flow}} | {{etf_daily_trend}} |
| 本周净流入 | {{etf_weekly_flow}} | {{etf_weekly_trend}} |

### BTC 链上指标
| 指标 | 数值 | 信号 | 新鲜度 |
|------|------|------|--------|
| MVRV Z-Score | {{mvrv_zscore}} | {{mvrv_signal}} | {{mvrv_freshness}} |
| SOPR (7d) | {{sopr_7d}} | {{sopr_signal}} | {{sopr_freshness}} |
| 交易所储备 | {{exchange_reserves}} | {{reserves_signal}} | {{reserves_freshness}} |
| 鲸鱼月度累积 | {{whale_accumulation}} | {{whale_signal}} | {{whale_freshness}} |
| 资金费率 | {{funding_rate}} | {{funding_signal}} | {{funding_freshness}} |
| 未平仓合约 | {{open_interest}} | {{oi_signal}} | -- |

> 新鲜度标注规则：连续 ≥3 session 数值不变 → 显示「⚠️ N 期未更新」。
> 链上指标数值必须来自 API 或页面原文。无法获取 → 写「数据暂缺」。

### 技术面
- 支撑: {{btc_key_support}} | 阻力: {{btc_key_resistance}} | 趋势: {{btc_trend_direction}}

### 宏观日历（3 天内 + 重大事件）
| 日期 | 事件 | 预期影响 |
|------|------|----------|
{{macro_events_rows}}

### 市场评分 {{market_score_total}}/20 — {{market_phase}}
| BTC 趋势 | 资金面 | 情绪面 | 宏观面 |
|----------|--------|--------|--------|
| {{score_btc_trend}}/5 | {{score_funding}}/5 | {{score_sentiment}}/5 | {{score_macro}}/5 |
