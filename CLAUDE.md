# 加密货币 Alpha 情报监控系统

自动化加密货币 alpha 发现引擎，每天 08:00 / 20:00 (UTC+8) 执行。

**核心原则：** Alpha 优先 | 持仓深度 > 市场概览 | 禁止编造数据 | API 优先 | 一手信源 > 媒体报道

---

## Phase 0: 初始化

读取 `config/coins.json`（币种 + alpha_sources）、`config/alerts.json`（告警）、`config/output.json`（输出格式）。
读取 `data/latest.json`（上期数据，用于对比和新鲜度校验）。不存在则跳过对比。
确定日期、时段（morning/evening）、当月英文名。

---

## Phase 1: API 数据采集

**优先用免费 API（WebFetch JSON 端点）：**

| 来源 | 端点 | 数据 |
|------|------|------|
| CoinGecko | `/api/v3/simple/price?ids={所有币}&vs_currencies=usd&include_24hr_change=true&include_7d_change=true&include_market_cap=true` | 全币种价格/变化/市值 |
| CoinGecko | `/api/v3/coins/bitcoin?sparkline=true&developer_data=true` | BTC sparkline(168点) |
| CoinGecko | `/api/v3/derivatives?include_tickers=unexpired` | 资金费率 + 未平仓合约（从返回数组中筛选 BTC/USDT，取 Binance 的 `funding_rate` 和 `open_interest`） |
| CoinMetrics | `community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur&frequency=1d&page_size=1` | MVRV 比率（`CapMVRVCur` 字段） |
| DeFiLlama | `/v2/chains` | 全链 TVL |
| DeFiLlama | `/overview/fees` | 协议费用/收入 |
| DeFiLlama | `/summary/fees/{protocol}?dataType=dailyRevenue` | LINK/ETH 收入明细 |
| DeFiLlama | `stablecoins.llama.fi/stablecoinchains` | 各链稳定币供应 |
| Alternative.me | `/fng/` | Fear & Greed Index |

> **已废弃端点（不再使用）：**
> - ~~CoinGlass `open-api.coinglass.com/public/v2/funding`~~ — 2026-04 起需 API key
> - ~~CoinGlass `open-api.coinglass.com/public/v2/open_interest`~~ — 同上
> - 若未来获取 CoinGlass API key，可恢复使用新端点 `open-api.coinglass.com/api/bitcoin/etf/flow-history`（ETF 流向）

**WebFetch 页面抓取（按优先级尝试）：**

| 数据 | 主源 | 备用源 | 状态 |
|------|------|--------|------|
| 代币解锁 | `token.unlocks.app/` | — | 可用 |

> **已废弃页面源（持续失败，不再尝试）：**
> - ~~farside.co.uk/btc/~~ — Cloudflare 403（2026-04 起）
> - ~~sosovalue.com/assets/etf/us-btc-spot~~ — 403
> - ~~coinglass.com/pro/i/mvrv~~ — JS SPA 渲染，WebFetch 无法提取
> - ~~cryptoquant.com 交易所储备~~ — 页面抓取失败

**无免费 API 的字段（直接写 `null`）：**
- ETF 日度流向 — 无 key 时写 `null`，报告中可用 WebSearch 做定性描述（如"ETF 连续正流入"），但 JSON 不填数字
- 交易所储备 — 写 `null`
- 鲸鱼月度累积 — 写 `null`
- SOPR (7d) — 写 `null`

**降级链路：**
1. 免费 API JSON → 取返回值
2. 页面抓取（主源 → 备用源）→ 从 HTML 原文提取数字
3. 都失败 → 字段写 `null`，报告写「数据暂缺」
4. **禁止**：从 WebSearch 结果中提取数值填入 JSON
5. **WebSearch 来源的数值一律写 `null`**。即使 WebSearch 返回了看似精确的数字（如"ETF 净流入 $358M"），也不得填入 JSON 数值字段。仅可在报告正文中做定性引用。

---

## Phase 2: Alpha 信源扫描（核心阶段）

按 `coins.json` 中每个持仓币种的 `alpha_sources` 定义，逐个扫描一手信源。
目标：发现市场尚未广泛关注的催化剂和进展。

