# 加密货币每日情报监控系统

## 系统概述
本系统是基于 Claude Code 的自动化加密货币情报引擎。每天早晚各执行一次（08:00 / 20:00 UTC+8），自动采集、分析并输出多币种市场情报报告。

**核心原则：**
- 所有币种配置、告警规则、输出格式均由 `config/` 目录下的 JSON 文件驱动，本文件只定义执行逻辑
- 禁止编造任何数据。找不到的指标标记为「数据暂缺」
- WebFetch 优先获取结构化数据，失败后降级为 WebSearch
- 搜索词动态生成，包含当天日期，不硬编码年份或绝对价格

---

## 执行流程

### Phase 0: 初始化

1. **读取配置文件：**
   - `config/coins.json` — 币种注册表（哪些币、什么优先级、关注什么指标）
   - `config/alerts.json` — 告警规则（5 类告警、动态阈值）
   - `config/output.json` — 输出格式配置（Markdown/HTML Dashboard/JSON/告警摘要）

2. **读取历史数据：**
   - `data/latest.json` — 上一期报告的数据快照（用于历史对比）
   - 如果文件不存在（首次运行），标记 `is_first_run = true`，后续跳过历史对比

3. **验证配置：**
   - 确认所有 JSON 文件可正常解析
   - 如果任何配置文件损坏，停止执行并写入错误报告到 `reports/YYYY-MM-DD_error.md`

4. **确定执行参数：**
   - 当前日期（YYYY-MM-DD 格式）
   - 当前时段：08:00 前后为 `morning`，20:00 前后为 `evening`
   - 当前月份的英文名（用于搜索词构造，如 "April 2026"）

---

### Phase 1: 结构化数据采集（WebFetch 优先）

对 `coins.json` 中所有币种的 `data_sources.webfetch_urls` 逐一执行 WebFetch。同时获取全局数据源：

**Tier 1: 免费 API（精确数据，优先使用）：**
| API 端点 | 提取目标 |
|----------|----------|
| `api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,chainlink,arbitrum,monad,plume-network&vs_currencies=usd&include_24hr_change=true&include_7d_change=true&include_market_cap=true` | 全币种价格、24h/7d 变化、市值 |
| `api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=true&community_data=false&developer_data=true&sparkline=true` | BTC 7d sparkline (168 点)、ATH/ATL、开发者 GitHub 数据 |
| `api.coingecko.com/api/v3/coins/{coingecko_id}?...&developer_data=true` | 各币种开发者活跃度（对 coins.json 中每个币种执行） |
| `api.llama.fi/v2/chains` | 全链 TVL |
| `api.llama.fi/overview/fees?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true&dataType=dailyFees` | 200+ 协议日费用/收入数据 |
| `api.llama.fi/summary/fees/{protocol}?dataType=dailyRevenue` | 单协议收入明细（对 LINK、ARB 等执行） |
| `stablecoins.llama.fi/stablecoinchains` | 各链稳定币供应 |
| `api.alternative.me/fng/` | Fear & Greed Index |

**Tier 2: WebFetch 页面抓取（半结构化）：**
| 数据 | URL | 提取目标 |
|------|-----|----------|
| BTC ETF 流向 | `https://farside.co.uk/btc/` | 今日和本周净流入 |
| 代币解锁 | `https://token.unlocks.app/` | LINK/ARB/MONAD/PLUME 未来 30 天解锁 |

**Tier 3: WebSearch（定性数据和付费 API 降级）：**
- MVRV / SOPR / 交易所储备（Glassnode/CryptoQuant 付费 → 搜索分析文章）
- 资金费率 / OI / 清算 / 多空比（CoinGlass 需认证 → 搜索）
- 鲸鱼大额转账、期权 Max Pain、技术分析支撑阻力
- 各币种新闻、合作、DAO 提案等定性信息

**WebFetch 规则：**
- 对每个 URL 发起 WebFetch，使用精确的提取提示（如："Extract the total TVL number and 24h change percentage for Ethereum, Solana, Arbitrum, Monad"）
- 如果 WebFetch 返回错误（403、超时、空内容），记录 `[WARN] WebFetch failed for {url}`，在 Phase 2/3 中使用 WebSearch 补充
- 不要对同一个失败的 URL 重试 WebFetch

---

### Phase 2: BTC 深度搜索（必须先于山寨分析完成）

