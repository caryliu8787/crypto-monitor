## 市场环境（进场时机参考）

### BTC 核心指标
| 指标 | 当前值 | 24h 变化 | 信号 |
|------|--------|----------|------|
| 价格 | {{btc_price}} | {{btc_24h_change}} | {{price_signal}} |
| 恐惧贪婪指数 | {{fear_greed_index}} | 上期: {{fear_greed_prev}} | {{fear_greed_label}} |
| BTC 主导率 | {{btc_dominance}} | {{dominance_change}} | {{dominance_signal}} |
| 总市值 | {{total_market_cap}} | -- | -- |

### 周期指标
| 指标 | 数值 | 信号 | 新鲜度 |
|------|------|------|--------|
| MVRV 比率 | {{mvrv_ratio}} | {{mvrv_signal}} | {{mvrv_freshness}} |
| 资金费率 | {{funding_rate}} | {{funding_signal}} | {{funding_freshness}} |
| 未平仓合约 | {{open_interest}} | {{oi_signal}} | -- |

> 新鲜度标注规则：连续 ≥3 session 数值不变 → 显示「⚠️ N 期未更新」。
> 数值必须来自 API 或页面原文。无法获取 → 写「数据暂缺」。

### ETF 资金流向（定性）
- BTC ETF: {{btc_etf_flow_text}}
- ETH ETF: {{eth_etf_flow_text}}

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

> 无持仓视角：此分数回答「现在该积极布局机会，还是持币观望」。
