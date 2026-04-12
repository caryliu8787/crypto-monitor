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
| CoinGlass | `open-api.coinglass.com/public/v2/funding` | 资金费率（全交易所） |
| CoinGlass | `open-api.coinglass.com/public/v2/open_interest` | 未平仓合约 |
| CoinGlass | `open-api.coinglass.com/public/v2/long_short` | 多空比 |
| Blockchain.com | `api.blockchain.info/charts/estimated-transaction-volume?timespan=7days&format=json` | BTC 交易量 |
| DeFiLlama | `/v2/chains` | 全链 TVL |
| DeFiLlama | `/overview/fees` | 协议费用/收入 |
| DeFiLlama | `/summary/fees/{protocol}?dataType=dailyRevenue` | LINK/ARB 收入明细 |
| DeFiLlama | `stablecoins.llama.fi/stablecoinchains` | 各链稳定币供应 |
| Alternative.me | `/fng/` | Fear & Greed Index |

**WebFetch 页面抓取（API 不覆盖的，按优先级尝试）：**

| 数据 | 主源 | 备用源 |
|------|------|--------|
| ETF 流向 | `farside.co.uk/btc/` | `sosovalue.com/assets/etf/us-btc-spot` |
| 代币解锁 | `token.unlocks.app/` | — |

**WebSearch 仅限定性信息（参见「数据真实性」规则）：** 新闻/合作/路线图进展、MVRV/SOPR 趋势方向（但数值必须来自 API 或页面原文）、鲸鱼转账事件、期权 MaxPain、技术面支撑阻力位、宏观事件

**降级链路（每个数据字段按此顺序尝试）：**
1. 免费 API JSON → 取返回值
2. 页面抓取（主源 → 备用源）→ 从 HTML 原文提取数字
3. 都失败 → 字段写 `null`，报告写「数据暂缺」
4. **禁止**：从 WebSearch 结果中提取数值填入 JSON

**数据来源标注：** `data/latest.json` 中增加 `_sources` 对象，记录关键字段的数据来源。格式：
```json
"_sources": {
  "btc_price": "coingecko_api",
  "btc_sparkline": "coingecko_api",
  "etf_daily_flow": "farside_page",
  "mvrv_zscore": null,
  "funding_rate": "coinglass_api"
}
```
来源值为: `coingecko_api` | `coinglass_api` | `blockchain_api` | `defillama_api` | `alternative_api` | `farside_page` | `sosovalue_page` | `token_unlocks_page` | `null`（未获取）。禁止出现 `websearch` 作为数值字段的来源。

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

## 数据真实性（硬规则，不可违反）

1. **数值型字段（价格、sparkline 序列、ETF 流向金额、链上指标数值、TVL、费用等）必须且只能来自 API JSON 返回值或页面原文中可直接提取的数字。** 禁止从 WebSearch 摘要中推断、估算、外推或编造任何数值。
2. **WebSearch 仅可用于定性信息：** 新闻事件、合作公告、趋势判断、路线图进展等文字描述。不可用于填充 `data/latest.json` 中的数值字段。
3. **数据缺失时的处理：**
   - `data/latest.json` 中该字段写 `null`
   - Markdown 报告中该指标写「数据暂缺」
   - HTML 图表：placeholder 用空数组 `[]`，前端自动显示「数据暂缺」提示
4. **sparkline 数据必须来自 CoinGecko `/coins/bitcoin?sparkline=true` 返回的 `sparkline_in_7d.price` 数组原值。** 如果 API 调用失败，`{{btc_sparkline_data}}` 填 `[]`，不可手工构造价格序列。
5. **ETF 流向数据必须来自 farside.co.uk 页面抓取的原始表格数值。** 如果页面无法访问或解析失败，相关字段写 `null`，不可从搜索结果拼凑。
6. **与上期数据对比时，如果某字段上期为 `null` 或本期为 `null`，则跳过该字段的 delta 计算**，不可用默认值替代。

---

## 错误处理

| 场景 | 处理 |
|------|------|
| WebFetch 失败 | WebSearch 补充定性信息；数值字段标 `null` / 「数据暂缺」 |
| WebSearch 无结果 | 标记「数据暂缺」|
| config 损坏 | 停止，写 `reports/YYYY-MM-DD_error.md` |
| 历史数据缺失 | 跳过对比 |
| 推送失败 | 记录错误，不影响报告 |

---

## 调度

由 macOS launchd 驱动，plist 位于 `~/Library/LaunchAgents/com.crypto-monitor.{morning,evening}.plist`。
plist 调用 `scripts/run-report.sh {session}`，该脚本负责：
1. 日志轮转（按日期命名 `logs/YYYY-MM-DD_{session}.log`，7 天自动清理）
2. 杀残留进程 + 等待网络
3. 调用 `claude -p` 生成报告
4. 验证产出文件（HTML + MD 存在且非空）
5. 成功 → 调用 `telegram-push.sh` 推送
6. 失败 → 发送 Telegram 告警（包含失败原因和日志路径）

系统时区为 Asia/Shanghai (UTC+8)，plist 中 Hour 直接使用本地时间。
- 晨报：08:00 UTC+8
- 晚报：20:00 UTC+8