BTC 是所有山寨币分析的前提。先完成 BTC 数据采集。

**动态搜索词生成规则：**
- 价格类：`"{CoinName} {Ticker} price {当天英文日期，如 April 3 2026}"`
- 新闻类：`"{CoinName} news today"` 或 `"{CoinName} latest news this week"`
- 不要在搜索词中硬编码年份用于路线图/升级类查询，使用 `"latest"` 或 `"upcoming"`
- 解锁类：`"{Ticker} token unlock schedule next"` 而非具体日期

**BTC 搜索序列（6-8 条）：**
1. `"Bitcoin BTC price today {日期}"` — 当前价格和基本市场数据
2. `"Bitcoin spot ETF daily net inflow outflow {日期}"` — ETF 资金流向（补充 Phase 1）
3. `"Bitcoin whale large transactions exchange deposit withdrawal"` — 鲸鱼行为
4. `"Federal Reserve FOMC {当月英文} {年份} crypto market"` — 宏观政策和日历
5. `"Bitcoin dominance percentage altcoin season index {当月}"` — BTC 主导率
6. `"Bitcoin MVRV ratio SOPR on-chain analysis"` — 链上指标
7. `"Bitcoin futures funding rate open interest"` — 衍生品数据（补充 Phase 1）
8. `"Bitcoin options max pain expiry {最近周五日期}"` — 期权数据

**补充搜索：** 如果 Phase 1 中 BTC 相关的 WebFetch（ETF flows、Fear & Greed、资金费率）失败，在此阶段用对应的 WebSearch 补充。

---

### Phase 3: 山寨币数据采集

遍历 `coins.json` 中所有 `enabled: true` 且 `id != "btc"` 的币种，按 priority 顺序处理。

**搜索深度按优先级分配：**
| 优先级 | 最大搜索数 | 说明 |
|--------|-----------|------|
| P0 | 6-8 条 | 覆盖所有 search_focus + custom_searches |
| P1 | 4-5 条 | 核心 search_focus + 关键 custom_searches |
| P2 | 3-4 条 | 价格 + 最关键的 1-2 个 search_focus |

**对每个币种：**
1. 生成价格搜索词：`"{CoinName} {Ticker} price today {日期}"`
2. 根据 `search_focus` 数组生成对应搜索词：
   - `"l2_data"` → `"Ethereum L2 TVL total value locked update"`
   - `"staking_rate"` → `"Ethereum staking rate percentage"`
   - `"dex_volume"` → `"{CoinName} DEX trading volume 24h"`
   - `"partnerships"` → `"{CoinName} new partnerships integrations {当月}"`
   - `"ccip_volume"` → `"Chainlink CCIP cross-chain transaction volume"`
   - `"staking_tvl"` → `"{CoinName} staking TVL"`
   - `"reserve_accumulation"` → `"Chainlink Reserve token accumulation"`
   - `"tvl"` → `"{CoinName} TVL DeFi"`
   - `"fee_revenue"` → `"{CoinName} sequencer revenue fees"`
   - `"unlock_schedule"` → `"{Ticker} token unlock vesting schedule next"`
   - `"dao_proposals"` → `"{CoinName} DAO governance proposal"`
   - `"ecosystem_growth"` → `"{CoinName} ecosystem new projects dApps"`
   - `"development_updates"` → `"{CoinName} development update latest"`
3. 执行 `custom_searches` 中的自定义搜索词
4. 补充 Phase 1 中该币种 WebFetch 失败的数据

---

### Phase 4: 分析与对比

**4.1 历史对比（如非首次运行）：**
- 从 `data/latest.json` 读取上期数据
- 计算每个币种的 delta：
  - 与上期对比（session-over-session）
  - 如果有 7 天前的 `data/history/` 快照，计算周环比
- 分类变化幅度：
  - 显著正向（绿色）：>+5%
  - 微幅变动（中性）：±2% 以内
  - 显著负向（红色）：>-5%
- 计算连续信号（如：恐惧贪婪连续 N 天处于某区间）

**4.2 告警评估：**
- 读取 `config/alerts.json`
- 对每条告警规则，用采集到的数据逐一评估
- 对于 `condition: "detected_in_search"` 类型的告警（如黑客、监管），从搜索结果中判断是否有相关负面新闻
- 对于动态阈值告警（如 BTC 支撑位），使用 Phase 2 搜索到的技术分析数据
- 记录所有触发的告警，按 severity 排序（critical > warning > info）

