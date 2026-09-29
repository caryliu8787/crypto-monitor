#!/usr/bin/env python3
"""一次性组装 2026-09-29 daily 期 data/latest.json（数值全部来自 collected.json 或定向 API）。"""
import json

C = json.load(open("data/collected.json"))
btc, eth, glob = C["btc"], C["eth"], C["global"]

movers_reasons = {
    "quant-network": ("Sibos 第二日：TCH 选定效应持续发酵，Quant 今日（美东下午）还有「The Tokenised Money Stack」panel；价格两日累涨逾 60%", "代币化结算/机构采用", "https://www.theclearinghouse.org/payment-systems/Articles/2026/09/The-Clearing-House-Partners-with-Quant-to-Advance-the--On-Chain-Money-Initiative"),
    "shuffle-2": ("原因未明（加密赌场代币，无可核实项目级催化剂）", "Gambling 动量", None),
    "marscoin-4": ("BSC meme，Binance 9 月初合约+现货上架后动量延续；无可核实新催化剂", "Meme", None),
    "pearl-2": ("9/23 创历史新高 $1.76 后持续回吐（30d +410% 抛物线回撤中）", "AI 挖矿/回吐", None),
    "grass": ("7d +54% 后连续第 2 期随大盘回调；基本面背景不变（DataCo 收入验证；10 月下旬投资人解锁日期待确认）", "DePIN", None),
    "hedera-hashgraph": ("原因未明为主：连续第 2 日大涨且量能放大至 $12.86 亿；可查背景为 Hedera 9 月上线官方 Docs MCP 服务器（AI 开发工具），但与两日累涨约 60% 的量级不匹配", "L1/机构叙事", "https://coinmarketcap.com/cmc-ai/hedera/latest-updates/"),
    "stonk-3": ("收入数据尚未更新（DeFiLlama 最新整日仍为 9/27 $52.9 万），价格延续回调（7d -36.2%）", "Launchpad 收入", "https://api.llama.fi/summary/fees/stonkfun?dataType=dailyRevenue"),
    "backpack": ("创历史新高后连续第 3 期回吐（24h -13.32%），「年度最重要发布」仍无日期", "ATH 后回吐", None),
    "akedo": ("原因未明（30d +283% 后的持续退潮，7d -39.4%）", "退潮", None),
    "layerzero": ("9 月下旬有约 3,260 万枚 ZRO 计划解锁的媒体报道（CMC 口径）叠加 7d +30.7% 后回吐", "解锁/回吐", "https://coinmarketcap.com/cmc-ai/layerzero/latest-updates/"),
    "the-graph": ("原因未明（9/22 以来放量上行后回吐，无项目级一手催化剂）", "AI/索引", None),
    "useless-3": ("原因未明（Meme，30d +282% 后回吐，24h -19.2% 为本期最大跌幅）", "Meme/回吐", None),
}
movers = []
for m in C["movers"]:
    r, tag, url = movers_reasons[m["coin_id"]]
    movers.append({"coin_id": m["coin_id"], "symbol": m["symbol"], "price_usd": m["price_usd"],
                   "price_change_24h": m["price_change_24h"], "price_change_7d": m["price_change_7d"],
                   "price_change_30d": m["price_change_30d"], "market_cap": m["market_cap"],
                   "volume_24h": m["volume_24h"], "reason": r, "narrative_tag": tag, "source_url": url})

def opp(id, coin, title, thesis, diffusion, cs, tw, cr, rk, status, first, tracked, ssp, url):
    return {"id": id, "coin": coin, "title": title, "thesis": thesis, "diffusion": diffusion,
            "score": {"catalyst_strength": cs, "time_window": tw, "crowding": cr, "risk": rk, "total": cs + tw + cr + rk},
            "status": status, "first_seen": first, "last_updated": "2026-09-29",
            "sessions_tracked": tracked, "sessions_since_progress": ssp, "source_url": url}

