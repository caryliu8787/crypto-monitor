# 加密货币每日情报监控系统

自动化加密货币情报引擎，每天 08:00 / 20:00 (UTC+8) 执行。

**核心原则：** 配置驱动（`config/` JSON）| 禁止编造数据 | API 优先，WebSearch 兜底 | 搜索词含当天日期，不硬编码年份

---

## Phase 0: 初始化

读取 `config/coins.json`（币种）、`config/alerts.json`（告警）、`config/output.json`（输出格式）。
读取 `data/latest.json`（上期数据，用于对比）。不存在则跳过对比。
确定日期、时段（morning/evening）、当月英文名。

---

## Phase 1: API 数据采集

**优先用免费 API（WebFetch JSON 端点）：**

| 来源 | 端点 | 数据 |
|------|------|------|
| CoinGecko | `/api/v3/simple/price?ids={所有币}&vs_currencies=usd&include_24hr_change=true&include_7d_change=true&include_market_cap=true` | 全币种价格/变化/市值 |
| CoinGecko | `/api/v3/coins/bitcoin?sparkline=true&developer_data=true` | BTC sparkline(168点)/ATH/GitHub |
| DeFiLlama | `/v2/chains` | 全链 TVL |
| DeFiLlama | `/overview/fees` | 协议费用/收入 |
| DeFiLlama | `/summary/fees/{protocol}?dataType=dailyRevenue` | LINK/ARB 收入明细 |
| DeFiLlama | `stablecoins.llama.fi/stablecoinchains` | 各链稳定币供应 |
| Alternative.me | `/fng/` | Fear & Greed Index |

**WebFetch 页面抓取（API 不覆盖的）：** ETF 流向 (`farside.co.uk/btc/`)、代币解锁 (`token.unlocks.app/`)

**WebSearch 兜底（付费 API 降级）：** MVRV/SOPR/交易所储备、资金费率/OI/多空比、鲸鱼转账、期权 MaxPain、技术面支撑阻力、新闻/合作等定性信息

失败处理：WebFetch 失败 → WebSearch 补充。都失败 → 标记「数据暂缺」。

---

## Phase 2: BTC 深度搜索（先于山寨）

动态生成 6-8 条搜索词，覆盖：价格、ETF、鲸鱼、宏观/FOMC、主导率/山寨季、MVRV/SOPR 链上、资金费率/OI、期权 MaxPain。

搜索词规则：含当天日期、不硬编码年份、路线图类用 `"latest"`、解锁类用 `"next"`。

---

## Phase 3: 山寨币数据

遍历 `coins.json` 中 `enabled: true` 的非 BTC 币种。搜索深度按优先级：P0 6-8条 | P1 4-5条 | P2 3-4条。

根据每个币种的 `search_focus` 和 `custom_searches` 字段动态生成搜索词。

---

## Phase 4: 分析

1. **历史对比：** 与 `data/latest.json` 上期数据计算 delta。变化 >±5% 标为显著。计算连续信号。
2. **告警评估：** 逐条评估 `config/alerts.json` 中的规则，按 severity 排序。
3. **市场阶段评估（4维 × 1-5分 = /20）：**
   - BTC 趋势 | 资金面（ETF+储备）| 情绪面（FGI+费率）| 宏观面
   - 16-20 强牛 | 12-15 偏多 | 8-11 中性 | 4-7 偏空 | 1-3 强熊
4. **各币种建议：** 建议 + 理由 + 时间框架（短/中/长期）
5. **跨链对比：** TVL 占比、稳定币、协议收入/TVL 资本效率

---

## Phase 5: 报告生成

**Markdown：** 读取 `templates/` 下各模板文件，填充数据，组装为完整报告。告警置顶。

**HTML：** 读取 `templates/dashboard.html`，替换所有 `{{placeholder}}` 变量。图表数据嵌入为 JS 数组。生成的 HTML 为单页富文本报告，可直接在浏览器打开。

---

## Phase 6: 输出

| 输出 | 路径 | 说明 |
|------|------|------|
| Markdown | `reports/YYYY-MM-DD_{session}.md` | 文本报告 |
| HTML | `reports/YYYY-MM-DD_{session}.html` | 可视化报告 |
| JSON 快照 | `data/latest.json` | 结构化数据（旧的归档到 `data/history/`）|
| 告警摘要 | `reports/latest-alert.txt` | 单行摘要 |
| Telegram | `bash scripts/telegram-push.sh` | 推送摘要+链接到 GitHub Pages |
| Notion | MCP 工具 | 可选，`output.json` 中启用 |

历史清理：`find data/history/ -name "*.json" -mtime +30 -delete`

---

## 错误处理

| 场景 | 处理 |
|------|------|
| WebFetch 失败 | WebSearch 兜底 |
| WebSearch 无结果 | 标记「数据暂缺」|
| config 损坏 | 停止，写 `reports/YYYY-MM-DD_error.md` |
| 历史数据缺失 | 跳过对比 |
| 推送失败 | 记录错误，不影响报告 |

---

## 调度

```
CronCreate(cron: "57 7 * * *", prompt: "执行加密货币情报监控，Phase 0-6 完整执行，morning 报告。", durable: true, recurring: true)
CronCreate(cron: "3 20 * * *", prompt: "执行加密货币情报监控，Phase 0-6 完整执行，evening 报告。", durable: true, recurring: true)
```

> 7 天自动过期，需重建。备用：macOS launchd 调用 `claude -p "..."`
