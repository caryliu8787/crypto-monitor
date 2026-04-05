## {{section_number}}、{{coin_name}} 深度跟踪

### 核心指标
| 指标 | 数值 | 变化 | 意义 |
|------|------|------|------|
| 价格 | {{price}} | {{change_24h}} (24h) / {{change_7d}} (7d) | -- |
{{specific_metrics_rows}}

> specific_metrics_rows: 从 coins.json 中该币种的 metrics.specific 字段读取，逐行填充。
> 每个指标必须包含「意义」列，解释该数值对投资决策的影响。

### 催化剂追踪
{{#each catalysts}}
- [{{status_icon}}] **{{description}}** — {{latest_update}}
{{/each}}

> 催化剂列表从 coins.json 的 metrics.catalysts 读取。
> status_icon: pending=⬜, progressing=🔄, triggered=✅, failed=❌
> latest_update: 从本期搜索结果中提取最新进展，如无新进展写「暂无更新」。

### 新合作/集成
{{partnerships_and_integrations}}

> 如无新合作，注明「本期无新合作公告」。不要编造。

### 与上期对比
{{delta_vs_previous}}

---