opps = [
    opp("ondo-dtcc-tokenization", "ONDO", "ONDO：维持 16（ssp=3）", "本期无新信息，不编造进展。3 只 Intelligent Portfolios 组合的持有人数与规模仍无公开可引用口径。", "green", 5, 5, 2, 4, "tracking", "2026-07-12_evening", 72, 3, "https://ondo.finance/blog/introducing-ondo-intelligent-portfolios"),
    opp("quant-sibos-murex-settlement", "QNT", "QNT：维持 16（ssp=1）—— Sibos 第二日，价格继续冲高", "Sibos 进入第二日（9/29），Quant 今日美东下午还有「The Tokenised Money Stack—Making Programmable Settlement Real」panel，10/1 另有「Why Regions Are Racing to Tokenise Deposits」。QNT $241.00（24h **+29.70%**、7d **+261.03%**、30d +293.36%），市值 $35.05 亿，v/mc 45.1%——**连续第 2 期大涨，TCH 效应仍在发酵。** 四维评分不变；⚠️定性不变且更强：Sibos 剩余日程更可能是 sell-the-news，真正现金流窗口在 2027 上半年。**验证方式不变：** 10/1 闭幕后一周内是否缩量回落。", "green", 5, 5, 2, 4, "tracking", "2026-09-25", 4, 1, "https://www.theclearinghouse.org/payment-systems/Articles/2026/09/The-Clearing-House-Partners-with-Quant-to-Advance-the--On-Chain-Money-Initiative"),
    opp("aave-aavenomics-buyback", "AAVE", "AAVE：维持 stale（ssp=11）", "本期无新信息，不编造进展。", "green", 4, 4, 4, 3, "stale", "2026-07-06_morning", 83, 11, "https://api.llama.fi/summary/fees/aave?dataType=dailyRevenue"),
    opp("filecoin-onchain-cloud-mainnet", "FIL", "FIL：维持 stale（ssp=7）", "本期无新信息，不编造进展。10/15 归属结束剩 16 天，事件仍在日历中。", "yellow", 5, 4, 3, 3, "stale", "2026-09-14_daily", 15, 7, "https://www.kucoin.com/blog/fil-issuance-drops-75-percent-in-october-2026-as-filecoin-paid-onchain-demand-grows"),
    opp("chainlink-ccip-institutional", "LINK", "LINK：维持 stale（ssp=30）", "本期无新信息，不编造进展。", "green", 5, 4, 2, 4, "stale", "2026-07-19_morning", 59, 30, "https://genfinity.io/2026/08/11/chainlink-johann-eid-dtcc-collateral-appchain-ccip-tokenization/"),
    opp("meteora-revenue-buyback-unlock-window", "MET", "MET：维持 15（ssp=4）—— ⚠️9/28 不完整日收入仅 $36,246，按速率全天约 $4.3 万", "⚠️**降级线预警升级。** DeFiLlama `summary/fees/meteora`：9/27 整日 **$104,904**（惊险保住 $10 万线）；**9/28 为不完整日（UTC 已过约 20/24 小时）仅 $36,246——按当前速率外推全天约 $4.3 万，远低于 $10 万降级线。** 若明日确认 9/28 整日 <$10 万，则「连续 3 日跌破」倒计时从第 1 天开始。10/23 解锁剩 24 天。评分四维未变（不完整日不构成整日判据触发）→ ssp 计 4。\n**验证方式（不变）：** 日收入回到 $15 万以上 = 强化；连续 3 日 <$10 万 = 降 catalyst_strength。", "yellow", 3, 5, 4, 3, "tracking", "2026-09-24", 5, 4, "https://api.llama.fi/summary/fees/meteora?dataType=dailyRevenue"),
    opp("morpho-robinhood-earn-distribution", "MORPHO", "MORPHO：维持 stale（ssp=21）", "本期无新信息，不编造进展。", "yellow", 5, 4, 3, 3, "stale", "2026-07-10_morning", 76, 21, "https://api.llama.fi/protocol/morpho-blue"),
    opp("uniswap-fee-switch-revenue", "UNI", "UNI：⬇️tracking→stale（ssp=5，按 4.7(a) 机械降级）", "ssp 达到 5，按 4.7(a) 机械降 stale——CME 10/19 期货（剩 20 天，pending regulatory review）本身无变化，但连续 5 期无新增一手。**与 FIL 同例：事件在日历中继续跟踪，条目本身降级。** 恢复条件：CME 上线确认或监管复核通过公告。", "green", 4, 5, 2, 4, "stale", "2026-07-10_evening", 75, 5, "https://www.prnewswire.com/news-releases/cme-group-to-expand-crypto-derivatives-suite-with-bitcoin-cash-and-uniswap-futures-302886066.html"),
    opp("arbitrum-robinhood-fee-share", "ARB", "ARB：维持 stale（ssp=9）", "本期无新信息，不编造进展。", "green", 5, 4, 3, 2, "stale", "2026-07-09_evening", 77, 9, "https://www.sec.gov/newsroom/press-releases/2026-90-sec-issues-innovation-exemption-facilitate-trading-tokenized-nms-stock-request-comment"),
    opp("coti-v2-sunset-buyback", "COTI", "COTI：维持 stale（ssp=10）", "本期无新信息，不编造进展。V1 日落截止 9/30（明天）仍在日历中。", "yellow", 4, 5, 3, 2, "stale", "2026-09-18", 11, 10, "https://cotinetwork.medium.com/sunset-of-coti-v1-essential-steps-to-secure-your-v2-tokens-5f33ff3e07f2"),
    opp("injective-rwa-institutional-cluster", "INJ", "INJ：维持 stale（ssp=8）", "本期无新信息，不编造进展。", "green", 5, 4, 3, 2, "stale", "2026-09-13_daily", 16, 8, "https://coinmarketcap.com/top-stories/6aae099518d5f96e3a16bf1e/"),
    opp("mantle-super-portal-rwa", "MNT", "MNT：维持 stale（ssp=23）", "本期无新信息，不编造进展。", "yellow", 3, 4, 3, 4, "stale", "2026-08-13_daily", 35, 23, "https://coinedition.com/mantle-price-prediction-august-2026-mnt-jumps-9-as-super-portal-goes-live-on-solana-with-chainlink-backing/"),
    opp("pump-fun-revenue-buyback", "PUMP", "PUMP：维持 stale（ssp=9）", "本期无新信息，不编造进展。", "green", 5, 4, 2, 3, "stale", "2026-07-16_morning", 65, 9, "https://api.llama.fi/summary/fees/pump.fun?dataType=dailyRevenue"),
    opp("solana-etf-inflow-governance", "SOL", "SOL：维持 12（ssp=1）", "本期无新增一手。「9/28 非 Alpenglow 主网激活日」的纠偏已结算；下一 tentative 窗口 11/9（未点名 Alpenglow，不建事件）。Solana 链 TVL $65.77 亿、环比 +0.39%（美元口径转正）。验证方式不变。", "green", 4, 3, 2, 3, "tracking", "2026-08-28_daily", 25, 1, "https://finance.yahoo.com/markets/crypto/articles/solana-developers-no-alpenrush-alpenglow-095429771.html"),
    opp("stonkfun-revenue-buyback-burn", "STONK", "STONK：维持 14（ssp=2）—— 9/28 收入数据尚未出炉，等待判决", "**DeFiLlama 最新整日仍为 9/27 $529,093（两日 -44%），9/28 整日数据本期尚未产生——降级判据（连续 3 日 <$50 万）仍是 0 天触发、等待数据的状态。** STONK $0.2491（24h **-7.78%**、7d **-36.17%**），市值 $2.03 亿。价格已抢先于收入数据下行。\n**验证方式（不变）：** 连续 3 日 <$50 万 → catalyst 降 2；回到 $80 万以上 → 论点成立。明日出炉的 9/28 整日数据是关键。", "yellow", 4, 5, 3, 2, "tracking", "2026-09-25", 4, 2, "https://api.llama.fi/summary/fees/stonkfun?dataType=dailyRevenue"),
    opp("stacks-genesis-bond-genesis-bond", "STX", "STX：维持 stale（ssp=11）", "本期无新信息，不编造进展。", "green", 5, 4, 3, 2, "stale", "2026-08-22_daily", 29, 11, "https://cryptoslate.com/hashkey-cloud-backs-stacks-genesis-bond-to-prove-institutional-appetite-for-native-bitcoin-yield/"),
    opp("avalanche-helicon-upgrade", "AVAX", "AVAX：维持 triggered（ssp=5）", "升级后跟进：Avalanche 链 TVL $6.17 亿（-0.39%），仍低于 $6.31 亿判据，连续第 5 期未收复。维持 triggered。", "green", 4, 5, 1, 3, "triggered", "2026-09-20", 9, 5, "https://build.avax.network/blog/helicon-upgrade"),
    opp("bitcoin-cash-cme-futures", "BCH", "BCH：维持 13（ssp=3）", "本期无新信息，不编造进展。CME BCH 期货 10/19（剩 20 天，pending regulatory review）。", "green", 4, 5, 1, 3, "tracking", "2026-09-23", 6, 3, "https://www.prnewswire.com/news-releases/cme-group-to-expand-crypto-derivatives-suite-with-bitcoin-cash-and-uniswap-futures-302886066.html"),
    opp("canton-dtcc-tokenization", "CC", "CC：维持 stale（ssp=26）", "本期无新信息，不编造进展。", "green", 5, 3, 2, 3, "stale", "2026-07-18_evening", 61, 26, "https://www.canton.network/dtc-and-fed-eligible-securities-on-canton"),
    opp("gnosis-gip151-redemption", "GNO", "GNO：维持 stale（ssp=47）", "本期无新信息，不编造进展。", "yellow", 5, 3, 3, 2, "stale", "2026-07-15_evening", 67, 47, "https://thecurrencyanalytics.com/altcoins/gno-holders-face-170-redemption-offer-as-activists-target-220m-gnosis-treasury-256794"),
    opp("grass-dataco-verified-revenue", "GRASS", "GRASS：维持 12（ssp=1）", "本期无新增一手。GRASS $0.5704（24h -8.70%、7d +54.07%），连续第 2 期回调。10 月下旬投资人解锁（占总供应 25.2%）精确日期仍待 tokenomist 确认 → 确认后建事件条目。", "yellow", 4, 3, 3, 2, "tracking", "2026-09-26", 3, 1, "https://coinmarketcap.com/cmc-ai/grass/latest-updates/"),
    opp("litecoin-grayscale-etf-conversion", "LTC", "LTC：维持 13（ssp=3）", "本期无新信息，不编造进展。SEC 决定截止日仍无带 2026 年份的可检索来源，不进事件日历。", "green", 4, 3, 2, 4, "tracking", "2026-09-25", 4, 3, "https://cryptorank.io/news/feed/674cb-litecoin-price-prediction-ltc-surges-15-as-grayscale-pushes-for-a-spot-etf"),
    opp("monad-defi-inflection", "MON", "MON：维持 stale（ssp=27）", "本期无新信息，不编造进展。", "yellow", 5, 4, 2, 2, "stale", "2026-07-06_morning", 83, 27, "https://api.llama.fi/v2/chains"),
    opp("pyth-network-nasdaq-totalview", "PYTH", "PYTH：维持 stale（ssp=50）", "本期无新信息，不编造进展。", "yellow", 4, 3, 3, 3, "stale", "2026-07-07_morning", 84, 50, "https://coinmarketcap.com/cmc-ai/pyth-network/latest-updates/"),
    opp("layerzero-zero-chain-gas-token", "ZRO", "ZRO：维持 13（ssp=4）", "本期无新增一手。ZRO $1.55（24h **-10.06%**、7d +30.69%）——CMC 口径 9 月下旬有约 3,260 万枚 ZRO 计划解锁，叠加短线回吐。Zero L1 主网仍无确切日期；协议收入近零的反证未变。", "yellow", 4, 4, 3, 2, "tracking", "2026-08-05_daily", 42, 4, "https://coinmarketcap.com/cmc-ai/layerzero/latest-updates/"),
    opp("edgex-buyback-burn", "EDGE", "EDGE：维持 stale（ssp=18）", "本期无新信息，不编造进展。", "yellow", 3, 5, 3, 1, "stale", "2026-07-12_morning", 73, 18, "https://coinmarketcap.com/cmc-ai/edgex/latest-updates/"),
    opp("hyperliquid-preipo-futures", "HYPE", "HYPE：维持 stale（ssp=29）", "本期无新信息，不编造进展。", "yellow", 4, 2, 3, 3, "stale", "2026-08-21_daily", 30, 29, "https://cryptoticker.io/en/hyperliquid-hype-sec-pre-ipo-push/"),
    opp("lido-nest-buyback", "LDO", "LDO：维持 12（ssp=2）", "本期无新信息，不编造进展。NEST 累计预算为负、ETH $2,674 仍低于 $3,000 启动条件——两条压制均未变。", "yellow", 3, 3, 3, 3, "tracking", "2026-07-08_morning", 80, 2, "https://cryptoslate.com/ethereums-institutional-staking-boom-is-growing-but-lidos-share-is-shrinking/"),
    opp("lighter-perp-dex-listing", "LIT", "LIT：维持 12（ssp=4）", "本期无新信息，不编造进展。", "yellow", 3, 3, 3, 3, "tracking", "2026-07-06_morning", 83, 4, "https://coinmarketcap.com/cmc-ai/lighter/latest-updates/"),
    opp("polygon-staking-reform", "POL", "POL：维持 stale（ssp=23）", "本期无新信息，不编造进展。", "yellow", 3, 3, 2, 4, "stale", "2026-08-18_daily", 33, 23, "https://www.coingabbar.com/en/price-prediction/polygon-price-prediction-august-2026"),
    opp("maple-syrup-kraken-lending", "SYRUP", "SYRUP：维持 stale（ssp=49）", "本期无新信息，不编造进展。", "yellow", 4, 2, 3, 3, "stale", "2026-07-10_evening", 75, 49, "https://www.coingecko.com/en/coins/syrup"),
    opp("venice-vvv-emission-cut", "VVV", "VVV：维持 stale（ssp=13）", "本期无新信息，不编造进展。10/1 第二阶段排放削减剩 2 天，是它能否回到 tracking 的唯一判据。", "green", 4, 4, 2, 2, "stale", "2026-07-08_evening", 80, 13, "https://api.llama.fi/summary/fees/venice?dataType=dailyRevenue"),
    opp("stellar-protocol27-bitwise", "XLM", "XLM：维持 stale（ssp=58）", "本期无新信息，不编造进展。", "yellow", 4, 2, 3, 3, "stale", "2026-07-12_morning", 73, 58, "https://www.coingecko.com/en/coins/stellar"),
    opp("plasma-unlock-cliff-repricing", "XPL", "XPL：维持 triggered（ssp=2）", "本期无新信息，不编造进展。cliff 已结算；此后 24 个月按月释放，「利空出尽」仅对本次成立。", "green", 3, 5, 2, 2, "triggered", "2026-09-25", 4, 2, "https://tokenomist.ai/plasma"),
    opp("zcash-privacy-etf-rotation", "ZEC", "ZEC：维持 stale（ssp=7）", "本期无新信息，不编造进展。FIRO 连续两期居热搜首位，隐私板块热度仍在，但无新的一手资金面证据。", "green", 5, 4, 1, 2, "stale", "2026-09-04_daily", 19, 7, "https://www.kucoin.com/blog/zcash-price-prediction-2026-why-zec-just-hit-a-new-multi-year-high"),
    opp("argus-arc-mainnet-launchpad", "ARGUS", "ARGUS：维持 stale（ssp=10）", "本期无新信息，不编造进展。", "yellow", 3, 3, 4, 1, "stale", "2026-09-17", 12, 10, "https://www.coingecko.com/en/coins/argus"),
    opp("curve-llamalend-v2-incentives", "CRV", "CRV：维持 stale（ssp=19）", "本期无新信息，不编造进展。", "yellow", 3, 3, 3, 2, "stale", "2026-08-10_daily", 38, 19, "https://blockworks.co/news/yield-basis-curve-dao-vote"),
    opp("derive-tokenized-gold-derivatives", "DRV", "DRV：维持 11（ssp=4）", "本期无新信息，不编造进展。V3 迁移仍无确切日期。", "green", 4, 4, 2, 1, "tracking", "2026-08-27_daily", 26, 4, "https://www.kucoin.com/news/flash/derive-proposes-v3-deployment-and-derive-chain-shutdown"),
    opp("ethena-falconx-lending", "ENA", "ENA（FalconX 线）：维持 expired", "已关闭（论点并入 ethena-fee-switch-usde-threshold），保留仅为历史连续。", "green", 4, 3, 2, 2, "expired", "2026-08-22_daily", 27, 6, "https://coinmarketcap.com/top-stories/6a9cca3698f4795d490fd4c1/"),
    opp("etherfi-restaking-recovery", "ETHFI", "ETHFI：维持 stale（ssp=10）", "本期无新信息，不编造进展。", "yellow", 3, 3, 3, 2, "stale", "2026-07-09_evening", 77, 10, "https://api.llama.fi/summary/fees/ether.fi?dataType=dailyRevenue"),
    opp("four-4stock-stock-paired-launchpad", "FORM", "FORM：维持 stale（ssp=17）", "本期无新信息，不编造进展。", "yellow", 3, 3, 4, 1, "stale", "2026-09-09_daily", 18, 17, "https://www.cryptopolitan.com/cea-industries-jumps-four-meme-bnc4-token/"),
    opp("jito-jtx-perp-launch", "JTO", "JTO：维持 stale（ssp=55）", "本期无新信息，不编造进展。", "yellow", 3, 2, 4, 2, "stale", "2026-07-08_evening", 80, 55, "https://coinmarketcap.com/cmc-ai/jito/price-analysis/"),
    opp("mina-mesa-hardfork", "MINA", "MINA：维持 stale（ssp=15）", "本期无新信息，不编造进展。", "yellow", 3, 3, 3, 2, "stale", "2026-09-13_daily", 16, 15, "https://www.bitrue.com/blog/major-blockchain-upgrades-in-september-2026"),
    opp("pendle-fee-inflection", "PENDLE", "PENDLE：维持 stale（ssp=13）", "本期无新信息，不编造进展。", "yellow", 3, 3, 3, 2, "stale", "2026-08-24_daily", 27, 13, "https://api.llama.fi/summary/fees/pendle?dataType=dailyRevenue"),
    opp("raydium-launchlab-stonkfun-revenue", "RAY", "RAY：维持 11（ssp=3）—— 9/28 不完整日已超昨日全天，初步企稳", "DeFiLlama `summary/fees/raydium`：9/27 整日 $118,842；**9/28 不完整日（UTC 约 20/24 小时）已录得 $120,195，超过昨日全天**——下滑斜率首次走平。但恢复判据（连续 3 日 >$40 万）仍遥远，维持 11 不变。下期若日收入仍低于 $15 万 → catalyst_strength 3→2 的预警继续有效。", "green", 3, 4, 2, 2, "tracking", "2026-09-10_daily", 17, 3, "https://api.llama.fi/summary/fees/raydium?dataType=dailyRevenue"),
    opp("vechain-vip255-upgrade", "VET", "VET：维持 stale（ssp=15）", "本期无新信息，不编造进展。", "yellow", 3, 2, 4, 2, "stale", "2026-08-28_daily", 25, 15, "https://www.coincarp.com/events/vechaincom-interstellar-upgrade/"),
    opp("zama-confidential-rfq", "ZAMA", "ZAMA：维持 11（ssp=4）", "本期无新增一手。mc/fdv 仅 0.22 的硬风险未变。", "yellow", 4, 3, 2, 2, "tracking", "2026-07-28_daily", 49, 4, "https://www.kucoin.com/news/flash/zama-scales-privacy-defi-with-16-new-vaults-and-secret-swap-protocol"),
    opp("backpack-securities-tokenized-equity", "BP", "BP：维持 10（ssp=2）", "本期无新信息，不编造进展。BP $1.26（24h **-13.32%**）——创历史新高后连续第 3 期回吐，「年度最重要发布」至今第 7 期仍无日期。", "yellow", 4, 3, 1, 2, "tracking", "2026-09-21", 8, 2, "https://coinmarketcap.com/cmc-ai/backpack-exchange/latest-updates/"),
    opp("ethena-fee-switch-usde-threshold", "ENA", "ENA：维持 10（ssp=2）", "**扳机指标继续原地踏步：** USDe 流通 $49.03 亿（上期 $49.02 亿，基本持平），距 $75 亿门槛仍需 +53%。资金费率 +0.0035% 仍贴近零。10/2 Core Contributors 解锁剩 3 天。验证方式不变。", "green", 4, 2, 2, 2, "tracking", "2026-09-26", 3, 2, "https://cryptobriefing.com/ethena-ena-buyback-usde-supply-growth/"),
    opp("helium-city-carrier-adoption", "HNT", "HNT：维持 stale（ssp=18）", "本期无新信息，不编造进展。", "yellow", 3, 3, 2, 2, "stale", "2026-08-31_daily", 23, 18, "https://en.coinotag.com/helium-hnt-short-squeeze-170-percent-surge"),
    opp("lisk-chain-sunset-supply-burn", "LSK", "LSK：维持 stale（ssp=10）", "本期无新信息，不编造进展。", "green", 4, 4, 1, 1, "stale", "2026-09-14_daily", 15, 10, "https://www.coingecko.com/en/coins/lisk"),
    opp("near-etf-window-ai-l1", "NEAR", "NEAR：维持 10（ssp=4）", "本期无新增一手。两条压制未变：里程碑激励领取的供给侧压力；扩散度已耗尽（仍在热搜）。", "green", 3, 3, 2, 2, "tracking", "2026-09-15", 14, 4, "https://coinpedia.org/price-analysis/near-protocol-price-surges-80-in-a-week-can-the-breakout-push-near-toward-5/"),
    opp("pieverse-arc-mainnet-launchpad", "PIEVERSE", "PIEVERSE：维持 stale（ssp=6）", "本期无新信息，不编造进展。Arc 链 TVL $5.23 亿（+0.58%），上期 +7.04% 的反弹未延续也未逆转。", "yellow", 3, 3, 2, 2, "stale", "2026-09-22_daily", 7, 6, "https://coinmarketcap.com/cmc-ai/pieverse/latest-updates/"),
    opp("monero-thorchain-native-swaps", "XMR", "XMR：维持 stale（ssp=19）", "本期无新信息，不编造进展。", "yellow", 3, 2, 3, 2, "stale", "2026-09-01_daily", 22, 19, "https://en.coinotag.com/monero-xmr-nears-520-thorchain-upgrade-rally"),
]

