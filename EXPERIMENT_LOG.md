# Automated Crypto Trading Bot — Complete Experiment Log

Author: Allen
Collaborator: AI assistant (DeepSeek)
Period: ~2 weeks of iterative research
Objective: Build an automated crypto trading bot with a genuine, statistically-validated edge

---

## Part 1: Project Origin and Initial Plan

The project began with the goal of building a regime-aware multi-bot system — a central orchestrator that detects market regime (trend vs. range vs. high-volatility) and dispatches the appropriate specialized bot. The initial plan was laid out in phases:

- Phase 0: Infrastructure — exchange API, order execution, state DB, logging, reconciliation
- Phase 1: Baseline EMA 50/200 bot, paper-traded
- Phase 2: Add regime detection layer (ADX + Bollinger bandwidth + ATR percentile)
- Phase 3: Transition buffer and orchestration across bots
- Phase 4: Drift detection and model retraining (deleted later)
- Phase 5: Live deployment with small capital

The plan was revised after a critique that correctly identified: Phase 4 had nothing to attach to (no ML model), Phase 2's verify criterion was statistically unsatisfiable at small sample sizes, and the phase timelines were arithmetically impossible. A realistic total was estimated at 4–6 months rather than 8 weeks.

A decision was made early to abandon GunBot (known bugs, unreliable) and to pursue a semi-automated path using Altrady's MCP server rather than building a fully autonomous trading system from scratch.

---

## Part 2: Infrastructure Built

### Altrady MCP Integration

A working Python client was built to connect to Altrady's local MCP server. Key technical facts discovered:

- MCP server runs locally inside the Altrady desktop app at http://127.0.0.1:6850/mcp
- Transport is streamable_http_client (MCP v2), not the older sse_client or streamablehttp_client
- Requires both application/json and text/event-stream in the Accept header
- Authentication via Authorization: Bearer <token> header
- Exposes 60+ tools for reading market data, positions, bots, charts, alerts, and staging trades

Critical architectural constraint: Altrady MCP never places orders autonomously. Every trade-relevant tool loads a setup into the UI and requires a manual click to confirm. True autonomy requires bypassing Altrady MCP and building a direct exchange API execution layer.

### Data Pipeline

For signal research, a data pipeline was built around CoinAPI's Flat Files S3 API (same parent company as FinFeedAPI, APIBricks):

- Endpoint: https://s3.flatfiles.coinapi.io
- Auth: API key as Access Key ID, "coinapi" as static Secret Access Key
- Data buckets: coinapi, coinapi-daily-tail, coinapi-indexes

Three datasets were used:

| Dataset | What it contains | Format |
|---|---|---|
| T-LIMITBOOK_FULL | Full-depth L2 order book snapshots | CSV, gzip, ~100ms cadence |
| T-TRADES | Every executed trade, tick-level | CSV, gzip |
| Hyperliquid L4 (T-TRADES/E-HYPERLIQUIDL4/) | Executed trades WITH wallet addresses | CSV, gzip |

Hyperliquid L4 was the gold-standard dataset because it uniquely includes user_taker and user_maker wallet addresses on every trade.

---

## Part 3: Every Strategy Tested, In Order

### Strategy 1: 50/200 EMA Crossover

Setup: EMA(50) and EMA(200) on close, long when 50 crosses above 200, exit when 50 crosses below.

Cost model: 0.240% round-trip (retail spot fees 0.14% + slippage 0.10%)

Results:

| Timeframe | Period | Trades | Win rate | Avg net/trade | Cumulative |
|---|---|---|---|---|---|
| BTC/USDT 4h | 24 months | 11 | 27.3% | -0.268% | -5.70% vs B&H +26.27% |
| BTC/USDT 1h | 24 months | 56 | 30.4% | -0.027% | -9.40% vs B&H +29.54% |

Interpretation: 4h had no raw edge at all. 1h had a small real raw edge (~+0.213% before costs) but not enough to overcome fees.

Verdict: DEAD.

---

### Strategy 2: 50/200 EMA + ADX Regime Filter

Setup: Same crossover, but only take trades when ADX exceeds various thresholds.

Results (BTC/USDT 1h):
- Avg ADX of winners: 27.6
- Avg ADX of losers: 28.1

The two distributions were essentially identical. ADX did not separate winning from losing trades. The threshold sweep produced no monotonic improvement.

Verdict: Regime thesis not validated by ADX on this data.

---

### Strategy 3: Bollinger Band Mean Reversion

Setup: Long when close crosses below lower Bollinger Band (20, 2 sigma), exit when close crosses above middle band. Max hold 100 bars.

Results (BTC/USDT 1h, 24 months):

