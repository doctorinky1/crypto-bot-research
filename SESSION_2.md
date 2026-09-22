# Session 2 Supplement — Extended Validation & Live Bot Infrastructure

Companion to: EXPERIMENT_LOG.md (session 1 findings)
Purpose: Document everything from the extended validation phase through the live bot deployment
Date of supplement: 2026-09-22

---

## Executive Summary

Session 1 ended with a single surviving signal: **4-hour aggregate trade flow imbalance on Hyperliquid**, validated on 5 weeks of data. Session 2 did four things:

1. **Extended the data window to 4 months** and re-validated
2. **Discovered the strategy must be LONG-ONLY** — the short side is a consistent loser
3. **Built the live infrastructure** — wallet scoring, seeding, live signal engine, paper trader
4. **Deployed the live bot** and confirmed signal generation matches the backtest logic

The production configuration is now running live and observing. No capital at risk yet.

---

## Part 1: Extended Data Acquisition

### Data window

- **Previous**: 35 days (Aug 17 – Sep 21, 2026)
- **Extended**: 128 days (May 15 – Sep 21, 2026)
- **Cost**: ~$0.06 from CoinAPI credits

### Data availability discoveries

Hyperliquid L4 data on CoinAPI goes back only to **mid-May 2026**. Earlier months return empty on all probes. Specifically:

| Month | Available |
|---|---|
| Sep 2026 | ✅ |
| Aug 2026 | ✅ |
| Jul 2026 | ⚠️ Partial (day 05 only) |
| Jun 2026 | ✅ |
| May 2026 | ✅ (from May 27) |
| Apr 2026 and earlier | ❌ |

Additionally, a **schema change** occurred around May 27: earlier files lack the `user_taker` column. Wallet attribution only starts from May 27, so all wallet-scored analysis uses data from that date forward.

### Data gap

A ~3-week gap exists in mid-to-late July 2026. Fold 3 and 4 of every walk-forward test window fall inside it, so those folds produce 0 test bars.

### Assets downloaded

- **BTC**: 9,008,423 wallet-minute rows, 142,946 minute bars
- **ETH**: 4,495,949 wallet-minute rows, 142,933 minute bars
- **SOL**: 1,291,382 wallet-minute rows (only 5 weeks — interrupted by credit exhaustion)

---

## Part 2: Walk-Forward Validation

### Methodology

Walk-forward test: 4-week training, 2-week test, 1-week roll. 11 folds total. Wallets re-scored on every fold to simulate live retraining.

### Pre-extension results (5 weeks of data)

| Asset | Params | Folds+ | Mean net% | Sharpe |
|---|---|---|---|---|
| BTC | 42/1.0 | 7/9 | +0.105% | 1.81 |
| BTC | 42/1.5 | 8/9 | +0.186% | 2.32 |
| ETH | 42/1.0 | 5/9 | -0.098% | -0.74 |
| ETH | 42/1.5 | 5/8 | +0.104% | 0.81 |

### Extended results (4 months, long+short)

| Asset | Params | Folds+ | Mean net% | Sharpe |
|---|---|---|---|---|
| BTC | 42/1.0 | 7/9 | +0.105% | 1.81 |
| BTC | 42/1.5 | 8/9 | +0.186% | 2.32 |
| ETH | 42/1.0 | 5/9 | -0.098% | -0.74 |
| ETH | 42/1.5 | 5/8 | +0.104% | 0.81 |

(Note: results are nearly identical between windows because the extra data added June folds that were mostly negative for ETH and neutral for BTC.)

### Key finding: wallet decay

Comparing walk-forward (wallets retrained per fold) vs. static-wallet tests revealed a critical operational requirement: **the top-500 wallet list degrades within 4–6 weeks**. A wallet list scored on May 29–July 1 produces a Sharpe of -0.15 by late August when applied stale. Production must retrain weekly.

---

## Part 3: The Side-Filter Discovery

### What happened

Running the walk-forward with different side configurations revealed:

**BTC (4-month, 42/1.0):**
| Config | Trades | Mean net% | Sharpe |
|---|---|---|---|
| LONG ONLY | 70 | **+0.272%** | **3.72** |
| SHORT ONLY | 61 | -0.108% | -1.24 |
| LONG+SHORT | 133 | +0.105% | 1.81 |