events = [
    {"id": "falcon-finance-unlock-20260929", "coin": "FF", "event_type": "unlock", "date": "2026-09-29", "days_away": 0, "description": "⏰**今天。** tokenomist FF 页面显示下一次解锁为 2026-09-29，分配类别 Ecosystems (Remaining)；数量与金额该页未显示，写 null。媒体口径 7,714 万枚 FF / 约 $955 万 / 占总量 0.77%（未经一手复核）。截至本期采集时（04:00 UTC+8）尚无执行后价格反应可读。", "opportunity_angle": "解锁前避险 vs 解锁后企稳吸筹。观察角度：若今日不再下跌，则抛压已被提前消化。", "source_url": "https://www.coingabbar.com/en/price-prediction/ff-price-prediction-2026-falcon-finance-outlook", "status": "upcoming"},
    {"id": "collector-crypt-unlock-20260929", "coin": "CARDS", "event_type": "unlock", "date": "2026-09-29", "days_away": 0, "description": "⏰**今天。** tokenomist 一手：\"The next unlock for Collector Crypt is scheduled for September 29, 2026. Released to Advisors.\"，数量未给出，写 null。媒体口径约 5,926 万枚 / 占总量 3.0%（未一手复核）。", "opportunity_angle": "用 XPL 样本检验「薄盘币解锁提前定价」是否可复制：今日之后价格企稳 = 可复制的形态；大跌 = XPL 是特例。", "source_url": "https://tokenomist.ai/collector-crypt", "status": "upcoming"},
    {"id": "coti-v1-sunset-20260930", "coin": "COTI", "event_type": "upgrade", "date": "2026-09-30", "days_away": 1, "description": "⏰**明天。** COTI V1 → V2 迁移截止日，V1 与 gCOTI V1 于 Q3 末日落。交易所持有者与 ERC-20 持有者无需操作；VIPER/Ledger 原生持有者须手动迁移。", "opportunity_angle": "迁移完成后的销毁执行是论点核心。⚠️COTI 连续多期不在前 250 币池，即使兑现也缺乏观测链路。", "source_url": "https://cotinetwork.medium.com/sunset-of-coti-v1-essential-steps-to-secure-your-v2-tokens-5f33ff3e07f2", "status": "upcoming"},
    {"id": "macro-pce-20260930", "coin": "MACRO", "event_type": "macro", "date": "2026-09-30", "days_away": 1, "description": "⏰**明天。** 美国个人收入与 PCE 平减指数（美东 08:30）。⚠️来源为经济日历聚合站、非 BEA 一手页面，只作日期标记，不引用预期数值，不计入宏观面评分。", "opportunity_angle": "方向未知 → 不构成可操作角度，只作为波动日标记。", "source_url": "https://fedratecalc.com/economic-calendar-this-week/", "status": "upcoming"},
    {"id": "venice-emission-cut2-20261001", "coin": "VVV", "event_type": "upgrade", "date": "2026-10-01", "days_away": 2, "description": "VVV 年排放 250 万→200 万第二阶段削减——第一刀已确认执行，第二刀为通缩路径验证点。", "opportunity_angle": "供给侧确定性事件。10/1 是 VVV 条目能否从 stale 回到 tracking 的唯一判据。", "source_url": None, "status": "upcoming"},
    {"id": "ethena-unlock-20261002", "coin": "ENA", "event_type": "unlock", "date": "2026-10-02", "days_away": 3, "description": "tokenomist 一手：\"The next unlock for Ethena is scheduled for October 2, 2026. Released to Core Contributors.\"，数量未提供，写 null。背景：早期投资人已被买断并删除投资人解锁日历，本次为 Core Contributors 批次。", "opportunity_angle": "解锁后吸筹比解锁前抢跑更有意义。真正的观测指标是 USDe 流通供应（当前 $49.03 亿 / 门槛 $75 亿）。", "source_url": "https://tokenomist.ai/ethena", "status": "upcoming"},
    {"id": "filecoin-vesting-end-20261015", "coin": "FIL", "event_type": "unlock", "date": "2026-10-15", "days_away": 16, "description": "Filecoin vesting 终止日（官方 X 一手）：Protocol Labs 与 Filecoin Foundation 归属结束。可验算口径：vesting 年释放约 6,670 万 FIL，区块奖励约 2,170 万 FIL，与「gross issuance 削减约 75%」自洽。", "opportunity_angle": "本期研究优先级第一。供给侧削减有硬日期、可提前验算。验证：归属结束的链上确认 + FIP-0118（Solstice）排入哪次网络升级。", "source_url": "https://en.bloomingbit.io/feed/news/119735", "status": "upcoming"},
    {"id": "arbitrum-unlock-20261016", "coin": "ARB", "event_type": "unlock", "date": "2026-10-16", "days_away": 17, "description": "tokenomist ARB 页面仍只展示 2026-07-15 的历史批次详情，下一笔 10-16 的枚数、金额与占比未列出，数值字段留空。", "opportunity_angle": "解锁前避险。金额未知本身是风险——无法提前量化压力。", "source_url": "https://tokenomist.ai/arbitrum", "status": "upcoming"},
    {"id": "cme-bch-uni-futures-20261019", "coin": "BCH/UNI", "event_type": "listing", "date": "2026-10-19", "days_away": 20, "description": "CME Group 9/22 官方新闻稿：计划 10/19 上线 BCH 与 UNI 期货（pending regulatory review）。合约规格：BCH 250 BCH/张、微型 25 BCH/张；UNI 10,000 UNI/张、微型 1,000 UNI/张。", "opportunity_angle": "准入型催化剂，不是需求型催化剂——同样首次为机构提供受监管的做空工具。⚠️唯一不确定项是 pending regulatory review。", "source_url": "https://www.prnewswire.com/news-releases/cme-group-to-expand-crypto-derivatives-suite-with-bitcoin-cash-and-uniswap-futures-302886066.html", "status": "upcoming"},
    {"id": "lisk-migration-deadline-20261021", "coin": "LSK", "event_type": "unlock", "date": "2026-10-21", "days_away": 22, "description": "LSK 跨链迁移截止日：持币人须经 Superbridge 或 Lisk Bridge 将 LSK 迁至以太坊。", "opportunity_angle": "未迁移部分构成永久性供给缩减，但 9 月那波 +538% 的主体已验证为清算而非重定价。LSK 已跌出前 250 币池。", "source_url": None, "status": "upcoming"},
    {"id": "meteora-unlock-20261023", "coin": "MET", "event_type": "unlock", "date": "2026-10-23", "days_away": 24, "description": "tokenomist 一手：下一次解锁 2026-10-23，分配类别 Meteora Ecosystem Reserve；数量、金额、占比未显示 → 全部写 null。", "opportunity_angle": "定义 MET 时间窗上限。⚠️9/28 不完整日收入仅 $36,246，若确认整日 <$10 万则降级倒计时开始。", "source_url": "https://tokenomist.ai/meteora", "status": "upcoming"},
    {"id": "macro-fomc-20261028", "coin": "MACRO", "event_type": "macro", "date": "2026-10-28", "days_away": 29, "description": "下次 FOMC 决议（10/27-28 会议，美东 10/28 14:00 公布）。9/16 已以 12-0 一致票加息 25bp 至 3.75%-4.00%；点阵图显示多数委员预期年内仍需再加一次。", "opportunity_angle": "宏观面唯一的高确定性事件。距离 29 天，对 1-4 周时间窗的机会不构成直接约束。", "source_url": None, "status": "upcoming"},
    {"id": "lisk-chain-shutdown-20261031", "coin": "LSK", "event_type": "upgrade", "date": "2026-10-31", "days_away": 32, "description": "Lisk Chain 正式关停（运行 10 年后），项目转型为以太坊/Base 上的企业财资管理平台。", "opportunity_angle": "供给侧终局事件，但流动性已不支持研究投入。", "source_url": None, "status": "upcoming"},
    {"id": "bitget-japan-exit-20261101", "coin": "CEX", "event_type": "listing", "date": "2026-11-01", "days_away": 33, "description": "Bitget 停止接受新日本用户，存量账户 11/1 起转只可平仓（沿用记录）。", "opportunity_angle": "与 BitMEX/CoinEx 同属交易所地域性收缩序列。", "source_url": None, "status": "upcoming"},
]