| Metric | Value |
|---|---|
| Trades | 339 |
| Win rate | 59.3% |
| Avg win | +0.69% net |
| Avg loss | -1.59% net |
| Avg net/trade | -0.236% |
| Cumulative | -57.31% vs B&H +29.54% |

High win rate, negative expectancy — classic "picking up pennies in front of a steamroller." Raw edge was effectively +0.004% — essentially zero.

Verdict: DEAD.

---

### Strategy 4: Volume-Based Signals (4 variants)

All four tested on BTC/USDT 1h, same cost model:

| Signal | n | Win% | Net/trade | Raw edge |
|---|---|---|---|---|
| VWAP reversion (2 sigma) | 147 | 55.1% | -0.018% | +0.222% |
| Volume spike continuation | 422 | 43.6% | -0.185% | +0.055% |
| OBV trend (EMA cross) | 1281 | 18.0% | -0.236% | +0.004% |
| MFI reversion | 163 | 52.1% | -0.189% | +0.051% |

Finding: VWAP reversion had the same ~+0.2% raw edge as the 1h EMA crossover — two independent signals hitting the same ceiling. Volume-based signals (spike, OBV, MFI) had no edge.

Verdict: All four dead at retail spot costs.

---

### Strategy 5: Order Book Imbalance / OFI

Data: Binance Spot and Binance Futures BTC/USDT T-LIMITBOOK_FULL L2 data, 7 days, ~2.3M rows/hour.

Signal: Top-10-level bid volume vs. ask volume, aggregated to 1-minute bars.

Results:

| Venue | Signal | Corr with next-min return |
|---|---|---|
| Binance Spot | Imbalance | -0.1143 (n=10,039) |
| Binance Spot | OFI change | -0.0795 |
| Binance Futures | Imbalance | -0.0101 |
| Binance Futures | OFI change | +0.0023 |

The spot signal showed a REVERSAL pattern (high imbalance -> negative next-minute return). This is a real microstructure effect but the reverse of what a naive momentum trader would expect.

Cost math: Signal predicts ~0.5 bp of next-minute return. Cost is 12–24 bp. Off by 20–40x.

Verdict: Book imbalance is an HFT signal, not retail-exploitable.

---

### Strategy 6: Trade Flow Imbalance

Data: Binance Spot and Binance Futures T-TRADES tick data, 7 days.

Signal: Aggressor volume imbalance = (buy_vol - sell_vol) / total_vol, aggregated to 1-minute bars.

Results:

| Venue | Signal | Corr with next-min return |
|---|---|---|
| Binance Spot | flow_imb | +0.3132 (n=10,079) |
| Binance Spot | signed_vol | +0.2203 |
| Binance Futures | flow_imb | +0.2909 (n=10,078) |
| Binance Futures | signed_vol | +0.2863 |

This was a genuine, large signal. Correlations of 0.29–0.31 on a financial time series are extraordinary.

But the horizon test showed the edge does not accumulate. Gross edge per trade at threshold |z|>1.0:

| Horizon | Spot gross% | Futures gross% |
|---|---|---|
| 1m | 0.0195% | 0.0186% |
| 5m | 0.0181% | 0.0165% |
| 30m | 0.0159% | 0.0088% |
| 60m | 0.0093% | 0.0049% |

The per-trade edge is flat at ~0.018% for 30 minutes, then decays. Round-trip cost is 0.24% (spot) or 0.12% (futures). Off by 7–13x.

Verdict: Real signal, still HFT territory.

---

### Strategy 7: Smart Money Wallet Filtering

Data: Hyperliquid L4 T-TRADES for BTC/USDC perp, 35 days. Every trade tagged with user_taker wallet.

Method:
- Train: score each wallet's flow predictiveness over week 1
- Test: evaluate on weeks 2–5 using only top-N wallets
- Shrinkage formula: score = corr * n / (n + 100) to punish thin samples

Results — test period correlations with next-minute return:

| Signal | Corr next-min |
|---|---|
| Aggregate (all wallets) | +0.1314 |
| Top 50 wallets | +0.1858 |
| Top 100 wallets | +0.1893 |
| Top 500 wallets | +0.1969 |

The filter worked — top-500 flow was 50% more predictive than the crowd, out-of-sample. This was genuine and remarkable.

However: When we ran the horizon test, the wallet filter's advantage disappeared at coarse bars. At 1h and 4h, top-500 flow was actually WORSE than aggregate flow. The wallets we identified were short-horizon scalpers, not directional bettors.

Verdict: Real finding (individual wallets have predictive skill), but not exploitable after costs at any horizon.

---

### Strategy 8: Coarse-Bar Aggregate Flow — THE ONE THAT WORKED

Data: Hyperliquid L4 trade flow, aggregated to 5min / 15min / 1h / 4h bars.

