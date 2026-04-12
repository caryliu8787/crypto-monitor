# Alpha-First Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure crypto-monitor around alpha discovery, aligning report depth with actual portfolio (LINK > ETH > Monad), and eliminating data fabrication/staleness.

**Architecture:** Config-driven system where Claude reads CLAUDE.md instructions + config JSON + Markdown/HTML templates to generate reports. Changes span config, templates, and instruction doc. No application code to test — validation is by inspection of generated output.

**Tech Stack:** JSON config, Markdown templates, HTML/CSS/Chart.js dashboard, shell scripts (already modified in prior P0-P3 fixes)

---

### Task 1: Delete dead templates

**Files:**
- Delete: `templates/coin-standard.md`
- Delete: `templates/coin-deep-track.md`
- Delete: `templates/coin-watchlist.md`
- Delete: `templates/historical-comparison.md`

- [ ] **Step 1: Delete the four files**

```bash
cd /Users/caryliu/projects/crypto-monitor
git rm templates/coin-standard.md templates/coin-deep-track.md templates/coin-watchlist.md templates/historical-comparison.md
```

- [ ] **Step 2: Verify only intended templates remain**

```bash
ls templates/
```

Expected: `alpha-signals.md` does NOT exist yet. Only `market-overview.md` and `dashboard.html` remain.

- [ ] **Step 3: Commit**

```bash
git add -A templates/
git commit -m "chore: delete replaced coin templates and dead historical-comparison"
```

---

### Task 2: Rewrite coins.json

**Files:**
- Modify: `config/coins.json`

Priority realignment (LINK P0, Monad P1, BTC context), replace `custom_searches` with `alpha_sources`, remove unused fields (`l2beat_tracked`, redundant `metrics.catalysts`), add ETH/Monad `alpha_sources`.

- [ ] **Step 1: Replace coins.json with new content**

Write the complete new `config/coins.json`:

```json
{
  "coins": [
    {
      "id": "btc",
      "name": "Bitcoin",
      "ticker": "BTC",
      "priority": "context",
      "enabled": true,
      "role": "市场环境锚",
      "role_detail": "不持仓，作为市场环境背景判断山寨走势",
      "template": "market-overview",
      "search_focus": ["etf_flows", "whale_activity", "on_chain", "derivatives", "macro"],
      "search_volume": "4-5",
      "data_sources": {
        "coingecko_id": "bitcoin",
        "webfetch_urls": {
          "etf_flows": "https://farside.co.uk/btc/",
          "etf_flows_backup": "https://sosovalue.com/assets/etf/us-btc-spot",
          "fear_greed": "https://alternative.me/crypto/fear-and-greed-index/"
        },
        "api_endpoints": {
          "funding_rate": "https://open-api.coinglass.com/public/v2/funding",
          "open_interest": "https://open-api.coinglass.com/public/v2/open_interest",
          "long_short": "https://open-api.coinglass.com/public/v2/long_short"
        },
        "page_scraping": {
          "mvrv": "https://www.coinglass.com/pro/i/mvrv",
          "exchange_reserves": "https://cryptoquant.com/asset/btc/chart/exchange-flows/exchange-reserve"
        }
      },
      "notes": "BTC 搜索量压缩至 4-5 条，仅采集市场环境数据"
    },
    {
      "id": "link",
      "name": "Chainlink",
      "ticker": "LINK",
      "priority": "P0",
      "enabled": true,
      "role": "第一仓位",
      "role_detail": "Oracle 基础设施 + CCIP 跨链 + 质押收益，Reserve 累积是独特买压",
      "template": "coin-holding",
      "search_focus": ["partnerships", "ccip_volume", "staking_tvl", "reserve_accumulation", "etf_flows", "governance"],
      "search_volume": "8-10",
      "data_sources": {
        "defillama_slug": "chainlink",
        "coingecko_id": "chainlink"
      },
      "alpha_sources": {
        "github": "https://github.com/smartcontractkit",
        "blog": "https://blog.chain.link",
        "ccip_contracts": "搜索 Etherscan 近 24h 新部署的 CCIP 相关合约",
        "reserve_contract": "搜索 Chainlink Reserve 合约最近买入事件",
        "partnerships": ["Aave", "Coinbase", "Swift", "DTCC", "JPMorgan", "Mastercard", "Lido", "GMX"],
        "etf_tracking": ["GLNK Grayscale", "CLNK Bitwise"],
        "governance": "Chainlink community forum + Snapshot"
      },
      "notes": "第一仓位，获得最大搜索量。一手信源全扫：GitHub、链上合约、官方 blog、治理提案、合作方公告"
    },
    {
      "id": "eth",
      "name": "Ethereum",
      "ticker": "ETH",
      "priority": "P0",
      "enabled": true,
      "role": "第二仓位",
      "role_detail": "DeFi/L2 基础设施，Glamsterdam 升级是核心催化剂",
      "template": "coin-holding",
      "search_focus": ["upgrade_progress", "l2_data", "staking_rate", "eth_btc_ratio", "ecosystem"],
      "search_volume": "6-8",
      "data_sources": {
        "defillama_slug": "ethereum",
        "coingecko_id": "ethereum"
      },
      "alpha_sources": {
        "github": "https://github.com/ethereum/pm",
        "blog": "https://blog.ethereum.org",
        "allcoredevs": "AllCoreDevs 会议纪要（GitHub ethereum/pm）",
        "eip_tracker": "EIP 状态变更（Glamsterdam 相关 EIP-7732/EIP-7928）",
        "partnerships": ["BlackRock", "Lido", "Coinbase", "Uniswap"]
      },
      "notes": "第二仓位。重点跟踪 Glamsterdam 升级进度和 ETH/BTC 比率"
    },
    {
      "id": "monad",
      "name": "Monad",
      "ticker": "MON",
      "priority": "P1",
      "enabled": true,
      "role": "第三仓位",
      "role_detail": "高性能 EVM L1，关注生态建设和解锁风险",
      "template": "coin-holding",
      "search_focus": ["ecosystem_growth", "tvl", "partnerships", "unlock_schedule"],
      "search_volume": "6-8",
      "data_sources": {
        "defillama_slug": "monad",
        "coingecko_id": "monad"
      },
      "alpha_sources": {
        "blog": "https://monad.xyz/blog",
        "partnerships": ["NYSE", "Securitize", "Uniswap", "Curve"],
        "ecosystem": "新 DApp 部署、TVL 变化、开发者活动"
      },
      "notes": "第三仓位。关注生态有机需求 vs 激励驱动（日费用是关键指标），11 月解锁悬崖"
    },
    {
      "id": "sol",
      "name": "Solana",
      "ticker": "SOL",
      "priority": "P2",
      "enabled": true,
      "role": "观察仓",
      "role_detail": "高性能 L1 标杆，观察 Firedancer 和生态活跃度",
      "template": "coin-holding",
      "search_volume": "2-3",
      "data_sources": {
        "defillama_slug": "solana",
        "coingecko_id": "solana"
      },
      "notes": "观察仓，报告中仅一行摘要"
    },
    {
      "id": "arb",
      "name": "Arbitrum",
      "ticker": "ARB",
      "priority": "P2",
      "enabled": true,
      "role": "观察仓",
      "role_detail": "以太坊最大 L2，观察费用分享提案和解锁",
      "template": "coin-holding",
      "search_volume": "2-3",
      "data_sources": {
        "defillama_slug": "arbitrum",
        "coingecko_id": "arbitrum",
        "webfetch_urls": {
          "unlocks": "https://token.unlocks.app/arbitrum"
        }
      },
      "notes": "观察仓，报告中仅一行摘要。注意解锁日期"
    },
    {
      "id": "plume",
      "name": "Plume Network",
      "ticker": "PLUME",
      "priority": "P2",
      "enabled": true,
      "role": "观察仓",
      "role_detail": "RWA 专注链，观察真实世界资产代币化进展",
      "template": "coin-holding",
      "search_volume": "2-3",
      "data_sources": {
        "defillama_slug": "plume",
        "coingecko_id": "plume-network"
      },
      "notes": "观察仓，报告中仅一行摘要"
    }
  ]
}
```

- [ ] **Step 2: Validate JSON syntax**

```bash
python3 -c "import json; json.load(open('config/coins.json')); print('Valid JSON')"
```

Expected: `Valid JSON`

- [ ] **Step 3: Commit**

```bash
git add config/coins.json
git commit -m "config: realign priorities (LINK P0, Monad P1, BTC context), add alpha_sources"
```

---

### Task 3: Update alerts.json

**Files:**
- Modify: `config/alerts.json`