latest = {
    "timestamp": "2026-09-29T04:05:00+08:00",
    "session": "daily",
    "market_scan": {
        "movers": movers,
        "movers_narrative": "本期距上期仅约 4.5 小时（昨夜补跑一期），格局延续：广度 18.2%（187 池中 34 涨）连续第 2 期低于 20%。正向异动仍是 QNT（Sibos 第二日，+29.70%）与 HBAR（连续第 2 日大涨、原因未明）；回吐名单扩大到 ZRO（-10.06%，有 9 月下旬解锁报道背景）与 USELESS（-19.20%，本期最大跌幅）。上期预警的三条收入型条目本期等数据：STONK 9/28 整日未出炉、MET 9/28 不完整日仅 $36,246、RAY 9/28 不完整日已超昨日全天。",
        "breadth": C["breadth"],
        "sector_rotation": [{**s, "note": "24h 变化数据缺失"} for s in C["sector_rotation"]],
        "sector_note": "CoinGecko categories 连续第 2 期未返回 24h 市值变化，trend_sessions 全部维持 1，无轮动信号可确认。",
        "trending": C["trending"],
        "trending_note": "热搜延续机构叙事 + 隐私双线：QNT、HBAR 在榜，FIRO 连续第 2 期居前；新面孔 BABYCALI、PONS、XDC、BUN 均为薄盘/小众币。STONK 掉出热搜。",
        "chains_tvl_delta": C["chains_tvl_delta"],
    },
    "opportunities": opps,
    "priority": [
        {"action": "high", "coin": "STONK", "headline": "等 9/28 整日收入数据出炉——判决日", "body": "9/27 已跌至 $52.9 万（两日 -44%），9/28 整日数据本期尚未产生。若 <$50 万则「连续 3 日」倒计时第 1 天开始；价格已抢先下行（7d -36%）。"},
        {"action": "high", "coin": "MET", "headline": "9/28 不完整日收入仅 $36,246，按速率全天约 $4.3 万", "body": "若明日确认 9/28 整日 <$10 万，降级倒计时开始。10/23 解锁前 24 天，收入判据比价格更接近触发。"},
        {"action": "high", "coin": "FIL", "headline": "10/15 归属结束剩 16 天", "body": "供给侧削减可提前验算（vesting 年释放约 6,670 万 FIL 终止）。条目虽 stale，事件是未来 4 周最硬的供给侧催化剂。"},
        {"action": "medium", "coin": "QNT", "headline": "Sibos 第二日，7d +261% 后只看 10/1 闭幕后的量能", "body": "今日还有一场 panel。不追价格；闭幕后一周内缩量回落 = sell-the-news 确认。"},
        {"action": "watch", "coin": "HBAR", "headline": "连续 2 日累计约 +60%、量能 $12.86 亿，主因仍未明", "body": "可查背景（Docs MCP 服务器）与涨幅量级不匹配。若出现一手催化剂再评估是否建条目。"},
        {"action": "watch", "coin": "FF/CARDS", "headline": "两笔解锁今天到期", "body": "用 XPL 样本检验「薄盘币解锁提前定价」：今日不跌 = 抛压已消化；大跌 = XPL 是特例。"},
    ],
    "board_note": "状态流转：UNI tracking→stale（ssp=5 机械降级，CME 10/19 事件仍在日历中）；本期无新发现机会。本期距上期仅约 4.5 小时，绝大多数条目无新信息属预期。",
    "events": events,
    "events_note": "FF 与 CARDS 两笔解锁今日到期（截至 04:00 UTC+8 尚无执行后价格反应）；明天 COTI V1 日落 + PCE。上期两个 d=0 事件已结算（QNT 演示兑现 / SOL Alpenglow 日期证伪），详见上期报告。",
    "market_context": {
        "btc": {
            "price_usd": btc["price_usd"], "price_change_24h": btc["price_change_24h"],
            "price_change_7d": btc["price_change_7d"], "fear_greed": btc["fear_greed"],
            "fear_greed_label": btc["fear_greed_label"], "mvrv_ratio": btc["mvrv_ratio"],
            "mvrv_data_time": btc["mvrv_data_time"], "funding_rate": btc["funding_rate"],
            "open_interest": btc["open_interest"], "dominance": btc["dominance"],
            "dominance_change_pp": btc["dominance_change_pp"], "sparkline_7d": btc["sparkline_7d"],
            "support": btc["support"], "resistance": btc["resistance"],
            "trend": "偏弱整理（7d -3.12%，区间分位约 16%，$82,630 支撑第 2 期守住）",
            "signals": {
                "price": "7d -3.12%，区间分位约 16%",
                "fgi": "74 Greed（连续 2 期不变）",
                "dominance": "58.28%（+0.02pp），横盘",
                "support": "$82,630 第 2 期守住",
                "resistance": "$87,158",
            },
        },
        "macro": {
            "fomc_date": "2026-10-28", "fomc_days_away": 29,
            "note": "宏观面连续第 9 期无新增制度性变量。9/30 PCE（明天）仍只作日期标记、不计分；本周五非农（媒体口径）。下次 FOMC 10/27–28（29 天后）。Sibos 2026 进行中（9/28–10/1），按市场基础设施处理、不计分。",
        },
        "etf_qualitative": {
            "btc_etf_flow_text": "数据暂缺（无免费日度 API）",
            "eth_etf_flow_text": "数据暂缺（无免费日度 API）",
        },
        "eth": {"price_usd": eth["price_usd"], "price_change_24h": eth["price_change_24h"],
                "price_change_7d": eth["price_change_7d"], "eth_btc_ratio": eth["eth_btc_ratio"]},
        "cycle_notes": {
            "mvrv": "1.576（数据时间 9/27），连续 2 期数值不变——CoinMetrics 日更口径，下期若仍不变将触发新鲜度标注",
            "funding": "+0.0035%（上期 +0.0062%），继续贴近零",
            "oi": "$77.41 亿，连续第 5 期下降（-1.7%），去杠杆已出清",
            "stablecoin": "总供应 $3,133.14 亿，环比 +0.09%——上期 +2.22% 的脉冲未延续，回到持平",
            "eth": "ETH $2,674.41（24h -0.62%、7d -3.01%），ETH/BTC 0.0321，无山寨季信号",
        },
        "analysis_note": "本期是昨夜补跑后 4.5 小时的常规期，市场结构无实质变化：BTC 在 $82,630 支撑上方第 2 期企稳，广度连续 2 期低于 20%，OI 连续 5 期下降。真正的信息增量在收入型条目：MET 9/28 不完整日收入仅 $36,246（预警升级），RAY 初步企稳，STONK 等数据。无持仓视角不变：等判据给出答案，不主动出手。",
        "global": {
            "total_market_cap_usd": glob["total_market_cap_usd"],
            "stablecoin_total_supply": glob["stablecoin_total_supply"],
            "stablecoin_supply_change_pct": glob["stablecoin_supply_change_pct"],
            "usde_circulating": glob["usde_circulating"],
        },
    },
    "market_score": {
        "btc_trend": 3, "funding": 3, "sentiment": 3, "macro": 3, "total": 12,
        "label": "偏多（12→12：四栏全部不变）",
        "vs_previous": "**12 → 12（0）。四栏全部不变，本期距上期仅约 4.5 小时，零变动属预期。**\n**BTC 趋势维持 3：** 7d -3.12%，现价 $83,370 处于 7d 区间（$82,630–$87,158）约 16% 分位——较上期 6% 略有抬升，$82,630 支撑第 2 期守住，但远未到恢复 4 的程度。\n**资金面维持 3：** 稳定币供应 +0.09%（上期 +2.22% 的脉冲未延续）；主力链 TVL 美元口径多数小幅转正（ETH +0.50% / SOL +0.39% / Base +0.67%），但升级条件（Solana 代币计价转正 + 稳定币 >+0.20%）仍只满足一半。\n**情绪面维持 3：** 广度 18.2% 连续第 2 期低于 20%；FGI 74 连续 2 期不变（新鲜度计数 2，下期若不变将标注）。\n**宏观面维持 3：** 连续第 9 期无制度性新变量；PCE 明天，仅日期标记。",
    },
    "watchlist": {},
    "alerts": [
        {"severity": "warning", "rule": "large_cap_mover", "message": "QNT 24h 变动 +29.70%（市值 $35.05 亿），进入异动关注"},
        {"severity": "warning", "rule": "large_cap_mover", "message": "HBAR 24h 变动 +28.25%（市值 $53.32 亿），进入异动关注"},
        {"severity": "warning", "rule": "large_cap_mover", "message": "MARSCOIN 24h 变动 +24.34%（市值 $1.58 亿），进入异动关注"},
        {"severity": "warning", "rule": "large_cap_mover", "message": "USELESS 24h 变动 -19.20%（市值 $2.39 亿），进入异动关注"},
        {"severity": "warning", "rule": "event_within_48h", "message": "⏰ 事件临近：FF unlock（2026-09-29）— 今天，tokenomist 一手确认日期，数量 null"},
        {"severity": "warning", "rule": "event_within_48h", "message": "⏰ 事件临近：CARDS unlock（2026-09-29）— 今天，tokenomist 一手确认日期（Advisors 批次），数量 null"},
        {"severity": "warning", "rule": "event_within_48h", "message": "⏰ 事件临近：COTI upgrade（2026-09-30）— 明天，V1 → V2 迁移截止"},
        {"severity": "warning", "rule": "event_within_48h", "message": "⏰ 事件临近：MACRO macro（2026-09-30）— 明天，美国 PCE 平减指数（日期标记）"},
    ],
    "_sources": C["_sources"],
    "_freshness": C["freshness"],
}

json.dump(latest, open("data/latest.json", "w"), ensure_ascii=False, indent=1)
print("latest.json written, opps:", len(opps), "events:", len(events))