Signal: Aggregate flow imbalance z-scored over rolling 42-bar window. Long when z > 1, short when z < -1.

Initial results (BTC, 28-day test period):

| Bar | Aggregate corr | Aggregate gross% | Aggregate net% |
|---|---|---|---|
| 5m | +0.126 | +0.0185% | -0.0715% |
| 15m | +0.140 | +0.0331% | -0.0569% |
| 1h | +0.181 | +0.0757% | -0.0143% |
| 4h | +0.217 | +0.1354% | +0.0454% |

First positive net expectancy found in the entire project.

---

### Strategy 8 — Validation Across Assets

Reran the exact same test on ETH and SOL.

Test period results (out-of-sample, weeks 2–5):

| Asset | 1h agg_net% | 4h agg_net% | 4h n |
|---|---|---|---|
| BTC | -0.0143% | +0.0454% | 53 |
| ETH | +0.0121% | +0.2422% | 54 |
| SOL | +0.0396% | +0.3445% | 50 |

Every asset positive at 4h. Two of three positive at 1h.

Train period (BTC week 1, in-sample):

| Bar | agg_net% |
|---|---|
| 4h | +0.3833% (n=13) |

Consistent with test period, suggesting stability.

---

### Strategy 8 — Trend Control Regression

Question: Is the flow signal just riding a bull market?

Method: OLS regression next_return ~ flow_z + past_return on each asset x timeframe.

Results — flow_z coefficient p-values:

| Test | flow_z coef | p-value | past_ret coef | p-value |
|---|---|---|---|---|
| BTC @ 1h | +0.000544 | 0.0001 | +0.078244 | 0.0544 |
| BTC @ 4h | +0.000963 | 0.0439 | +0.164691 | 0.0426 |
| ETH @ 1h | +0.000580 | 0.0020 | +0.058129 | 0.1544 |
| ETH @ 4h | +0.001435 | 0.0307 | +0.048610 | 0.5466 |
| SOL @ 1h | +0.000630 | 0.0066 | +0.056708 | 0.1693 |
| SOL @ 4h | +0.001852 | 0.0239 | +0.238517 | 0.0026 |

Every flow_z coefficient is significant at p < 0.05. The signal has independent predictive power beyond trend-following.

UP/DOWN regime split (does it work in down bars?):

| Test | Up regime net% | Down regime net% |
|---|---|---|
| BTC @ 1h | +0.0138% | -0.0238% |
| BTC @ 4h | +0.1030% | +0.0753% |
| ETH @ 1h | +0.0228% | -0.0339% |
| ETH @ 4h | +0.0814% | +0.2425% |
| SOL @ 1h | +0.0973% | -0.0293% |
| SOL @ 4h | +0.3526% | +0.2579% |

At 4h, the signal works in BOTH up and down regimes across all three assets. At 1h, it's trend-dependent.

---

## Part 4: What We Have Learned

### Finding 1: Signals exist. Retail economics are the wall.

Every real signal we found had a raw edge of roughly 0.02–0.5% per trade. Retail spot fees (0.24% round-trip) and even Hyperliquid taker fees (0.09%) swallow edges smaller than ~0.1%.

### Finding 2: The edge lives at slow timescales, not fast ones.

Counterintuitively, the only positive edge we found was at 4-hour bars — the slowest timeframe we tested. The per-trade edge GROWS with bar size, because it accumulates directional pressure while the fixed cost stays the same. This is the opposite of where HFT operates.

### Finding 3: Wallet-level information is real but not exploitable at retail costs.

The top-500 Hyperliquid wallets were genuinely more predictive than the crowd at 1-minute bars (corr 0.197 vs. 0.131). But their alpha lived in microstructure and disappeared at coarse bars. Individual wallet tracking is a legitimate signal — but for a different venue and time-horizon than retail can access.

### Finding 4: The 4h aggregate flow signal is the only surviving candidate.

After testing 8 signal families across 4 timeframes and 3 assets, exactly one survived all tests:
- Positive net expectancy after costs (0.045–0.35%)
- Consistent across BTC, ETH, SOL
- Consistent between train and test periods
- Survives trend-control regression at p < 0.05
- Works in both up and down regimes at 4h

### Finding 5: The edge is fragile on sample size.

The 4h edge comes from 50–54 trades per asset over 28 days. That is a small sample. Standard error on the mean is roughly +/-0.03–0.04%. We cannot yet distinguish this with confidence from a lucky window, though the consistency across three assets helps.

### Finding 6: The single 28-day window is a bull market.

BTC +5%, ETH +7.6%, SOL +17% during the test period. No bear or sideways regime was sampled. This is the largest remaining unknown.

---

