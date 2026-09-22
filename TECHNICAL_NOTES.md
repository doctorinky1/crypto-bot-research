# Technical Companion — Automated Crypto Trading Bot

Companion to: EXPERIMENT_LOG.md
Purpose: Environment setup, schemas, constants, and code snippets needed to resume work

---

## Environment

- OS: Windows (HP ProDisplay, dedicated machine)
- Python: 3.14
- Shell: PowerShell
- Editor: VS Code
- Working directory: C:\Users\Allen\Desktop\

### Required packages

Install with:
    pip install mcp httpx pandas pyarrow boto3 statsmodels

Notes:
- The `mcp` package must be v2 or later (streamable_http_client API)
- Python 3.14 handles the MCP async code correctly

### Python version gotchas encountered

- `pip install mcp` fails silently on Windows if `Set-ExecutionPolicy` is Restrict
  Fix: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
- Node.js was installed via .msi, not Docker; Visual Studio Build Tools not required
- Python from python.org with "Add Python to PATH" checked is required
  (the py launcher does not always work)

---

## CoinAPI Authentication

- Parent company: APIBricks (same as FinFeedAPI)
- S3 endpoint: https://s3.flatfiles.coinapi.io
- Access Key ID: the API key from console.apibricks.io
- Secret Access Key: the literal string "coinapi"  (NOT "FinFeedAPI")
- Region: us-east-1
- Signature: s3v4

### Working boto3 pattern

    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        's3',
        aws_access_key_id=API_KEY,
        aws_secret_access_key='coinapi',
        endpoint_url='https://s3.flatfiles.coinapi.io',
        config=Config(signature_version='s3v4', region_name='us-east-1'),
    )

### Buckets available

- coinapi — main historical data
- coinapi-daily-tail — last 24h only
- coinapi-indexes — market indices

### Dataset prefixes (under coinapi)

| Prefix | Content |
|---|---|
| T-TRADES | Executed trades |
| T-LIMITBOOK_FULL | Full-depth L2 book (SET/SUB/ADD/SNAPSHOT rows) |
| T-QUOTES | Best bid/ask quotes |
| T-OHLCVRT | OHLCV candles |

### Partition structure

    {DATASET}/D-{YYYYMMDDHH}/{EXCHANGE}/{FILE}.csv.gz

Example:
    T-TRADES/D-2026091400/E-HYPERLIQUIDL4/IDDI-...S-BTCUSDT.csv.gz

### Files of interest

| Dataset | Exchange code | Symbol match string |
|---|---|---|
| Binance spot trades | E-BINANCE | SC-BINANCE_SPOT_BTC_USDT |
| Binance spot L2 | E-BINANCE | SC-BINANCE_SPOT_BTC_USDT |
| Binance futures trades | E-BINANCEFTS | SC-BINANCEFTS_PERP_BTC_USDT |
| Binance futures L2 | E-BINANCEFTS | SC-BINANCEFTS_PERP_BTC_USDT |
| Hyperliquid BTC L4 | E-HYPERLIQUIDL4 | SC-HYPERLIQUIDL4_PERP_BTC_USDC |
| Hyperliquid ETH L4 | E-HYPERLIQUIDL4 | SC-HYPERLIQUIDL4_PERP_ETH_USDC |
| Hyperliquid SOL L4 | E-HYPERLIQUIDL4 | SC-HYPERLIQUIDL4_PERP_SOL_USDC |

---

## Data Schemas (discovered by probing)

### Binance T-LIMITBOOK_FULL (order book L2)

Delimiter: semicolon (;)
Columns: time_exchange;time_coinapi;update_type;is_buy;entry_px;entry_sx;order_id

Notes:
- update_type is one of: SNAPSHOT, SET, SUB, ADD
- SNAPSHOT appears once at the beginning of each hourly file (full book state)
- SET is the dominant type (~96%) — it re-publishes current state at each level
- is_buy: 1 = bid, 0 = ask
- entry_px = price, entry_sx = size in BTC
- File size: ~20 MB/hour compressed (Binance spot), ~60 MB/hour (futures)
- Decompression: MUST use gzip module; pandas cannot auto-detect .gz when passed raw bytes

### Binance T-TRADES (executed trades)