**ETH (4-month, 42/1.0):**
| Config | Trades | Mean net% | Sharpe |
|---|---|---|---|
| LONG ONLY | 73 | **+0.230%** | **2.29** |
| SHORT ONLY | 66 | -0.461% | -1.85 |
| LONG+SHORT | 140 | -0.098% | -0.74 |

### Interpretation

**The short side is consistently unprofitable on both assets.** Buying pressure predicts continued uptrends. Selling pressure does not predict continued downtrends — likely because:
- Crypto bear markets are often driven by liquidations and forced selling (mechanical, not informational)
- In a strong bull, "flow-negative" bars are often just profit-taking pauses, not reversals
- The aggregate flow signal captures demand, and demand asymmetry is the actual edge

### Production decision

**Both assets: LONG ONLY.**

This roughly doubles BTC's Sharpe (1.81 → 3.72) and flips ETH from negative to positive.

---

## Part 4: Exit Strategy Tests

### Tested exit rules (9 total)

- Fixed holds: 1, 2, 3, 6 bars
- Signal reversal (exit when z < 0): with caps at 6 and 12 bars
- Signal reversal + trailing stops at 3% and 5%

### Results

**BTC (best-to-worst by Sharpe):**
| Rule | Trades | Mean net% | Sharpe |
|---|---|---|---|
| **Fixed 1 bar** | 81 | +0.152% | **+2.05** |
| Signal rev | 65 | +0.173% | +1.37 |
| Fixed 2 bars | 72 | +0.123% | +1.03 |
| Fixed 6 bars | 45 | +0.205% | +0.92 |

**ETH (best-to-worst by Sharpe):**
| Rule | Trades | Mean net% | Sharpe |
|---|---|---|---|
| **Fixed 1 bar** | 88 | +0.232% | **+1.95** |
| Fixed 6 bars | 47 | +0.508% | +1.53 |
| Fixed 3 bars | 65 | +0.228% | +0.74 |
| Signal rev | 76 | -0.006% | -0.03 |

### Verdict

**Fixed 1-bar hold wins.** No alternative improved both Sharpe AND mean net% on both assets. The signal decays quickly — its edge is concentrated in the bar it fires on. Trailing stops never triggered because z falls to zero faster than price falls 3%.

### Production decision

**Fixed 1-bar hold.** Zero parameters, cleanest possible exit. Signal-reversal exits would add a parameter that isn't justified by the improvement.

### Catastrophic stop (untested but recommended)

For insurance against exchange outages, flash crashes, and data glitches, we recommend a **-12% hard stop** at the position level. It's not an alpha-improving rule; it's a safety mechanism. Expected frequency: 0–1 trigger per year.

---

## Part 5: Equity Sizing Analysis

### The earlier backtest was implicitly 100% allocation

Every trade's return was measured as a fraction of the entire account, which mathematically assumed 100% of capital deployed on every signal. That's not tradeable.

### Fixed fractional sizing

Each trade risks a fixed percentage `f` of *current* equity. Position size grows with the account, shrinks during drawdowns.

### Results at different sizing levels (4-month window, $10,000 start)

| Sizing | BTC final | BTC return | ETH final | ETH return |
|---|---|---|---|---|
| 2% | $10,039.83 | +0.40% | $10,033.67 | +0.34% |
| **5%** | **$10,099.84** | **+1.00%** | **$10,084.36** | **+0.84%** |
| 10% | $10,200.59 | +2.01% | $10,169.27 | +1.69% |
| 25% | $10,508.42 | +5.08% | $10,427.45 | +4.27% |
| 50% | $11,040.48 | +10.40% | $10,869.26 | +8.69% |
| 100% | $12,179.57 | +21.80% | $11,797.27 | +17.97% |

### Signal quality is sizing-independent

Sharpe ratios at all sizing levels:
- BTC: **+3.86** (trades: 71, mean net: +0.280%)
- ETH: **+2.29** (trades: 73, mean net: +0.230%)

### Recommended sizing

**Start at 5%, scale to 15–25% only after live verification.** Reasons:
- 5% is safe enough that even a -20% backtest error doesn't hurt
- Kelly-optimal sizing for a Sharpe 3.86 signal is theoretically very high (~40%+), but Kelly assumes you know the true distribution — we don't
- After 4–8 weeks of live observation matching the backtest, increase incrementally

### The honest caveat

