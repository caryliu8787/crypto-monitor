## 机会看板

> 以下机会来自全市场扫描（异动/板块轮动/trending/TVL 动量）和事件驱动发现，按评分排序。
> 扩散度：🔴 首发（主流媒体未报道）| 🟡 早期（仅专业社区讨论）| 🟢 已扩散（主流媒体已覆盖）
> 评分 /20 = 催化剂强度 + 时间窗 + 拥挤度（反向）+ 风险（反向），各维 1-5。

{{#if has_new_opportunities}}
### 🆕 本期新发现
{{new_opportunities}}
{{/if}}

{{#if has_tracking_opportunities}}
### 📌 持续跟踪
{{tracking_opportunities}}
{{/if}}

{{#if has_triggered_opportunities}}
### ✅ 已触发 / 已过期
{{triggered_opportunities}}
{{/if}}

{{#if has_stale_summary}}
> {{stale_count}} 项机会持续静默跟踪，无进展（详见 JSON，不逐条展示）
{{/if}}

> 每条格式：**[扩散度] [币种] 标题（{{score}}/20）** — 论点 | 时间窗 | 验证方式（来源: URL）
> 没有发现新机会 = 如实写「本期无新机会」。绝不编造或拔高旧信息。