Delimiter: semicolon (;)
Columns: time_exchange;time_coinapi;guid;price;base_amount;taker_side;id_exch_guid;id_exch_int_inc;order_id_maker;order_id_taker

Notes:
- taker_side: "BUY" or "SELL" (aggressor)
- time_coinapi is full ISO timestamp

### Hyperliquid T-TRADES (L4 with wallets)

Delimiter: semicolon (;)
Columns: time_exchange;time_coinapi;guid;price;base_amount;taker_side;id_exch_guid;id_exch_int_inc;order_id_maker;order_id_taker;user_taker;user_maker

Notes:
- user_taker and user_maker are Ethereum wallet addresses (0x...)
- This is unique — the only dataset with entity-level attribution
- File size: ~1 MB/hour compressed (much smaller than Binance)
- taker_side same as Binance

---

## Working Constants (do not change without re-validating)

### Cost model

| Venue | Round-trip cost |
|---|---|
| Binance Spot (taker) | 0.240% |
| Binance Futures (taker) | 0.120% |
| Hyperliquid taker | 0.090% |
| Hyperliquid maker | 0.030% (untested) |

### Wallet scoring (Smart Money test)

- Shrinkage formula: score = corr * n / (n + 100)
- Min active minutes: 50
- Min active days: 3
- Min total volume: 0.5 BTC
- Top N wallets tested: 50, 100, 500

### Coarse-bar signal

- Rolling z-score window: 42 bars
- Entry threshold: |z| > 1.0
- Bar sizes tested: 5min, 15min, 1h, 4h

### Train/test split (5-week Hyperliquid window)

- Train: 2026-08-17 to 2026-08-23 (7 days)
- Test: 2026-08-24 to 2026-09-20 (28 days)

### Data window

- END_DATE: 2026-09-21
- START_DATE: 2026-08-17 (35 days prior)

---

## Altrady MCP (infrastructure only, not part of signal research)

- Server URL: http://127.0.0.1:6850/mcp
- Server runs only inside the Altrady Desktop app (Windows)
- Auth header: Authorization: Bearer <token>
- Accept header (required): "application/json, text/event-stream"
- Import: from mcp.client.streamable_http import streamable_http_client
- Client wraps httpx.AsyncClient with timeout=httpx.Timeout(30, read=300), follow_redirects=True
- Usage pattern:

    async with streamable_http_client(url=URL, http_client=http_client) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("tool_name", {"param": "value"})

- Important: MCP v2 yields only TWO values (read, write), not three
- Altrady MCP never places orders without user click in the UI

---

## Known Bugs Fixed (do not reintroduce)

1. gzip decoding: pass gzip.decompress(bytes) to pd.read_csv, not raw bytes
2. MCP v2 unpacking: streamable_http_client yields 2 values, not 3
3. Pandas set_index: after mm.set_index('minute'), do not access mm['minute'] as column
4. CoinAPI S3 secret: use 'coinapi', not 'FinFeedAPI'
5. Hyperliquid cache filename mismatch: use consistent naming
6. Node.js/Python: skip the "Additional Tools" installer, install Python separately

---

## Key Scripts and Their Purpose

| Script | Purpose |
|---|---|
| check_history.py | Probe CoinAPI for earliest Hyperliquid L4 availability |
| pull_hl_5weeks.py | Download 5 weeks of Hyperliquid L4 (template for longer) |
| smart_money.py | Score wallets, compute top-N flow, evaluate out-of-sample |
| coarse_bars.py | Resample flow to 5m/15m/1h/4h, run threshold strategies |
| validate_edge.py | Multi-asset coarse-bar test (BTC, ETH, SOL) |
| trend_control.py | OLS regression: next_ret ~ flow_z + past_ret |

---

## Current State (2026-09-21)

Last action: check_history.py running to determine how far back Hyperliquid L4 data is available.

Next steps once check_history.py finishes:
1. Decide the historical window length (target: 6–12 months)
2. Download extended data for BTC, ETH, SOL
3. Re-run validate_edge.py + trend_control.py on the extended window
4. Confirm the 4h edge survives bear + sideways regimes
5. If yes: design live execution via direct Hyperliquid API

Open questions:
- Does the 4h edge survive a bear market? (unknown — need longer window)
- What is Hyperliquid maker fill rate at desired entry prices?
- Is the signal robust to rolling window and threshold variations?

---

End of technical notes.