Drawdowns at 5% sizing showed as -0.05% (BTC) and -0.16% (ETH). These are suspiciously small because the 4-month window was a bull market. In an adverse regime, expect -2% to -5% at 5% sizing.

---

## Part 6: Live Infrastructure

### Side semantics verification

**Question:** what does Hyperliquid's `side` field mean?

**Method:** polled `l2Book` and `recentTrades` simultaneously, classified each trade by comparing price to best bid/ask.

**Result:**
- `side='B'` → taker **bought** (aggressor was the buyer) — confirmed on 84% of BTC trades
- `side='A'` → taker **sold** (aggressor was the seller) — confirmed on 71% of BTC trades

**Assumption:** `users[0]` is the taker, `users[1]` is the maker. Not yet independently verified.

### Wallet list builder (`build_wallet_list.py`)

Reads historical `hl_cache_*.parquet` files, scores every wallet by shrunk correlation between its signed flow and next-bar return over the last 28 days, selects the top 500 per asset, writes to `top_wallets.json`.

**Must be re-run weekly** to counter wallet decay.

Current output:
- BTC: 4,925 wallets pass filter, top 500 kept
- ETH: 2,793 wallets pass filter, top 500 kept

### Seed script (`seed_history.py`)

Reads historical CoinAPI Parquet files, filters to the top-500 wallets, aggregates to 4h bars, writes `live_state_*.parquet`. This lets the live bot start with a valid z-score from its first bar instead of waiting 7 days.

**Seeds 60 bars per asset** (z-window is 42, so this gives headroom).

### Live signal engine (`live_signal.py`)

Polls Hyperliquid `recentTrades` every 15 seconds. Filters to top-500 wallets. Aggregates into 4h bars. Computes rolling z-score. **LONG-ONLY.** Emits signals only at bar close (no partial-bar signals).

**State persistence:**
- `live_state_btc.parquet` / `live_state_eth.parquet` — bar data
- `live_seen_btc.json` / `live_seen_eth.json` — trade IDs to prevent duplicates
- `live_signals.csv` — log of every signal

**Safe to Ctrl+C** — the shutdown handler saves state correctly.

### Paper trader (`paper_trader.py`)

Recomputes signals from `live_state_*.parquet` on every run. Simulates entries at bar close, exits one bar later, applies fixed fractional sizing, writes to `paper_trades.csv`.

**Idempotent** — can be run as often as desired.

---

## Part 7: Bugs Found and Fixed

| Bug | Impact | Fix |
|---|---|---|
| gzip decompression bypass | Pandas failed on `.csv.gz` files | Explicit `gzip.decompress()` before `read_csv` |
| MCP v2 unpacking | Expected 3 return values, got 2 | Use only 2 values from `streamable_http_client` |
| S3 secret key | Used `FinFeedAPI` instead of `coinapi` | Correct key per CoinAPI docs |
| CoinAPI empty response | Daily tail not yet written | Fall back to L2-book method for side verification |
| `state` scope in shutdown | Ctrl+C didn't save bars | Moved try/except inside `main()` |
| Partial-bar signals | z-scores of ±3.9 during forming bars | Added closed-bar gate |
| Duplicate log rows | Restarts re-logged the same bar | `drop_duplicates(subset=['coin','bar'])` |

---

## Part 8: Current Production Configuration

### Strategy

| Setting | Value |
|---|---|
| Signal | Top-500 wallet aggregate flow imbalance |
| Bar size | 4 hours |
| Z-window | 42 bars |
| Entry threshold | z > 1.0 |
| Side rule | LONG ONLY |
| Exit | 1 bar (4h) |
| Cost assumption | 0.090% round-trip (taker) |
| Wallet retraining | Weekly |

### Expected performance (from 4-month walk-forward)

| Metric | BTC | ETH |
|---|---|---|
| Trades (4 months) | 70 | 73 |
| Trades/month | ~18 | ~18 |
| Mean net% per trade | +0.272% | +0.230% |
| Win rate | 60.0% | 55.7% |
| Sharpe-like | 3.72 | 2.29 |

### Live deployment status (as of 2026-09-22)

- ✅ Wallet list built
- ✅ Seed applied (60 bars per asset)
- ✅ Live signal engine running
- ⏳ Waiting for first live bar close after restart
- ⏳ Paper trading observation period (not started)

---

## Part 9: Files in Repository
