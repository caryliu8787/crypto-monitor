# 加密货币机会发现引擎

自动化加密货币机会发现系统，每天 04:00 (UTC+8) 执行一次。当前无持仓，目标是**发现值得研究的机会**。

**核心原则：** 机会发现优先 | 全市场扫描 + 事件驱动 | 禁止编造数据 | API 优先 | 一手信源 > 媒体报道

---

## Phase 0: 初始化

读取 `config/scan-config.json`（币池过滤 + 板块追踪 + 评分参数 + 调用预算）、`config/alerts.json`（告警规则）、`config/watchlist.json`（用户钉住的关注币）、`config/output.json`（输出格式 + 可选 API key）。
读取 `data/latest.json`（上期数据，用于对比、机会/事件跨期携带和新鲜度校验）。不存在则跳过对比。
**兼容性：** 若上期数据是旧 schema（含 `holdings`/`alpha_signals`），只复用 `market_context` 内的可比字段，机会与事件从零开始建立。
确定日期，时段固定为 daily（历史数据中的 morning/evening 为旧调度遗留，按正常上期数据对待）。

---

## Phase 1: API 数据采集

**全部用免费 API。** 若 `config/output.json` 的 `api_keys.coingecko_demo` 非空，CoinGecko 请求附加 header `x-cg-demo-api-key`；否则匿名调用（限速 5-15 次/分钟，**将 CoinGecko 调用与其他来源交错发起，避免连发触发 429**）。

**大响应端点必须用 `curl -s` 存临时文件 + `jq`/`python3` 本地精确过滤**（250 币池、derivatives、chains 等）。**禁止用网页抓取工具的摘要模式处理大数组**——摘要会漏币（2026-07-07 实测：摘要模式扫 250 币池漏掉 ANSEM +36%、GROVE +30% 等 top movers，与 trending 交叉比对才发现）。网页抓取仅用于小 JSON 端点和网页。

| 来源 | 端点 | 数据 |
|------|------|------|
| CoinGecko | `/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1&price_change_percentage=24h,7d,30d` | 250 币扫描池（价格/24h/7d/30d 变化/市值/成交量） |
| CoinGecko | `/api/v3/search/trending` | 热搜币（新币 bypass 的依据） |
| CoinGecko | `/api/v3/coins/categories` | 板块市值 + 24h 变化（板块轮动） |
| CoinGecko | `/api/v3/global` | 总市值、BTC dominance |
| CoinGecko | `/api/v3/coins/bitcoin?sparkline=true` | BTC sparkline（在 `market_data.sparkline_7d.price`，168 点） |
| CoinGecko | `/api/v3/derivatives?include_tickers=unexpired` | 资金费率 + 未平仓合约（筛选 Binance (Futures) 的 BTCUSDT，取 `funding_rate` 和 `open_interest`；响应约 8MB） |
| CoinMetrics | `community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur&frequency=1d&page_size=1` | MVRV 比率（`CapMVRVCur`） |
| DeFiLlama | `api.llama.fi/v2/chains` | 全链 TVL（与上期对比得 TVL 动量） |
| DeFiLlama | `stablecoins.llama.fi/stablecoinchains` | 各链稳定币供应 |
| Alternative.me | `api.alternative.me/fng/` | Fear & Greed Index |

**按需定向调用（仅对入围候选，不做全量）：**

| 数据 | 端点 | 说明 |
|------|------|------|
| 协议收入 | `api.llama.fi/summary/fees/{protocol}?dataType=dailyRevenue` | 候选币需要基本面佐证时用 |
| 代币解锁 | 网页抓取 `tokenomist.ai`（原 token.unlocks.app，已改名） | 部分可靠：解锁日期/分配比例通常可提取，精确数量常缺失→缺失写 `null` |

> **已废弃数据源（不再尝试）：**
> - ~~farside.co.uk / sosovalue.com~~ — 403
> - ~~CoinGlass 免费端点~~ — 需 API key
> - ~~CryptoQuant 交易所储备~~ — 抓取失败
> - ~~DeFiLlama `/emissions` 及 defillama.com/unlocks 页面~~ — 402 付费 / 403（2026-07 实测）
> - ~~fapi.binance.com 直连~~ — 地理封锁 451
> - ~~DeFiLlama `/overview/fees` 全量~~ — 23MB 响应且只服务旧持仓需求，改用定向 `/summary/fees/{protocol}`

**无免费 API 的字段（直接写 `null`）：** ETF 日度流向、交易所储备、鲸鱼月度累积、SOPR。报告中可用 WebSearch 做定性描述，JSON 不填数字。