**4.3 市场阶段评估：**
| 维度 | 评分标准（1-5） | 数据来源 |
|------|----------------|----------|
| BTC 趋势 | 1=强跌, 3=中性, 5=强涨 | 价格变化 + 技术面趋势 |
| 资金面 | 1=大幅流出, 3=平衡, 5=大幅流入 | ETF 流向 + 交易所储备变化 |
| 情绪面 | 1=极度恐惧, 3=中性, 5=极度贪婪 | 恐惧贪婪指数 + 资金费率 |
| 宏观面 | 1=强利空, 3=中性, 5=强利好 | 宏观事件 + 政策走向 |

总分 /20 → 对应市场阶段：
- 16-20: 强牛市（可积极加仓）
- 12-15: 偏多（可适度加仓，控制仓位）
- 8-11: 中性（观望为主）
- 4-7: 偏空（减仓防守）
- 1-3: 强熊市（最低仓位或空仓）

**4.4 生成各币种建议：**
- 基于市场阶段 + 各币种自身催化剂进展 + 价格位置
- 每个建议包含：建议内容 + 理由 + 时间框架（短期/中期/长期）

**4.5 跨链对比分析：**
- 使用 Phase 1 获取的 DeFiLlama TVL 数据
- 对比各链 TVL 占比变化、DEX 交易量排名

---

### Phase 5: 报告生成

**5A. Markdown 报告：**

1. **读取模板文件：**
   - 对 BTC：读取 `templates/market-overview.md`
   - 对每个山寨币：根据 `coins.json` 中的 `template` 字段读取对应模板
   - 读取 `templates/historical-comparison.md`

2. **组装报告：**

```
# 加密货币每日情报简报
**日期：** {YYYY-MM-DD}  |  **时段：** {morning/evening}  |  **执行时间：** {HH:MM UTC+8}

---

## 0. 关键变化摘要
{如有 critical/warning 告警，在此列出}
{相比上期报告的主要变化摘要（3-5 条最重要的变化）}

---

{templates/market-overview.md 填充后的内容 — 含 BTC 全部指标 + 跨链对比}

---

{对每个山寨币，按优先级顺序，使用对应模板填充}

---

{templates/historical-comparison.md 填充后的内容}

---

## 操作建议

### 当前市场阶段
| 维度 | 状态 | 评分 |
|------|------|------|
| ... | ... | .../5 |
| **综合** | **{阶段判断}** | **{总分}/20** |

### 信号面板
| 信号 | 方向 | 状态 | 置信度 | 依据 |
|------|------|------|--------|------|
{从告警评估结果和技术分析生成}

### 各币种建议
| 币种 | 建议 | 理由 | 时间框架 |
|------|------|------|----------|
{从 Phase 4.4 生成}

### 本日行动项
{具体可执行的建议，如 "关注 BTC 是否守住 $XX,XXX 支撑" 等}
```

3. **告警标记：**
   - 如有任何 severity=critical 的告警触发，在报告文件最开头添加：
   ```
   ⚠️ **重大告警** ⚠️
   {告警列表}
   ---
   ```

**5B. HTML Dashboard：**

1. **读取模板：** 读取 `templates/dashboard.html`
2. **替换所有 `{{placeholder}}` 变量：**
   - KPI 数据：`{{fgi_value}}`, `{{market_score_total}}`, `{{btc_dominance}}`, `{{btc_ath_change}}`, `{{altseason_index}}` 等
   - BTC sparkline：将 CoinGecko 7d sparkline 数组嵌入为 `{{btc_sparkline_data}}`（JS 数组格式如 `[66412, 66500, ...]`）
   - 支撑/阻力：`{{btc_support}}`, `{{btc_resistance}}`
   - 链上指标：`{{mvrv_zscore}}`, `{{sopr_sth}}`, `{{sopr_aggregate}}`, `{{exchange_reserves_trend}}` 等
   - 衍生品：`{{funding_rate}}`, `{{open_interest}}`, `{{options_max_pain}}`, `{{put_call_ratio}}`
   - ETF 图表数据：`{{etf_chart_labels}}`（日期数组）, `{{etf_chart_data}}`（金额数组）
   - 生态数据：`{{tvl_chart_labels}}`, `{{tvl_chart_data}}`, `{{stablecoin_table_html}}`, `{{protocol_revenue_table_html}}`
   - 开发者活跃度：`{{dev_chart_labels}}`, `{{dev_chart_data}}`
   - 告警/信号/建议：`{{alerts_html}}`, `{{catalysts_html}}`, `{{recommendations_html}}`, `{{action_items_html}}`
   - 历史数据：`{{history_dates}}`, `{{history_fgi}}`, `{{history_scores}}`, `{{heatmap_html}}`, `{{consecutive_signals_html}}`
   - 报告元数据：`{{report_date}}`, `{{report_session}}`, `{{report_timestamp}}`
