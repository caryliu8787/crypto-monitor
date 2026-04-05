## {{section_number}}、历史趋势对比

### 与上期报告对比（{{prev_session_label}}）
| 指标 | 上期 | 本期 | 变化 | 趋势 |
|------|------|------|------|------|
| BTC 价格 | {{prev_btc_price}} | {{curr_btc_price}} | {{btc_price_delta}} | {{btc_trend_arrow}} |
| 恐惧贪婪 | {{prev_fgi}} | {{curr_fgi}} | {{fgi_delta}} | {{fgi_trend_arrow}} |
| BTC 主导率 | {{prev_dominance}} | {{curr_dominance}} | {{dom_delta}} | {{dom_trend_arrow}} |
{{#each coins}}
| {{ticker}} 价格 | {{prev_price}} | {{curr_price}} | {{price_delta}} | {{trend_arrow}} |
{{/each}}

### 本周趋势（7 日滚动）
| 币种 | 周初价 | 当前价 | 周变化 | 本周关键事件 |
|------|--------|--------|--------|-------------|
{{weekly_trend_rows}}

> 周初价取自 7 天前的历史快照。如无 7 天前数据，跳过此表并注明。

### 连续信号追踪
{{consecutive_signals}}

> 示例输出:
> - 恐惧贪婪指数已连续 5 天处于「恐惧」区间（<40）
> - BTC 已连续 3 天收于 $85,000 上方
> - ETH/BTC 比率已连续 7 天下降
> 
> 从 data/history/ 中的历史快照计算。首次运行时跳过，注明「历史数据不足，暂无连续信号」。