**降级链路：** 免费 API JSON → 页面抓取提取原文数字 → 都失败写 `null`、报告写「数据暂缺」。**禁止**从 WebSearch 结果提取数值填入 JSON。

---

## Phase 2: 全市场机会扫描（核心阶段）

**2.1 异动币筛选（纯数据，不耗调用）**
从 250 币池按 `scan-config.json` 过滤：市值 ≥ `min_market_cap_usd`、24h 成交 ≥ `min_volume_24h_usd`、排除 `exclude_categories`。
按 |24h 变化| 和 |7d 变化| 综合排序，取前 `top_movers_reported` 个。
**新币 bypass：** 出现在 trending 或有 TGE/新上所背景的币不受市值/成交量门槛限制。

**2.2 板块轮动（纯数据）**
对 `categories_tracked` 中每个板块，市值与上期快照（`market_scan.sector_rotation`）对比。
连续 ≥2 期同向变化 = 轮动信号（记录 `trend_sessions`）。上期无数据则本期只记录基线。

**2.3 Trending × TVL 动量交叉（纯数据）**
`/search/trending` 结果与 DeFiLlama 链 TVL 变化交叉：热搜币所在链 TVL 同步上升 = 更强信号。

**2.4 定性归因（WebSearch，预算受控）**
仅对 2.1-2.3 入围的候选（≤ `websearch_candidates_max` 个）逐个 WebSearch「{币名} + 今日日期」查涨跌原因：
- 找到明确催化剂（升级/合作/上所/叙事）→ 记入 `movers[].reason`，并评估是否值得升级为 `opportunities[]` 条目
- 查不到原因 → `reason` 写「原因未明」，不编造

**搜索词规则：** 含当天日期 | 不硬编码年份 | 路线图类用 `"latest"` | 解锁类用 `"next"`

---

## Phase 3: 事件驱动机会

前瞻事件日历，持久化在 `data/latest.json` 的 `events[]`，跨期携带：

1. **携带**：读上期 `events[]`，重算每条 `days_away`；`date < today` 的标记 `status: "passed"`（保留一期供报告回顾，下期删除）
2. **解锁**：对高市值候选/watchlist 币网页抓取 `tokenomist.ai` 查解锁 cliff（日期可提取则记录，数量缺失写 `null`）
3. **升级/ETF/上所**：WebSearch（≤ `websearch_events_max` 次）已知的近期主网升级、ETF 审批窗口、大所上币计划——**只记录有明确日期或明确时间窗的事件**
4. 每个事件附 `opportunity_angle`（定性）：如「解锁前避险 vs 解锁后企稳吸筹」「升级前抢跑 vs sell-the-news」

**事件 id 规则：** `{coin_id}-{event_type}-{YYYYMMDD}`，与上期按 id 匹配，避免重复建条。

---

## Phase 4: 分析

### 4.1 机会评分与生命周期
对 Phase 2/3 发现的每个机会候选，4 维评分（各 1-5 分，总分 /20）：
- `catalyst_strength` 催化剂强度：确定性高、影响大 = 高分
- `time_window` 时间窗：1-4 周内可验证 = 高分；遥遥无期 = 低分
- `crowding` 拥挤度（反向）：搜索 Google News 查扩散程度——无报道 🔴=5 | 仅专业媒体 🟡=3-4 | 主流已发 🟢=1-2
- `risk` 风险（反向）：流通盘极薄、纯 meme 无基本面、临近大解锁 = 低分

**生命周期**（跨期携带，id 规则 `{coin_id}-{论点slug}`；先按币种+标题与上期模糊匹配，匹配不上才建新 id）：
`new`（本期新发现）→ `tracking`（持续跟踪）→ `triggered`（催化剂兑现）/ `expired`(时间窗过期/逻辑失效)
- 上期已有的机会：有新进展则更新 detail 和评分；无新信息保持原状（**不编造进展**）
- `sessions_tracked` 计数递增
- `sessions_since_progress` 计数：本期有**实质进展**则归 0，否则 +1。实质进展 = 催化剂状态变化 / 评分任一维度变化 / 新增可引用信源。**单纯价格波动不算进展。**

### 4.2 新鲜度校验
对 `market_context` 数值字段逐字段与上期比对：`mvrv_ratio`, `funding_rate`, `open_interest`, `fear_greed`, `dominance`。
连续 ≥3 期值不变 → 写入 `_freshness`，报告标注「⚠️ 数据已 N 期未更新」。**绝不**静默复读上期数据当新数据。`null` 字段不参与校验。