## Part 5: Scripts and Data Inventory

### Python scripts built (in C:\Users\Allen\Desktop\)

Altrady MCP integration:
- client.py — first successful MCP connection
- probe.py, probe2.py, probe3.py, probe4.py — schema discovery iterations
- backtest.py, backtest_1h.py, backtest_1h_adx.py, backtest_1h_mr.py, backtest_volume.py — EMA and volume backtests

CoinAPI data pipeline:
- coinapi_discover.py, coinapi_explore.py, coinapi_btc_probe.py, coinapi_probe2.py — bucket exploration
- coinapi_sample.py — first L2 download
- analyze_sample.py — schema analysis
- check_updates.py — L3 update semantics
- ofi_compute.py — first OFI calculation (single hour)
- pull_and_compute.py — batch L2 downloader
- ofi_backtest.py — first OFI economics test
- probe_trades.py — trade data schema discovery
- pull_trades.py — Binance trade data batch downloader
- trades_backtest.py — trade flow economics test
- horizon_test.py — multi-horizon edge test
- probe_hl.py, pull_hyperliquid.py, pull_hl_5weeks.py — Hyperliquid L4 pipeline
- smart_money.py — wallet scoring and smart-money test
- coarse_bars.py — coarse-bar aggregate flow test
- validate_edge.py — multi-asset validation
- trend_control.py — trend-control regression
- check_history.py — historical data availability check (in progress)

### Data files on disk

| File | Contents |
|---|---|
| btc_usdt_sample.csv | 1 hour of Binance L2 (decompressed) |
| ofi_spot.parquet / ofi_futures.parquet | 1 week Binance book OFI per minute |
| trades_spot.parquet / trades_futures.parquet | 1 week Binance trade flow per minute |
| hl_cache_btc_wallet.parquet / hl_cache_btc_minute.parquet | 5 weeks BTC Hyperliquid L4 |
| hl_cache_eth_wallet.parquet / hl_cache_eth_minute.parquet | 5 weeks ETH Hyperliquid L4 |
| hl_cache_sol_wallet.parquet / hl_cache_sol_minute.parquet | 5 weeks SOL Hyperliquid L4 |

### Cost accounting

Total data purchased from CoinAPI: roughly $1–2 across the entire project. The $32 credit is intact.

---

## Part 6: Open Questions

1. Does the 4h signal survive a bear market? 12+ months of historical data would answer this.
2. What is the earliest available Hyperliquid L4 data on CoinAPI? check_history.py is running.
3. Can maker orders reduce cost below the current 0.09% taker threshold? Hyperliquid maker fees are ~0.015% per side, ~0.03% round-trip. That would 3x the effective edge.
4. Is the 4h signal robust to parameter choices (z-score window, threshold, rolling window)? Deliberate robustness testing needed.
5. Would a portfolio of 4h signals across BTC, ETH, SOL have better risk-adjusted returns than any single asset?

---

## Part 7: Methodological Lessons

1. The economics check must come first. Before building any strategy, compute raw edge vs. round-trip cost. If the edge is smaller than the cost, the strategy is dead regardless of how pretty the backtest looks.

2. Sample size beats backtest Sharpe. A Sharpe of 3 on 15 trades is noise. A Sharpe of 0.5 on 5,000 trades is meaningful.

3. The threshold-sweep trap. If you test 20 thresholds and one works spectacularly, that's data mining, not discovery. Look for monotonic patterns, not single peaks.

4. HFT signals leak into retail datasets. Trade flow imbalance, order book imbalance, and wallet alpha all look like magic at 1-minute bars and evaporate at retail costs. This is the market being efficient.

5. Trend control is essential. Any directional signal in a bull market looks good. The OLS regression against past returns is the cheapest way to distinguish real alpha from trend-following.

6. Train/test split is non-negotiable. The wallet score test would have been meaningless without a proper time-based split. In-sample results are useless.

7. The edge rarely lives where you expect. The best signal in this project came from the coarsest timeframe we tested, in the least exotic data (aggregate flow), after every sophisticated alternative failed.

---

## Part 8: Current Status

As of last update: The 4h aggregate flow imbalance signal is the sole surviving candidate. It passed:
- Positive net expectancy after Hyperliquid taker costs
- Consistency across BTC, ETH, SOL in out-of-sample testing
- Regression significance at p < 0.05 controlling for trend
- Works in both up and down regimes at 4h

Pending:
- Historical data availability check (check_history.py running)
- Extension to a longer window covering multiple market regimes
- Robustness testing on parameters
- Live execution design (likely directly on Hyperliquid, bypassing Altrady MCP)

The project has moved from "no viable edge exists" to "one promising edge needs regime validation." That is a substantial change in position.

---

End of log.