3. **HTML 片段生成规则：**
   - 告警列表 (`{{alerts_html}}`): 每条告警一行，格式 `<div class="alert-item alert-{severity}"><span class="alert-dot"></span>{text}<span class="alert-badge">{SEVERITY}</span></div>`
   - 推荐卡片 (`{{recommendations_html}}`): 每个币种一张卡片，border-color 按建议类型（green=加仓, orange=观望, red=减仓）
   - 数据表格 (`{{protocol_revenue_table_html}}`): 标准 HTML table，收入/TVL 比率列用颜色编码
4. **保存结果** — 替换完成后即为完整独立 HTML 文件，可直接在浏览器打开

---

### Phase 6: 输出与归档

根据 `config/output.json` 中启用的格式逐一输出：

**6.1 Markdown 报告：**
- 保存到 `reports/YYYY-MM-DD_{session}.md`

**6.2 HTML Dashboard：**
- 保存到 `reports/YYYY-MM-DD_{session}.html`
- 在浏览器中打开即可查看交互式仪表盘（Chart.js 图表需要网络加载 CDN）

**6.3 JSON 数据快照（必选）：**
- 将本次采集的所有结构化数据保存为 `data/latest.json`
- 如果已存在 `data/latest.json`，先将其移动到 `data/history/YYYY-MM-DD_{prev_session}.json`
- JSON 结构示例：
```json
{
  "timestamp": "2026-04-03T08:00:00+08:00",
  "session": "morning",
  "coins": {
    "btc": {
      "price": 84500,
      "change_24h": -1.2,
      "change_7d": 3.0,
      "dominance": 54.3,
      "fear_greed": 45,
      "etf_weekly_flow": 120000000,
      "mvrv": 1.8,
      "sopr": 1.02,
      "exchange_reserves": 2100000,
      "funding_rate": 0.01,
      "key_support": 82000,
      "key_resistance": 87000
    },
    "eth": { "price": 3200, "change_24h": -0.8, "eth_btc": 0.0379, "tvl": 48500000000, "staking_rate": 28.5 },
    "sol": { "price": 178, "change_24h": 1.5, "tvl": 8200000000, "dex_volume": 3500000000 },
    "link": { "price": 14.5, "change_24h": -0.3, "staking_tvl": 650000000, "ccip_volume": 12000000 },
    "arb": { "price": 0.85, "change_24h": -1.1, "tvl": 3200000000, "next_unlock": "2026-05-15" },
    "monad": { "price": 0.45, "change_24h": 2.3, "tvl": 320000000, "weekly_fees": 85000 }
  },
  "market_score": { "btc_trend": 3, "funding": 3, "sentiment": 3, "macro": 3, "total": 12 },
  "alerts_triggered": []
}
```

**6.4 告警摘要文本：**
- 保存到 `reports/latest-alert.txt`
- 单行格式：`{日期} {时间} | BTC ${价格} ({24h变化}%) | FGI {指数} | {告警摘要或 "No critical alerts"}`

**6.5 Notion 推送（可选）：**
- 仅当 `config/output.json` 中 `notion.enabled = true` 且 `database_id` 不为空时执行
- 使用 Notion MCP 工具创建新页面
- 如果推送失败，记录错误但不影响主流程

**6.6 Telegram 推送（可选）：**
- 仅当 `config/output.json` 中 `telegram.enabled = true` 且 `bot_token` 和 `chat_id` 不为空时执行
- 执行命令: `bash scripts/telegram-push.sh {YYYY-MM-DD} {session}`
- 脚本会自动发送:
  1. 文本摘要（`reports/latest-alert.txt` 内容，HTML 格式化）
  2. HTML 报告文件（作为附件，手机可下载后打开）
  3. Markdown 报告文件（作为附件）