### 4.3 事件状态更新
按 Phase 3 结果更新 `events[]`；触发 `event_within_48h` 告警的事件在报告中前置。

### 4.4 告警评估
逐条评估 `config/alerts.json` 全部规则（price/cycle/macro/ecosystem/cross_coin/opportunity），按 severity 排序写入 `alerts[]`。

### 4.5 市场阶段评估（4维 × 1-5分 = /20）——进场时机参考
- BTC 趋势 | 资金面（稳定币供应+TVL 动量）| 情绪面（FGI+费率）| 宏观面
- 16-20 强牛 | 12-15 偏多 | 8-11 中性 | 4-7 偏空 | 1-3 强熊
- 当前无持仓，此分数回答的是：**现在是该积极布局机会，还是持币观望**

### 4.6 机会优先级排序
综合评分 + 扩散度 + 市场环境，输出「值得深挖」清单：每项给出论点、时间窗、验证方式（看什么信号确认/证伪）。不给买卖建议（无持仓），框架是「值得花时间研究的优先级」。

### 4.7 防膨胀规则（硬规则）
报告长度必须收敛在 ~200 行。以下三条按顺序机械执行，**不是判断题**：

**(a) 老化降级：** `sessions_since_progress` ≥ `stale_after_sessions`（5）且未触发 → 状态改 `stale`。适用于 `tracking` 和 `new`，无例外——`sessions_tracked` 再大也不是留在 `tracking` 的理由。

**(b) 看板限额：** `### 📌 持续跟踪` 一节最多列 `tracking_board_max`（10）条，按 `score.total` 降序取前 N。超出的**不逐条展示**，并入 (c) 的折叠行。

**(c) 折叠汇总：** `stale` 条目 + (b) 溢出条目在末尾折叠为一行：「N 项机会持续静默跟踪（见 JSON）」，只列 symbol + 评分。JSON 中保留完整条目以维持连续性。**禁止把静默或溢出条目逐条重复打印。**

**长度兜底：** md 写完若仍 > 250 行，优先砍「持续跟踪」节的条目数（降低有效 `tracking_board_max`）重写该节，**不要**逐行手工裁剪已写好的报告——那会耗尽看门狗预算导致 HTML 生成不及（2026-07-27~29 实测连续 3 期因此失败）。

---

## Phase 5: 报告生成

**报告结构（~200 行，机会优先）：**
1. 机会看板（按评分排序，🔴🟡🟢扩散度着色）→ `templates/opportunity-board.md`
2. 全市场扫描（异动榜 + 板块轮动 + trending + 链 TVL 动量）→ `templates/market-scan.md`
3. 事件日历（按日期升序，48h 内高亮）→ `templates/event-calendar.md`
4. 市场环境（BTC + 周期指标，进场时机参考）→ `templates/market-overview.md`
5. 关注名单（仅当 `config/watchlist.json` 非空时渲染，内联小表）

**Markdown：** 读取 `templates/` 下模板，填充数据，组装完整报告。机会看板置顶。
**HTML：** 读取 `templates/dashboard.html`，替换所有 `{{placeholder}}`。机会卡片按扩散度颜色编码（red/yellow/green/gray）。图表数据嵌入为 JS 数组。

---

## Phase 6: 输出

| 输出 | 路径 | 说明 |
|------|------|------|
| Markdown | `reports/YYYY-MM-DD_{session}.md` | 文本报告 |
| HTML | `reports/YYYY-MM-DD_{session}.html` | 可视化报告 |
| JSON 快照 | `data/latest.json` | 结构化数据（历史归档由 `run-report.sh` 在运行前自动完成，无需处理） |
| 告警摘要 | `reports/latest-alert.txt` | 单行摘要 |

**执行顺序（由定时任务提示词驱动）：** 先运行 `scripts/pre-run.sh`（日志轮转 + 上期快照归档与备份）→ 执行 Phase 0-6 生成文件 → 验证 HTML + MD 存在且非空 → 成功后运行 `scripts/telegram-push.sh <日期> daily` 完成 git push 和 Telegram 推送。Phase 6 本身只负责生成文件；若任一 Phase 失败导致报告未产出，用 `data/latest.json.bak` 恢复 `data/latest.json`，避免半成品快照污染下一期对比。

