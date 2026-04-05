## {{section_number}}、{{coin_name}} 状况

| 指标 | 当前值 | 24h 变化 | 7d 变化 |
|------|--------|----------|---------|
| 价格 | {{price}} | {{change_24h}} | {{change_7d}} |
{{#if eth}}
| ETH/BTC | {{eth_btc_ratio}} | {{eth_btc_change}} | -- |
| L2 总 TVL | {{l2_total_tvl}} | {{l2_tvl_change}} | -- |
| 质押率 | {{staking_rate}} | -- | -- |
| Gas (Gwei) | {{gas_gwei}} | -- | -- |
{{/if}}
{{#if sol}}
| DEX 24h 交易量 | {{dex_24h_volume}} | {{dex_volume_change}} | -- |
| TVL | {{tvl}} | {{tvl_change}} | -- |
| TPS | {{tps}} | -- | -- |
{{/if}}

**与上期对比:**
{{delta_vs_previous}}

**重要事件:**
{{important_events}}

> 如无重要事件，注明「本期无重大事件」。不要编造事件。