- 配置 Telegram Bot:
  1. 在 Telegram 中找 @BotFather，发送 `/newbot` 创建机器人，获取 Bot Token
  2. 给机器人发一条消息，然后访问 `https://api.telegram.org/bot{TOKEN}/getUpdates` 获取 Chat ID
  3. 填入 `config/output.json` 的 `telegram.bot_token` 和 `telegram.chat_id`

**6.7 历史清理：**
- 删除 `data/history/` 中超过 30 天的 JSON 文件
- 使用 bash: `find data/history/ -name "*.json" -mtime +30 -delete`

---

## 搜索策略规则

### 动态搜索词构造
- 始终包含当天日期或当月月份，确保结果时效性
- 不要在路线图/升级类搜索中硬编码具体年份，使用 `"latest"` 或 `"upcoming"`
- 解锁日期类搜索使用 `"next"` 而非具体日期

### 数据源优先级
1. **WebFetch**（结构化页面抓取）— 精确度高，适用于 DeFiLlama、Etherscan 等
2. **WebSearch**（搜索引擎）— 覆盖面广，适用于新闻、分析文章
3. 如果两者都无法获取某数据，标记「数据暂缺」，不编造

### 数据真实性
- 所有价格、TVL、指标数据必须来自搜索或抓取结果
- 如果搜索结果中的数据相互矛盾，采用更权威来源（如 CoinGecko > 小型网站）
- 技术分析（支撑/阻力位）引用至少 1 个来源

---

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| WebFetch 返回 403/超时/空内容 | 记录警告，该数据点改用 WebSearch |
| WebSearch 无有效结果 | 报告中标记「数据暂缺」 |
| config JSON 解析失败 | 停止执行，写错误报告到 `reports/YYYY-MM-DD_error.md` |
| `data/latest.json` 不存在或损坏 | 跳过历史对比，注明「首次运行，无历史对比数据」 |
| Notion 推送失败 | 记录错误，不影响 Markdown 和 JSON 输出 |
| 单个币种所有搜索均失败 | 在该币种 section 注明「本期数据采集失败」，继续处理其他币种 |

---

## 调度配置

### 方式一：Claude Code CronCreate（推荐）

```
Morning report (08:00 UTC+8):
  CronCreate(
    cron: "57 7 * * *",
    prompt: "执行每日加密货币情报监控。读取 CLAUDE.md 执行流程，从 Phase 0 到 Phase 6 完整执行，生成 morning 报告。",
    durable: true,
    recurring: true
  )

Evening report (20:00 UTC+8):
  CronCreate(
    cron: "3 20 * * *",
    prompt: "执行每日加密货币情报监控。读取 CLAUDE.md 执行流程，从 Phase 0 到 Phase 6 完整执行，生成 evening 报告。",
    durable: true,
    recurring: true
  )
```

> 注意：分钟数偏移避免集群拥堵。recurring + durable 任务 7 天后自动过期，需定期重新创建。

### 方式二：系统 launchd（备用，不受 7 天限制）

如需永久调度，可创建 macOS launchd plist，调用：
```bash
cd ~/projects/crypto\ monitor && claude -p "执行每日加密货币情报监控。读取 CLAUDE.md 执行流程，从 Phase 0 到 Phase 6 完整执行，生成 {session} 报告。"
```

---

## 目录结构参考

```
crypto monitor/
├── CLAUDE.md                    ← 本文件（纯执行逻辑）
├── config/
│   ├── coins.json               ← 币种注册表（7 币种：BTC/ETH/SOL/LINK/ARB/MONAD/PLUME）
│   ├── alerts.json              ← 告警规则
│   └── output.json              ← 输出格式配置（MD/HTML/JSON/告警/Telegram/Notion）
├── templates/
│   ├── dashboard.html           ← HTML Dashboard 模板（Chart.js + 5 Tab）
│   ├── market-overview.md       ← BTC 市场总览模板
│   ├── coin-standard.md         ← 标准币种模板（ETH/SOL）
│   ├── coin-deep-track.md       ← 深度跟踪模板（LINK/ARB）
│   ├── coin-watchlist.md        ← 观察仓模板（MONAD/PLUME）
│   └── historical-comparison.md ← 历史对比模板
├── reports/                     ← 生成的报告（.md + .html）
│   └── latest-alert.txt         ← 最新告警摘要
├── data/
│   ├── latest.json              ← 最新数据快照
│   └── history/                 ← 历史数据归档
└── .claude/
    └── settings.local.json
```
