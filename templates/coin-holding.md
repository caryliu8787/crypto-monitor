{{!-- P0 (LINK/ETH): 完整展示 | P1 (Monad): 中等展示 | P2 (SOL/ARB/PLUME): 一行模式 --}}

{{#if is_p2}}
| {{ticker}} | {{price}} | {{change_24h}} | {{headline}} |
{{else}}
## {{coin_name}} 持仓追踪

### 核心指标
| 指标 | 数值 | 变化 | 意义 |
|------|------|------|------|
| 价格 | {{price}} | {{change_24h}} (24h) | -- |
{{specific_metrics_rows}}

{{#if catalysts}}
### 催化剂状态
{{#each catalysts}}
- [{{status_icon}}] **{{description}}** — {{detail}}
{{/each}}
{{/if}}

### 一手信源发现
{{alpha_findings}}

> 如无新发现，写「本期一手信源扫描无新进展」。

{{#if partnerships}}
### 新合作/集成
{{partnerships}}
{{/if}}

### 与上期对比
{{delta_vs_previous}}

---
{{/if}}