**`data/latest.json` 结构：**
```json
{
  "timestamp": "ISO 8601",
  "session": "daily",
  "market_scan": {
    "movers": [{"coin_id","symbol","price_usd","price_change_24h","price_change_7d","price_change_30d","market_cap","volume_24h","reason","narrative_tag","source_url"}],
    "movers_narrative": "本期异动的定性综述",
    "sector_rotation": [{"category","market_cap","market_cap_change_24h","trend_sessions","note"}],
    "trending": [{"coin_id","symbol","name"}],
    "chains_tvl_delta": [{"chain","tvl","tvl_change_pct_vs_prev"}]
  },
  "opportunities": [{"id","coin","title","thesis","diffusion":"red|yellow|green",
    "score":{"catalyst_strength","time_window","crowding","risk","total"},
    "status":"new|tracking|triggered|expired|stale",
    "first_seen","last_updated","sessions_tracked","sessions_since_progress","source_url"}],
  "events": [{"id","coin","event_type":"unlock|upgrade|etf_decision|listing|macro",
    "date","days_away","description","opportunity_angle","source_url","status":"upcoming|passed"}],
  "market_context": {
    "btc": {"price_usd","price_change_24h","price_change_7d","fear_greed","fear_greed_label","mvrv_ratio","funding_rate","open_interest","dominance","sparkline_7d","support","resistance","trend"},
    "macro": {"fomc_date","fomc_days_away","note"},
    "etf_qualitative": {"btc_etf_flow_text","eth_etf_flow_text"},
    "global": {"total_market_cap_usd","stablecoin_total_supply"}
  },
  "market_score": {"btc_trend","funding","sentiment","macro","total","label","vs_previous"},
  "watchlist": {"<coin_id>": {"price_usd","price_change_24h","price_change_7d","market_cap","note"}},
  "alerts": [{"severity","rule","message"}],
  "_sources": {"field": "source_type|null"},
  "_freshness": {"field": {"value","unchanged_since","sessions_unchanged"}}
}
```

---

## 数据真实性（硬规则，不可违反）

1. **数值型字段必须且只能来自 API JSON 返回值或页面原文中可直接提取的数字。** 禁止从 WebSearch 摘要中推断、估算、外推或编造任何数值。
2. **WebSearch 仅可用于定性信息**（涨跌原因、事件背景、扩散度判断）。不可用于填充 `data/latest.json` 中的数值字段。即使 WebSearch 返回看似精确的数字（如"ETF 净流入 $358M"），也只可在报告正文定性引用。
3. **数据缺失时：** JSON 写 `null`，报告写「数据暂缺」，图表用 `[]` 显示占位提示。
4. **sparkline 数据必须来自 CoinGecko 返回的原值**（`market_data.sparkline_7d.price`）。失败则填 `[]`。
5. **上期/本期有 `null` 的字段跳过 delta 计算。**
6. **`_sources` 为必填字段**，记录每个关键指标的数据来源。禁止 `websearch` 作为数值字段来源。
7. **机会看板没发现新机会 = 写「本期无新机会」。** 绝不编造或拔高旧信息。事件没有明确日期 = 不进事件日历。
8. **防膨胀（见 4.7）：** 无进展 ≥5 期的条目降 `stale`；持续跟踪节最多 10 条；stale + 溢出条目折叠为一行汇总，禁止逐条重复打印。

---

## 错误处理

| 场景 | 处理 |
|------|------|
| 网页抓取失败 | WebSearch 补充定性信息；数值字段标 `null` / 「数据暂缺」 |
| CoinGecko 429 限速 | 等待 60s 重试一次；仍失败则该数据源本期标 `null` |
| WebSearch 无结果 | 标记「数据暂缺」/「原因未明」 |
| config 损坏 | 停止，写 `reports/YYYY-MM-DD_error.md` |
| 历史数据缺失 | 跳过对比、轮动趋势和新鲜度校验（本期记录基线） |
| 推送失败 | 记录错误，不影响报告 |

---

## 调度

由 Kimi Work 定时任务驱动（cron `0 4 * * *`，Asia/Shanghai，模型 k3-agent，local_conversation 模式，工作区为本项目目录）。每次运行按顺序执行：
1. `scripts/pre-run.sh`：日志轮转（7 天清理）+ 上期快照归档到 `data/history/`（30 天清理）+ 备份 `data/latest.json` 为 `.bak`
2. 执行本手册 Phase 0-6
3. 验证产出文件（HTML + MD 存在且非空）；失败则用 `.bak` 恢复 `data/latest.json`
4. 成功 → `scripts/telegram-push.sh` 推送 GitHub Pages + Telegram

运行记录与失败状态在 Kimi Work 定时任务面板可查，并配有桌面通知。

- 日报：04:00 UTC+8（每天一次，一天 = 一期）
- 历史：2026-09-28 前由 macOS launchd + `claude -p` 驱动；Claude 账号停用后迁移至 Kimi 定时任务