Adjust `coins` arrays in price_alerts and ecosystem_alerts to reflect new priorities. Holdings coins (link, eth, monad) get critical/warning alerts. Watchlist coins (sol, arb, plume) only get info-level. Remove `altseason_index` reference from cross_coin_alerts since the field is being deleted.

- [ ] **Step 1: Update price_alerts coins arrays**

In `config/alerts.json`, change the `p0_p1_major_drop` alert's coins from `["btc", "eth", "sol", "link"]` to `["link", "eth", "monad", "btc"]`.

Change `p0_p1_major_pump` coins the same way.

Change `altcoin_divergence` coins from `["eth", "sol", "link", "arb", "monad"]` to `["link", "eth", "monad"]`.

Change `report_delta_large` coins from `["btc", "eth", "sol", "link", "arb", "monad"]` to `["link", "eth", "monad", "btc"]`.

- [ ] **Step 2: Update ecosystem_alerts**

Change `large_unlock_imminent` coins from `["link", "arb", "monad", "plume"]` to `["monad", "arb"]` (LINK ETF is live so unlock is less relevant; Plume is minimal observation).

Change `tvl_weekly_drop` coins from `["eth", "sol", "arb", "monad", "plume"]` to `["eth", "monad"]`.

- [ ] **Step 3: Remove altseason_index from cross_coin_alerts**

Delete the `altseason_signal` alert object entirely (references deleted `altseason_index` field).

- [ ] **Step 4: Validate JSON**

```bash
python3 -c "import json; json.load(open('config/alerts.json')); print('Valid JSON')"
```

- [ ] **Step 5: Commit**

```bash
git add config/alerts.json
git commit -m "config: align alerts with new portfolio priorities, remove altseason reference"
```

---

### Task 4: Create alpha-signals.md template

**Files:**
- Create: `templates/alpha-signals.md`

- [ ] **Step 1: Write the template**

```markdown
## Alpha 信号板

> 以下信号来自一手信源扫描（GitHub、链上合约、官方 blog、治理论坛、合作方公告）。
> 评级规则：🔴 首发（主流媒体未报道）| 🟡 早期（仅专业社区讨论）| 🟢 已扩散（主流媒体已覆盖）

{{#if has_red_signals}}
### 🔴 首发信号
{{red_signals}}
{{/if}}

{{#if has_yellow_signals}}
### 🟡 早期信号
{{yellow_signals}}
{{/if}}

{{#if has_green_signals}}
### 🟢 已扩散
{{green_signals}}
{{/if}}

### 今日无新信号的持仓
{{no_signal_coins}}

> 每条信号格式：**[币种] 标题** — 详情（来源: URL）
> 没有发现新信号 = 如实写「无新信号」。绝不编造或拔高旧信息。
> 上期已收录且无进展更新的信息不重复出现。
```

- [ ] **Step 2: Commit**

```bash
git add templates/alpha-signals.md
git commit -m "templates: create alpha signal board template"
```

---

### Task 5: Create coin-holding.md template

**Files:**
- Create: `templates/coin-holding.md`

Single parameterized template. Detail level controlled by priority field from coins.json.

- [ ] **Step 1: Write the template**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add templates/coin-holding.md
git commit -m "templates: create parameterized coin-holding template (P0/P1/P2 modes)"
```

---

### Task 6: Rewrite market-overview.md

**Files:**
- Modify: `templates/market-overview.md`

Compress from 60 lines to ~35. Remove: altseason_index row, cross-chain DEX table, ATH row. Compress macro calendar to 3-day window. Add freshness annotations to on-chain indicators.

- [ ] **Step 1: Replace market-overview.md content**

```markdown
## 市场环境

### BTC 核心指标
| 指标 | 当前值 | 24h 变化 | 信号 |
|------|--------|----------|------|
| 价格 | {{btc_price}} | {{btc_24h_change}} | {{price_signal}} |
| 恐惧贪婪指数 | {{fear_greed_index}} | 上期: {{fear_greed_prev}} | {{fear_greed_label}} |
| BTC 主导率 | {{btc_dominance}} | {{dominance_change}} | {{dominance_signal}} |

### ETF 资金流向
| 指标 | 数值 | 趋势 |
|------|------|------|
| 今日净流入 | {{etf_daily_flow}} | {{etf_daily_trend}} |
| 本周净流入 | {{etf_weekly_flow}} | {{etf_weekly_trend}} |