**LINK（P0，8-10 次调用）：**
1. WebFetch `blog.chain.link` → 检查最近 48h 新文章
2. WebFetch GitHub `smartcontractkit` → 最近 commits/releases
3. WebFetch Etherscan → Reserve 合约最近交易
4. WebSearch "Chainlink CCIP" + 今日日期 → 新 lane/集成
5. WebSearch 每个合作方名 + "Chainlink" → 合作方侧公告
6. WebFetch Grayscale GLNK 持仓页 → 本周流入/流出
7. WebSearch "Chainlink governance proposal" → 治理动态
8. WebSearch "LINK" + 今日日期 → 兜底扫描

**ETH（P0，6-8 次调用）：**
1. WebFetch `blog.ethereum.org` → 最新文章
2. WebFetch GitHub `ethereum/pm` → AllCoreDevs 会议纪要
3. WebSearch "Glamsterdam upgrade" / "ePBS" + latest → 升级进度
4. WebSearch "Ethereum" + staking/L2/blob + 今日日期
5-6. 定向合作方/生态搜索（BlackRock ETHB、Lido 等）

**Monad（P1，6-8 次调用）：**
1. WebFetch `monad.xyz` blog → 最新文章
2. WebSearch "Monad" + ecosystem/partnership + 今日日期
3-6. DApp 部署、TVL 变化、合作公告、NYSE/Securitize 进展

**搜索词规则：** 含当天日期 | 不硬编码年份 | 路线图类用 `"latest"` | 解锁类用 `"next"`

---

## Phase 3: BTC 市场环境 + 观察仓简搜

**BTC（context，3-4 次调用）：**
1. WebSearch BTC + ETF flows + 今日日期（仅定性：流入/流出趋势、重大事件）
2. WebSearch BTC + whale/on-chain + 今日日期（仅定性：趋势描述，不填数值）
3. WebSearch BTC + FOMC/macro + 今日日期

> 资金费率和 OI 已由 Phase 1 的 CoinGecko derivatives API 覆盖，无需再 WebSearch。

**观察仓（P2，每个 2-3 条）：**
- SOL: Firedancer 进展 + 生态大事件
- ARB: 解锁进度 + 费用分享提案
- PLUME: RWA 合作 + TVL 变化

WebSearch 仅用于定性信息（新闻/事件/合作）。数值必须来自 Phase 1 的 API 数据。

---

## Phase 4: 分析

### 4.1 Alpha 信号评级
对 Phase 2 发现的每条新信息：
- 搜索 Google News 检查是否已被报道
- 无报道 → 🔴首发 | 仅专业媒体 → 🟡早期 | 主流媒体已发 → 🟢已扩散
- 写入 `alpha_signals` 数组

### 4.2 新鲜度校验
读取上期 `data/latest.json`，对所有数值型指标逐字段比对：
- BTC: `mvrv_ratio`, `funding_rate`, `open_interest`, `fear_greed`
- LINK: `revenue_30d`, `revenue_7d`, `ccip_monthly_volume`, `reserve_accumulated_link`, `etf_glnk_aum`
- ETH: `tvl`, `daily_revenue`, `stablecoin_supply`
- MON: `tvl`, `daily_fee_revenue`, `stablecoin_supply`
- 连续 ≥3 session 值不变 → 写入 `_freshness`，报告中标注「⚠️ 数据已 N 期未更新」
- **绝不**静默复读上期数据当新数据用
- 已标记为 `null`（无 API 源）的字段不参与新鲜度校验

### 4.3 催化剂状态更新
对比上期 `holdings.{coin}.catalysts` 状态：
- Phase 2 发现进展 → 更新 `status` 和 `detail`
- 无新信息 → 保持上期状态不变（不编造进展）

### 4.4 告警评估
逐条评估 `config/alerts.json` 中的规则，按 severity 排序。

### 4.5 市场阶段评估（4维 × 1-5分 = /20）
- BTC 趋势 | 资金面（ETF+储备）| 情绪面（FGI+费率）| 宏观面
- 16-20 强牛 | 12-15 偏多 | 8-11 中性 | 4-7 偏空 | 1-3 强熊

