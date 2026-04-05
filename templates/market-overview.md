## 一、市场概览（BTC 视角）

### BTC 核心价格指标
| 指标 | 当前值 | 24h 变化 | 7d 变化 | 信号 |
|------|--------|----------|---------|------|
| 价格 | {{btc_price}} | {{btc_24h_change}} | {{btc_7d_change}} | {{price_signal}} |
| 恐惧贪婪指数 | {{fear_greed_index}} | 上期: {{fear_greed_prev}} | -- | {{fear_greed_label}} |
| BTC 主导率 | {{btc_dominance}} | {{dominance_24h_change}} | {{dominance_7d_change}} | {{dominance_signal}} |
| 山寨季指数 | {{altseason_index}}/100 | -- | -- | {{altseason_label}} |

### BTC ETF 资金流向
| 指标 | 数值 | 趋势 |
|------|------|------|
| 今日净流入 | {{etf_daily_flow}} | {{etf_daily_trend}} |
| 本周净流入 | {{etf_weekly_flow}} | {{etf_weekly_trend}} |
| 累计 AUM | {{etf_cumulative_aum}} | -- |

### BTC 链上指标
| 指标 | 数值 | 信号 | 含义 |
|------|------|------|------|
| MVRV 比率 | {{mvrv_ratio}} | {{mvrv_signal}} | >3.5 超买, <1 超卖 |
| SOPR | {{sopr}} | {{sopr_signal}} | >1 获利卖出, <1 亏损卖出 |
| 交易所储备 | {{exchange_reserves}} | {{reserves_trend}} | 下降=积累, 上升=抛压 |
| 资金费率 | {{funding_rate}} | {{funding_signal}} | 正=多头拥挤, 负=空头 |
| 未平仓合约 | {{open_interest}} | {{oi_trend}} | 上升=杠杆增加 |
| 期权最大痛点 | {{options_max_pain}} | -- | 本周到期锚定价 |

### 宏观日历（未来 7 天）
| 日期 | 事件 | 预期影响 | 状态 |
|------|------|----------|------|
{{macro_events_rows}}

> 如无法获取宏观日历数据，注明「数据暂缺」并跳过此表。

### BTC 技术面关键位
- 关键支撑: {{btc_key_support}}（来源: {{support_source}}）
- 关键阻力: {{btc_key_resistance}}（来源: {{resistance_source}}）
- 趋势判断: {{btc_trend_direction}}
- 与上期对比: {{btc_trend_vs_prev}}

### 对山寨的影响判断
{{altcoin_impact_analysis}}

> 评判依据: BTC 趋势方向 + 主导率变化 + 资金费率 + 山寨季指数 + 恐惧贪婪综合判断。
> 结论应明确给出: 适合加仓山寨 / 减仓山寨 / 观望不动。

---

### 跨链 TVL 对比
| 链 | TVL | 24h 变化 | 7d 变化 | TVL 占比 |
|----|-----|----------|---------|---------|
{{cross_chain_tvl_rows}}

### 跨链 DEX 24h 交易量对比
| 链 | 24h DEX 量 | 变化 | 主要 DEX |
|----|-----------|------|---------|
{{cross_chain_dex_rows}}

> 跨链对比数据来源: DeFiLlama。如 WebFetch 失败，使用 WebSearch 补充。