### BTC 链上指标
| 指标 | 数值 | 信号 | 新鲜度 |
|------|------|------|--------|
| MVRV Z-Score | {{mvrv_zscore}} | {{mvrv_signal}} | {{mvrv_freshness}} |
| SOPR (7d) | {{sopr_7d}} | {{sopr_signal}} | {{sopr_freshness}} |
| 交易所储备 | {{exchange_reserves}} | {{reserves_signal}} | {{reserves_freshness}} |
| 鲸鱼月度累积 | {{whale_accumulation}} | {{whale_signal}} | {{whale_freshness}} |
| 资金费率 | {{funding_rate}} | {{funding_signal}} | {{funding_freshness}} |
| 未平仓合约 | {{open_interest}} | {{oi_signal}} | -- |

> 新鲜度标注规则：连续 ≥3 session 数值不变 → 显示「⚠️ N 期未更新」。
> 链上指标数值必须来自 API 或页面原文。无法获取 → 写「数据暂缺」。

### 技术面
- 支撑: {{btc_key_support}} | 阻力: {{btc_key_resistance}} | 趋势: {{btc_trend_direction}}

### 宏观日历（3 天内 + 重大事件）
| 日期 | 事件 | 预期���响 |
|------|------|----------|
{{macro_events_rows}}