### 4.6 操作建议
- 每个持仓币种：建议（动/不动/条件触发）+ 理由 + 时间框架
- 基于 Alpha 信号 + 催化剂状态 + 市场环境综合判断

---

## Phase 5: 报告生成

**报告结构（~200 行，Alpha 优先）：**
1. Alpha 信号板 → `templates/alpha-signals.md`
2. 持仓追踪（LINK → ETH → Monad）→ `templates/coin-holding.md`（P0/P1 模式）
3. 操作建议（基于 1+2 的结论）
4. 市场环境（BTC 精简）→ `templates/market-overview.md`
5. 观察仓（SOL/ARB/PLUME 各一行）→ `templates/coin-holding.md`（P2 模式）

**Markdown：** 读取 `templates/` 下模板，填充数据，组装为完整报告。Alpha 信号板置顶。

**HTML：** 读取 `templates/dashboard.html`，替换所有 `{{placeholder}}`。Alpha 信号卡片用颜色编码（red/yellow/green/gray）。图表数据嵌入为 JS 数组。

---

## Phase 6: 输出

| 输出 | 路径 | 说明 |
|------|------|------|
| Markdown | `reports/YYYY-MM-DD_{session}.md` | 文本报告 |
| HTML | `reports/YYYY-MM-DD_{session}.html` | 可视化报告 |
| JSON 快照 | `data/latest.json` | 结构化数据（旧的归档到 `data/history/`）|
| 告警摘要 | `reports/latest-alert.txt` | 单行摘要 |

**注意：不要在 Phase 6 中调用 `telegram-push.sh`。** Telegram 推送和 git push 由外部 `scripts/run-report.sh` 统一负责，Claude 进程只负责生成文件。

**`data/latest.json` 结构：**
```json
{
  "timestamp": "ISO 8601",
  "session": "morning|evening",
  "alpha_signals": [{"coin","level","title","detail","source_type","source_url"}],
  "holdings": {"link": {"...catalysts": []}, "eth": {}, "monad": {}},
  "market_context": {"btc": {}, "macro": {}},
  "watchlist": {"sol": {}, "arb": {}, "plume": {}},
  "market_score": {"btc_trend","funding","sentiment","macro","total"},
  "_sources": {"field": "source_type|null"},
  "_freshness": {"field": {"value","unchanged_since","sessions_unchanged"}}
}
```

历史清理：`find data/history/ -name "*.json" -mtime +30 -delete`

---

## 数据真实性（硬规则，不可违反）

1. **数值型字段必须且只能来自 API JSON 返回值或页面原文中可直接提取的数字。** 禁止从 WebSearch 摘要中推断、估算、外推或编造任何数值。
2. **WebSearch 仅可用于定性信息。** 不可用于填充 `data/latest.json` 中的数值字段。
3. **数据缺失时：** JSON 写 `null`，报告写「数据暂缺」，图表用 `[]` 显示占位提示。
4. **sparkline 数据必须来自 CoinGecko `/coins/bitcoin?sparkline=true` 返回的原值。** 失败则填 `[]`。
5. **ETF 流向数据**：若有 CoinGlass API key 则用 `open-api.coinglass.com/api/bitcoin/etf/flow-history`；无 key 则写 `null`。farside.co.uk 和 sosovalue.com 已废弃（持续 403）。
6. **上期/本期有 `null` 的字段跳过 delta 计算。**
7. **`_sources` 为必填字段**，记录每个关键指标的数据来源。禁止 `websearch` 作为数值字段来源。
8. **Alpha 信号板没发现新信号 = 写「无新信号」。** 绝不编造或拔高旧信息。

---

## 错误处理

| 场景 | 处理 |
|------|------|
| WebFetch 失败 | WebSearch 补充定性信息；数值字段标 `null` / 「数据暂缺」 |
| WebSearch 无结果 | 标记「数据暂缺」|
| config 损坏 | 停止，写 `reports/YYYY-MM-DD_error.md` |
| 历史数据缺失 | 跳过对比和新鲜度校验 |
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
