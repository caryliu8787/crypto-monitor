# Alpha-First Redesign Spec

Date: 2026-04-12
Status: Approved

---

## Problem Statement

The crypto-monitor system has structural problems that undermine its value:

1. **Report structure is inverted vs portfolio.** BTC (no position) gets 25% of report space (79 lines). LINK (largest position) gets P1 treatment (~30 lines).
2. **~60% of content is filler.** Recycled WebSearch results, frozen on-chain metrics presented as fresh, generic market commentary anyone can find.
3. **Data integrity failures.** 6 key fields (MVRV, SOPR, exchange reserves, whale accumulation, funding rate, dev commits) unchanged across 4+ consecutive sessions. No provenance tracking. Sparkline data fabricated when API fails.
4. **Config-implementation gap.** `coins.json` defines catalysts, custom_searches, defillama_slug fields that are never used. `historical-comparison.md` template is dead code.

## Design Goal

Restructure the system around **alpha discovery** -- surfacing catalysts and developments from first-hand sources before they become market consensus. Align report depth with actual portfolio positions (LINK > ETH > Monad >> the rest).

## User Context

- Portfolio: LINK (#1), ETH (#2), Monad (#3). BTC/SOL/ARB/PLUME are observation only.
- Priority: C (fundamentals tracking) > A (action decisions) > D (trend context) > B (anomaly detection)
- "Information edge" means: developments from primary sources (GitHub, on-chain contracts, governance forums, official blogs) that haven't yet been picked up by crypto media.
- Wants all primary source types scanned for holdings: GitHub, on-chain activity, official blogs, governance proposals, partner announcements.

---

## Section 1: Report Structure

### Current (320 lines, BTC-led)

```
1. Alert summary
2. BTC market overview (79 lines)
   - Price/ETF/on-chain/macro/technical
3. ETH standard (18 lines)
4. SOL standard (18 lines)
5. LINK deep track (30 lines)
6. ARB deep track (25 lines)
7. Monad watchlist (25 lines)
8. Plume watchlist (20 lines)
9. Historical comparison (20 lines)
10. Operation advice (40 lines)
11. Disclaimer
```

### New (~200 lines, Alpha-led)

```
1. Alpha Signal Board
   - New catalysts discovered today, grouped by coin
   - Information edge rating: red(first-mover) / yellow(early) / green(spread) / gray(none)
   - Source links for every signal

2. Holdings Tracker
   - LINK deep (primary source scan results)
   - ETH deep (upgrade/ecosystem progress)
   - Monad deep (ecosystem/TVL/partnerships)
   Each includes: core metrics table, catalyst status updates, new partnerships, vs prior period

3. Action Recommendations
   - Derived from sections 1+2
   - Explicit: act / hold / conditional trigger
   - Time frame for each

4. Market Context (compact)
   - BTC price + core on-chain indicators (with freshness annotations)
   - Macro calendar (next 3 days + major events only)
   - Market score /20

5. Watchlist (SOL/ARB/PLUME, 2-3 lines each)
   - Price | 24h change | one-line headline or null
```

### Key changes

- Alpha signal board at top -- first thing visible on open.
- Holdings ordered LINK > ETH > Monad, each gets deep coverage.
- BTC demoted from protagonist to "market context" backdrop, ~30 lines down from 79.
- SOL/ARB/PLUME merged into single watchlist section, 2-3 lines each.
- Total ~200 lines, down from ~320.

---

## Section 2: Alpha Signal Board

### Signal Sources (by information edge window)

| Source Type | Specific Sources | Method | Edge Window |
|-------------|-----------------|--------|-------------|
| On-chain contract activity | CCIP new lane deployments, Reserve contract buys, new price feeds | WebFetch block explorer | 1-6 hours |
| GitHub commits | smartcontractkit, ethereum, monad-labs repos | WebFetch GitHub API | 2-12 hours |
| Official blogs | blog.chain.link, blog.ethereum.org, monad.xyz | WebFetch RSS/page | 6-24 hours |
| Governance proposals | Chainlink community forum, Snapshot votes, AllCoreDevs | WebFetch + WebSearch | 12-48 hours |
| Partner announcements | Aave/Coinbase/Swift/DTCC mentioning held coins | WebSearch targeted | 12-48 hours |
| Industry media | The Block/Blockworks/CoinDesk | WebSearch | 24-48 hours (already spread) |

### Signal Rating Rules

- **Red (first-mover):** Information from on-chain/GitHub/official source, no Google News coverage found.
- **Yellow (early):** Discussed only in professional communities (governance forums, developer Discord), not yet in mainstream media.
- **Green (already spread):** CoinDesk/The Block/etc have published articles. Edge window closed.
- **Gray (no signal):** No new catalyst discovered for this coin today. One line stating this.

### Signal Format in Report

```markdown
## Alpha Signal Board

### Red -- First-Mover Signals
- **[LINK] CCIP new Avalanche<>Arbitrum lane** -- contract deployed 4/12 03:17 UTC
  (source: Etherscan contract creation)

### Yellow -- Early Signals
- **[LINK] Grayscale GLNK week 14 consecutive net inflow** -- +$2.3M this week
  (source: Grayscale official holdings)

### Green -- Already Spread
- **[MON] NYSE partnership details published** -- covered by The Block
  (source: The Block)

### Gray -- No New Signals
- ETH: No Glamsterdam progress update today
```

### Constraints

- No signal discovered = write "no new signal". Never fabricate or inflate old information.
- Every signal must include a source link.
- Same information already in prior report with no progress update does not reappear.

---

## Section 3: Data Layer (`latest.json`)

### New Top-Level Structure

```json
{
  "timestamp": "ISO 8601",
  "session": "morning|evening",
  "alpha_signals": [],
  "holdings": {},
  "market_context": {},
  "watchlist": {},
  "market_score": {},
  "_sources": {},
  "_freshness": {}
}
```

### `alpha_signals` Array

```json
[
  {
    "coin": "link",
    "level": "red|yellow|green",
    "title": "Short description",
    "detail": "One-line context",
    "source_type": "onchain|github|blog|governance|partner|media",
    "source_url": "https://..."
  }
]
```

### `holdings` Object

Contains LINK, ETH, Monad with full metrics + catalyst tracking:

```json
"holdings": {
  "link": {
    "price": 9.07, "change_24h": -0.21, "change_7d": null,
    "market_cap": 6590000000,
    "staking_tvl_link": 45000000, "staking_apy": 0.0432,
    "reserve_accumulated_link": 3064151,
    "ccip_monthly_volume": 18000000000,
    "revenue_30d": 4550000,
    "catalysts": [
      {"id": "etf_flows", "status": "active", "detail": "GLNK week 14 net inflow"},
      {"id": "ccip_v15", "status": "progressing", "detail": "Monthly volume $18B"}
    ]
  },
  "eth": { "price, tvl, staking, upgrade progress fields..." },
  "monad": { "price, tvl, ecosystem, partnership fields..." }
}
```

### `market_context` Object

BTC indicators + macro, compact:

```json
"market_context": {
  "btc": {
    "price": 73062, "change_24h": 0.22, "change_7d": 8.42,
    "dominance": 57.5, "fear_greed": 16,
    "mvrv_zscore": 1.2,
    "exchange_reserves": 2210000,
    "whale_monthly_accumulation": 270000,
    "funding_rate": 0.005,
    "open_interest": 53870000000,
    "key_support": 68200, "key_resistance": 73595
  },
  "macro": {
    "next_fomc": "2026-04-28",
    "fomc_hold_probability": 97.9
  }
}
```

### `watchlist` Object

Minimal fields per coin:

```json
"watchlist": {
  "sol": { "price": 84.94, "change_24h": 0.19, "tvl": 5834246074, "headline": null },
  "arb": { "price": 0.1156, "change_24h": -0.68, "next_unlock": "2026-04-16", "headline": null },
  "plume": { "price": 0.00975, "change_24h": 2.53, "headline": null }
}
```

### `_sources` Object

Records where each key metric came from. Required field.

```json
"_sources": {
  "btc_price": "coingecko_api",
  "mvrv_zscore": "cryptoquant_page",
  "exchange_reserves": null,
  "fear_greed": "alternative_api",
  "link_staking_tvl": "defillama_api"
}
```

Allowed values: `coingecko_api` | `coinglass_api` | `blockchain_api` | `defillama_api` | `alternative_api` | `farside_page` | `sosovalue_page` | `cryptoquant_page` | `glassnode_page` | `coinglass_page` | `token_unlocks_page` | `null`. The value `websearch` is prohibited for numeric fields.

### `_freshness` Object

Automatic staleness tracking for on-chain indicators:

```json
"_freshness": {
  "mvrv_zscore": { "value": 1.2, "unchanged_since": "2026-04-09T08:00:00+08:00", "sessions_unchanged": 6 },
  "exchange_reserves": { "value": 2210000, "unchanged_since": "2026-04-09T20:00:00+08:00", "sessions_unchanged": 5 }
}
```

Report generation rule: if `sessions_unchanged >= 3`, append warning to that metric in the report.

### Deleted Fields

- `dev_commits_4w` (never changes)
- `ath` / `ath_change` (static, low value)
- `altseason_index` (low information density)
- `cross_chain_tvl` top-level object (merged into per-coin data)

---

## Section 4: Config & Templates

### 4a: `coins.json` Priority Realignment

```
LINK:  P1 -> P0 (largest position)
ETH:   P0 -> P0 (unchanged)
Monad: P2 -> P1 (third position)
BTC:   P0 -> context (market backdrop, not a coin entry)
SOL:   P1 -> P2 (watchlist)
ARB:   P2 -> P2 (watchlist)
PLUME: P2 -> P2 (watchlist)
```

### Search Volume Allocation

| Priority | Searches | Coins |
|----------|----------|-------|
| BTC context | 4-5 | BTC (down from 6-8) |
| P0 | 8-10 | LINK, ETH (full primary source scan) |
| P1 | 6-8 | Monad |
| P2 | 2-3 | SOL, ARB, PLUME |

### `alpha_sources` Field (replaces empty `custom_searches`)

LINK example:

```json
"alpha_sources": {
  "github": "https://github.com/smartcontractkit",
  "blog": "https://blog.chain.link",
  "ccip_contracts": "Search Etherscan for CCIP-related contract deployments in last 24h",
  "reserve_contract": "0x... Reserve contract address, check recent buy events",
  "partnerships": ["Aave", "Coinbase", "Swift", "DTCC", "JPMorgan", "Mastercard"],
  "etf_tracking": ["GLNK Grayscale", "CLNK Bitwise"]
}
```

ETH and Monad get analogous `alpha_sources` definitions.

### Deleted Config Fields

- `custom_searches` (empty arrays, replaced by `alpha_sources`)
- `l2beat_tracked` (never used)
- Redundant `metrics` sub-objects (catalyst definitions move to `alpha_sources`, runtime status to `latest.json`)

### 4b: Template Consolidation

**Delete:**
- `coin-standard.md` (hardcoded ETH/SOL conditionals)
- `coin-deep-track.md`
- `coin-watchlist.md`
- `historical-comparison.md` (dead code)

**Create:**
- `alpha-signals.md` -- Alpha signal board template
- `coin-holding.md` -- Single parameterized template, detail level controlled by priority:
  - P0 (LINK/ETH): Full -- metrics table + catalyst tracking + partnerships + primary source findings + vs prior period
  - P1 (Monad): Medium -- metrics table + catalysts + ecosystem projects
  - P2 (SOL/ARB/PLUME): One-line -- `price | 24h | headline`

Result: 6 Markdown templates -> 2 Markdown templates + market-overview.md (compressed).

### 4c: HTML Dashboard

**Structure follows new report:**
- Top: Alpha signal board cards (red/yellow/green/gray tags)
- Middle: Holdings tracker (LINK / ETH / Monad panels)
- Bottom: Market context (compact BTC chart + score)
- Footer: Watchlist one-line list

**Charts retained:**
- BTC sparkline (with freshness annotation)
- ETF flow bar chart
- TVL horizontal bar (ETH/SOL/ARB only, Monad+Plume merged to "Other")

**Charts deleted:**
- Developer Activity (data never changes)
- Historical FGI + Score trend (low signal)

---

## Section 5: CLAUDE.md Execution Flow

### Phase Restructure

```
Current                              New
───────                              ───
Phase 0: Init (read config)          Phase 0: Init (unchanged)
Phase 1: API data collection (all)   Phase 1: API collection (streamlined + on-chain page scraping)
Phase 2: BTC deep search (6-8)       Phase 2: Alpha Source Scan (core change)
Phase 3: Altcoin search (by P)       Phase 3: Holdings deep + watchlist brief
Phase 4: Analysis                    Phase 4: Analysis (+ alpha rating + freshness check)
Phase 5: Report generation           Phase 5: Report generation (new structure)
Phase 6: Output                      Phase 6: Output (unchanged)
```

### Phase 2: Alpha Source Scan (biggest change)

For each holding, scan `alpha_sources` defined in `coins.json`:

```
LINK (P0, 8-10 calls):
  1. WebFetch blog.chain.link -> check posts in last 48h
  2. WebFetch GitHub smartcontractkit -> recent commits/releases
  3. WebFetch Etherscan -> Reserve contract recent transactions
  4. WebSearch "Chainlink CCIP" + today's date -> new lanes/integrations
  5. WebSearch each partner name + "Chainlink" -> partner-side announcements
  6. WebFetch Grayscale GLNK holdings page -> weekly inflow/outflow
  7. WebSearch "Chainlink governance proposal" -> governance activity
  8. WebSearch "LINK" + today's date -> catch-all sweep

ETH (P0, 6-8 calls):
  1. WebFetch blog.ethereum.org
  2. WebFetch GitHub ethereum/pm -> AllCoreDevs notes
  3. WebSearch "Glamsterdam upgrade" / "ePBS" + latest
  4. WebSearch "Ethereum" + staking/L2/blob + today's date
  5-6. Targeted partner/ecosystem searches

Monad (P1, 6-8 calls):
  1. WebFetch monad.xyz blog
  2. WebSearch "Monad" + ecosystem/partnership + today's date
  3-6. DApp deployments, TVL changes, partnership announcements

BTC (context, 4-5 calls):
  1. WebSearch BTC + ETF flows + today's date
  2. WebSearch BTC + whale/on-chain + today's date
  3. WebSearch BTC + FOMC/macro + today's date
  4. WebSearch BTC + funding rate/OI + today's date
```

Key difference from current: WebFetch primary sources first, then WebSearch for media. LINK gets the most search volume. BTC compressed to 4-5 contextual queries.

### Phase 4: New Analysis Logic

```
4.1 Alpha Rating:
    - For each new finding from Phase 2, search Google News for coverage
    - No coverage -> red (first-mover)
    - Professional media only -> yellow (early)
    - Mainstream media covered -> green (already spread)

4.2 Freshness Check:
    - Read prior latest.json
    - Compare on-chain indicators field by field (MVRV/SOPR/reserves/whale/funding)
    - Unchanged >= 3 consecutive sessions -> record in _freshness
    - Report appends warning to that metric

4.3 Catalyst Status Update:
    - Compare prior session catalyst states
    - Phase 2 found progress -> update status and detail
    - No new info -> keep prior status unchanged (do not fabricate progress)
```

---

## Files Changed (Implementation Scope)

| File | Action | Description |
|------|--------|-------------|
| `CLAUDE.md` | Rewrite | Phases 2-5 restructured, search allocation, alpha rules |
| `config/coins.json` | Rewrite | Priority realignment, alpha_sources, field cleanup |
| `config/alerts.json` | Edit | Adjust alert coins to match new priorities |
| `templates/alpha-signals.md` | Create | New alpha signal board template |
| `templates/coin-holding.md` | Create | New parameterized coin template |
| `templates/market-overview.md` | Edit | Compress to market context section |
| `templates/coin-standard.md` | Delete | Replaced by coin-holding.md |
| `templates/coin-deep-track.md` | Delete | Replaced by coin-holding.md |
| `templates/coin-watchlist.md` | Delete | Replaced by coin-holding.md |
| `templates/historical-comparison.md` | Delete | Dead code |
| `templates/dashboard.html` | Rewrite | New section order, alpha cards, chart cleanup |
| `data/latest.json` | Will be overwritten | New structure on next run |