### 市场评分 {{market_score_total}}/20 — {{market_phase}}
| BTC 趋势 | 资金面 | 情绪面 | 宏观面 |
|----------|--------|--------|--------|
| {{score_btc_trend}}/5 | {{score_funding}}/5 | {{score_sentiment}}/5 | {{score_macro}}/5 |
```

- [ ] **Step 2: Commit**

```bash
git add templates/market-overview.md
git commit -m "templates: compress market-overview to compact context section with freshness"
```

---

### Task 7: Rewrite dashboard.html

**Files:**
- Modify: `templates/dashboard.html`

New section order: Alpha Signal Board -> Holdings (LINK/ETH/Monad) -> Action Recommendations -> Market Context (compact BTC) -> Watchlist footer. Delete Developer Activity chart and History FGI+Score chart. Add alpha signal card styles.

- [ ] **Step 1: Replace the HTML body content (between `<body>` and `</body>`) with new structure**

Keep the existing `<head>` CSS variables, reset, and base styles. Add new CSS for alpha signal cards. Replace the body sections in this order:

1. Header (keep, change subtitle)
2. NEW: Alpha Signal Board section with colored signal cards
3. NEW: Holdings section (LINK / ETH / Monad panels using `{{coin_sections_html}}`)
4. NEW: Action Recommendations section (`{{recommendations_html}}` + `{{action_items_html}}`)
5. Market Context section (compressed BTC table, sparkline, ETF chart, on-chain table, score bars)
6. NEW: Watchlist footer (single table row for SOL/ARB/PLUME)
7. Footer

Remove these sections entirely:
- "二、跨链生态对比" (TVL chart, stablecoin table, protocol revenue, developer activity chart)
- "四、历史趋势对比" (heatmap, FGI+Score history chart, consecutive signals)

Remove these chart JS blocks:
- Developer Activity Bar (`chartDev`)
- History Dual-Axis Line (`chartHistory`)

Add new CSS classes:

```css
/* ===== Alpha Signal Cards ===== */
.alpha-card {
  border-left: 3px solid var(--border);
  padding: 10px 14px;
  margin-bottom: 8px;
  background: var(--bg-card);
  border-radius: 0 var(--radius) var(--radius) 0;
  font-size: 13px;
}
.alpha-card.red    { border-left-color: #f85149; }
.alpha-card.yellow { border-left-color: #e3b341; }
.alpha-card.green  { border-left-color: #3fb950; }
.alpha-card.gray   { border-left-color: var(--text-muted); }
.alpha-card .coin-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  margin-right: 6px;
}
.alpha-card.red .coin-tag    { background: rgba(248,81,73,.15); color: #f85149; }
.alpha-card.yellow .coin-tag { background: rgba(227,179,65,.15); color: #e3b341; }
.alpha-card.green .coin-tag  { background: rgba(63,185,80,.15); color: #3fb950; }
.alpha-card.gray .coin-tag   { background: rgba(72,79,88,.2); color: var(--text-muted); }
.alpha-card .source { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

/* ===== Holdings Panels ===== */
.holding-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
}
.holding-panel h3 { margin-top: 0; }

/* ===== Watchlist Row ===== */
.watchlist-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.watchlist-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 13px;
}
.watchlist-item .ticker { font-weight: 700; color: var(--accent); }

/* ===== Freshness Warning ===== */
.freshness-warn { color: var(--orange); font-size: 11px; }
```

Replace body sections with:

```html
<div class="container">

  <!-- HEADER -->
  <div class="report-header">
    <h1>加密货币 Alpha 情报</h1>
    <div class="meta">{{report_date}} | {{report_session}} | {{report_timestamp}}</div>
  </div>

  <!-- SECTION 1: ALPHA SIGNAL BOARD -->
  <h2>一、Alpha 信号板</h2>
  {{alpha_signals_html}}

  <hr class="section-divider">

  <!-- SECTION 2: HOLDINGS TRACKER -->
  <h2>二、持仓追踪</h2>
  {{coin_sections_html}}

  <hr class="section-divider">

  <!-- SECTION 3: ACTION RECOMMENDATIONS -->
  <h2>三、操作建议</h2>
  <h3>市场阶段评估</h3>
  <div class="card">
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px;flex-wrap:wrap;">
      <span style="font-size:13px;color:var(--text-secondary);">综合评分</span>
      <span style="font-size:22px;font-weight:700;">{{market_score_total}}<span style="font-size:14px;color:var(--text-secondary);">/20</span></span>
      <span style="font-size:14px;font-weight:600;">{{market_phase}}</span>
    </div>
    <div class="score-row">
      <span class="label">BTC 趋势</span>
      <div class="score-track"><div class="score-fill" id="bar-btc-trend"></div></div>
      <span class="val">{{score_btc_trend}}</span>
    </div>
    <div class="score-row">
      <span class="label">资金面</span>
      <div class="score-track"><div class="score-fill" id="bar-funding"></div></div>
      <span class="val">{{score_funding}}</span>
    </div>
    <div class="score-row">
      <span class="label">市场情绪</span>
      <div class="score-track"><div class="score-fill" id="bar-sentiment"></div></div>
      <span class="val">{{score_sentiment}}</span>
    </div>
    <div class="score-row">
      <span class="label">宏观环境</span>
      <div class="score-track"><div class="score-fill" id="bar-macro"></div></div>
      <span class="val">{{score_macro}}</span>
    </div>
  </div>

  <h3>各持仓建议</h3>
  {{recommendations_html}}

  <h3>行动清单</h3>
  <div class="card">
    {{action_items_html}}
  </div>

  <hr class="section-divider">

  <!-- SECTION 4: MARKET CONTEXT -->
  <h2>四、市场环境</h2>

  <h3>BTC 核心指标</h3>
  <div class="card">
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>指标</th><th>当前值</th><th>24h 变化</th><th>信号</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>价格</td>
            <td><strong>{{btc_price}}</strong></td>
            <td>{{btc_24h_change}}</td>
            <td>{{btc_price_signal}}</td>
          </tr>
          <tr>
            <td>恐惧贪婪</td>
            <td><strong>{{fgi_value}}</strong></td>
            <td>{{fgi_label}}</td>
            <td>{{fgi_signal}}</td>
          </tr>
          <tr>
            <td>BTC 主导率</td>
            <td><strong>{{btc_dominance}}%</strong></td>
            <td>{{btc_dominance_change}}</td>
            <td>{{btc_dominance_signal}}</td>
          </tr>
          <tr>
            <td>ETF 周净流入</td>
            <td><strong>{{etf_weekly_net}}</strong></td>
            <td>--</td>
            <td>{{etf_signal}}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div style="margin-top:10px;">
      <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:3px;">
        <span>Extreme Fear</span><span>Fear</span><span>Neutral</span><span>Greed</span><span>Extreme Greed</span>
      </div>
      <div class="progress-track">
        <div class="progress-fgi" style="width:{{fgi_value}}%"></div>
      </div>
    </div>
  </div>

  <h3>BTC 7 日价格走势</h3>
  <div class="card">
    <div class="chart-inline">
      <canvas id="chartSparkline"></canvas>
      <div id="noDataSparkline" class="no-data" style="display:none;">数据暂缺 — CoinGecko sparkline API 未返回有效数据</div>
    </div>
  </div>

  <h3>ETF 资金流向</h3>
  <div class="card">
    <div class="chart-small">
      <canvas id="chartETF"></canvas>
      <div id="noDataETF" class="no-data" style="display:none;">数据暂缺 — ETF 流向数据未获取</div>
    </div>
    <div class="etf-text-summary">{{etf_flow_text}}</div>
  </div>

  <h3>BTC 链上指标</h3>
  <div class="card">
    <div class="table-wrap">
      {{onchain_table_html}}
    </div>
  </div>

  <h3>技术面</h3>
  <div class="card">
    <table class="data-table compact">
      <tbody>
        <tr><td style="width:80px;font-weight:600;">支撑</td><td>{{btc_support_text}}</td></tr>
        <tr><td style="font-weight:600;">阻力</td><td>{{btc_resistance_text}}</td></tr>
        <tr><td style="font-weight:600;">趋势</td><td>{{btc_trend_text}}</td></tr>
      </tbody>
    </table>
  </div>

  <h3>宏观日历</h3>
  <div class="card">
    <div class="table-wrap">
      {{macro_calendar_html}}
    </div>
  </div>

  <hr class="section-divider">

  <!-- SECTION 5: WATCHLIST -->
  <h2>五、观察仓</h2>
  <div class="watchlist-row">
    {{watchlist_html}}
  </div>

  <!-- FOOTER -->
  <div class="report-footer">
    Generated by Crypto Monitor | Data: CoinGecko, DeFiLlama, CoinGlass, Alternative.me
  </div>

</div>
```

Keep JS for: score bars, BTC sparkline, ETF bar chart, TVL bar chart.
Delete JS for: Developer Activity (`chartDev`), History dual-axis (`chartHistory`).

- [ ] **Step 2: Verify the template has no syntax errors by checking placeholder count**

```bash
grep -c '{{' templates/dashboard.html
```

Expected: approximately 35-45 placeholders (down from 63).

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "templates: rewrite dashboard.html with alpha-first layout"
```

---

### Task 8: Rewrite CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

This is the most critical change — it drives the entire system behavior. Rewrite Phases 2-5 to implement alpha source scanning, freshness checking, and new report structure.

- [ ] **Step 1: Replace CLAUDE.md with the complete new version**

```markdown
# 加密货币 Alpha 情报监控系统

自动化加密货币 alpha 发现引擎，每天 08:00 / 20:00 (UTC+8) 执行。

**核心原则：** Alpha 优先 | 持仓深度 > 市场概览 | 禁止编造数据 | API 优先 | 一手信源 > 媒体报道

---

## Phase 0: 初始化

读取 `config/coins.json`（币种 + alpha_sources）、`config/alerts.json`（告警）、`config/output.json`（输出格式）。
读取 `data/latest.json`（上期数据，用于对比和新鲜度校验）。不存在则跳过对比。
确定日期、时段（morning/evening）、��月英文名。

---

## Phase 1: API 数据采集

**优先用免费 API（WebFetch JSON 端点）：**

| 来源 | 端点 | 数据 |
|------|------|------|
| CoinGecko | `/api/v3/simple/price?ids={所有币}&vs_currencies=usd&include_24hr_change=true&include_7d_change=true&include_market_cap=true` | 全币种价格/变化/市值 |
| CoinGecko | `/api/v3/coins/bitcoin?sparkline=true&developer_data=true` | BTC sparkline(168点) |
| CoinGlass | `open-api.coinglass.com/public/v2/funding` | 资金费率 |
| CoinGlass | `open-api.coinglass.com/public/v2/open_interest` | 未平仓合约 |
| DeFiLlama | `/v2/chains` | 全链 TVL |
| DeFiLlama | `/overview/fees` | 协议费用/收入 |
| DeFiLlama | `/summary/fees/{protocol}?dataType=dailyRevenue` | LINK/ETH 收入明细 |
| DeFiLlama | `stablecoins.llama.fi/stablecoinchains` | 各链稳定币供应 |
| Alternative.me | `/fng/` | Fear & Greed Index |

**WebFetch 页面抓取（按优先级尝试）：**

| 数据 | 主源 | 备用源 |
|------|------|--------|
| ETF 流向 | `farside.co.uk/btc/` | `sosovalue.com/assets/etf/us-btc-spot` |
| 代币���锁 | `token.unlocks.app/` | — |
| MVRV | `coinglass.com/pro/i/mvrv` | — |
| 交易所储备 | `cryptoquant.com/asset/btc/chart/exchange-flows/exchange-reserve` | — |

**降级链路：**
1. 免费 API JSON → 取返回值
2. 页面抓取（主源 → 备用源）→ 从 HTML 原文提取数字
3. 都失败 → 字段��� `null`，报告写「数据暂缺」
4. **禁止**：从 WebSearch 结果中提取数值��入 JSON

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

**BTC（context，4-5 次调用）：**
1. WebSearch BTC + ETF flows + 今日日期
2. WebSearch BTC + whale/on-chain + 今日日期
3. WebSearch BTC + FOMC/macro + 今日日期
4. WebSearch BTC + funding rate/OI + 今日日期

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
读取上期 `data/latest.json`，对链上指标逐字段比对：
- `mvrv_zscore`, `sopr_7d`, `exchange_reserves`, `whale_monthly_accumulation`, `funding_rate`
- 连续 ≥3 session 值不变 → 写入 `_freshness`，报告中标注「⚠️ 数据已 N 期未更新」
- **绝不**静默复读上期数据当新数据用

### 4.3 催化剂状态更新
对比上期 `holdings.{coin}.catalysts` 状态：
- Phase 2 发现进展 → 更新 `status` 和 `detail`
- 无新信息 → 保持上期状态不变（不编造进展）

### 4.4 告警评估
逐条��估 `config/alerts.json` 中的规则，按 severity 排序。

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
| Telegram | `bash scripts/telegram-push.sh` | 推送摘要+链接 |

**`data/latest.json` 结构：**
```json
{
  "timestamp": "ISO 8601",
  "session": "morning|evening",
  "alpha_signals": [{"coin","level","title","detail","source_type","source_url"}],
  "holdings": {"link": {..., "catalysts": [...]}, "eth": {...}, "monad": {...}},
  "market_context": {"btc": {...}, "macro": {...}},
  "watchlist": {"sol": {...}, "arb": {...}, "plume": {...}},
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
5. **ETF 流向数据必须来自 farside.co.uk 或 sosovalue.com 页面原文。** 失败则写 `null`。
6. **上期/本期有 `null` 的字段跳过 delta 计算。**
7. **`_sources` 为必填字段**，记录每个关键指标的数据来源。禁止 `websearch` 作为数值字段来源。
8. **Alpha 信号板没发现新信号 = 写「无新信号」。** 绝不编造或拔高旧信息。

---

## 错误处理

| 场景 | 处理 |
|------|------|
| WebFetch 失败 | WebSearch 补���定性信息；数值字段标 `null` / 「数据暂缺」 |
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
```

- [ ] **Step 2: Verify CLAUDE.md line count is reasonable**

```bash
wc -l CLAUDE.md
```

Expected: approximately 150-170 lines (up slightly from 108 but much denser in actionable content).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "rewrite: CLAUDE.md alpha-first execution flow with freshness checks"
```

---

### Task 9: Final verification

**Files:** All modified files

- [ ] **Step 1: Verify all config JSON files are valid**

```bash
python3 -c "import json; json.load(open('config/coins.json')); json.load(open('config/alerts.json')); json.load(open('config/output.json')); print('All config valid')"
```

- [ ] **Step 2: Verify template file inventory matches spec**

```bash
ls -la templates/
```

Expected exactly 4 files:
- `alpha-signals.md` (new)
- `coin-holding.md` (new)
- `market-overview.md` (rewritten)
- `dashboard.html` (rewritten)

- [ ] **Step 3: Verify no references to deleted templates remain**

```bash
grep -r "coin-standard\|coin-deep-track\|coin-watchlist\|historical-comparison" config/ templates/ CLAUDE.md
```

Expected: no matches.

- [ ] **Step 4: Verify alpha_sources defined for all holdings**

```bash
python3 -c "
import json
coins = json.load(open('config/coins.json'))['coins']
for c in coins:
    if c['priority'] in ('P0', 'P1'):
        assert 'alpha_sources' in c, f'{c[\"id\"]} missing alpha_sources'
        print(f'{c[\"id\"]} ({c[\"priority\"]}): alpha_sources OK')
"
```

Expected: link (P0), eth (P0), monad (P1) all have alpha_sources.

- [ ] **Step 5: Commit (if any fixups needed)**

Only if earlier steps revealed issues that were fixed. Otherwise skip.
