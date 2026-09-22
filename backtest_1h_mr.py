import asyncio
import json
from datetime import datetime, timezone, timedelta
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = "http://127.0.0.1:6850/mcp"
MCP_TOKEN = "sUADWs9dvL_OjtcFiATs0DczDIw30UE6ew1zAYx99QE"

EXCHANGE = "BINA"
SYMBOL = "BTC/USDT"
TIMEFRAME = "60"
BAR_HOURS = 1

# --- Cost config (same as previous tests for direct comparison) ---
FEES_ROUNDTRIP = 0.00140
SLIPPAGE_ROUNDTRIP = 0.00100
COST_ROUNDTRIP = FEES_ROUNDTRIP + SLIPPAGE_ROUNDTRIP

START = datetime(2024, 9, 20, tzinfo=timezone.utc)
END = datetime(2026, 9, 20, tzinfo=timezone.utc)

# --- Bollinger Band config ---
BB_PERIOD = 20
BB_STD = 2.0
MAX_HOLD_BARS = 100  # safety exit: close after 100 bars (about 4 days) if no reversion

# --- ADX config ---
ADX_PERIOD = 14


async def fetch_all_candles(session):
    all_candles = []
    cursor = START
    window = timedelta(days=60)
    while cursor < END:
        window_end = min(cursor + window, END)
        result = await session.call_tool("get_ohlc", {
            "exchange": EXCHANGE,
            "marketSymbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "from": cursor.isoformat().replace("+00:00", "Z"),
            "to": window_end.isoformat().replace("+00:00", "Z"),
            "limit": 2000,
        })
        for block in result.content:
            if hasattr(block, 'text'):
                try:
                    data = json.loads(block.text)
                    all_candles.extend(data.get("candles", []))
                except json.JSONDecodeError:
                    pass
        cursor = window_end
    return all_candles


def bollinger(closes, period, num_std):
    n = len(closes)
    mid = [None] * n
    upper = [None] * n
    lower = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        mid[i] = m
        upper[i] = m + num_std * sd
        lower[i] = m - num_std * sd
    return mid, upper, lower


def compute_adx(highs, lows, closes, period=14):
    n = len(closes)
    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    if n < 2 * period + 1:
        return [None] * n

    str_ = [None] * n
    sp = [None] * n
    sm = [None] * n
    str_[period] = sum(tr[1:period + 1])
    sp[period] = sum(plus_dm[1:period + 1])
    sm[period] = sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        str_[i] = str_[i - 1] - str_[i - 1] / period + tr[i]
        sp[i] = sp[i - 1] - sp[i - 1] / period + plus_dm[i]
        sm[i] = sm[i - 1] - sm[i - 1] / period + minus_dm[i]

    dx = [None] * n
    for i in range(period, n):
        if str_[i] and str_[i] != 0:
            pdi = 100 * sp[i] / str_[i]
            mdi = 100 * sm[i] / str_[i]
            denom = pdi + mdi
            if denom != 0:
                dx[i] = 100 * abs(pdi - mdi) / denom

    adx = [None] * n
    first = 2 * period - 1
    if n <= first:
        return adx
    valid_dx = [dx[i] for i in range(period, first + 1) if dx[i] is not None]
    if len(valid_dx) < period:
        return adx
    adx[first] = sum(valid_dx[:period]) / period
    for i in range(first + 1, n):
        if dx[i] is not None and adx[i - 1] is not None:
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def bucket_stats(name, trades):
    if not trades:
        print(f"{name:22s}  n=0")
        return
    n = len(trades)
    wins = [t for t in trades if t['net_return'] > 0]
    avg = sum(t['net_return'] for t in trades) / n
    wr = len(wins) / n * 100
    print(f"{name:22s}  n={n:3d}  win%={wr:5.1f}  avg_net={avg * 100:+.3f}%")


async def main():
    http_client = httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {MCP_TOKEN}",
            "Accept": "application/json, text/event-stream",
        },
        timeout=httpx.Timeout(60, read=600),
        follow_redirects=True,
    )

    async with http_client:
        async with streamable_http_client(url=MCP_SERVER_URL, http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print(f"Fetching {SYMBOL} {BAR_HOURS}h candles...\n")
                candles = await fetch_all_candles(session)

    print(f"Total candles: {len(candles)}\n")
    if len(candles) < 200:
        print("Not enough candles. Aborting.")
        return

    closes = [float(c['close']) for c in candles]
    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    times = [c['time'] for c in candles]

    mid, upper, lower = bollinger(closes, BB_PERIOD, BB_STD)
    adx_vals = compute_adx(highs, lows, closes, ADX_PERIOD)

    position = False
    entry_price = None
    entry_time = None
    entry_adx = None
    entry_bar = None
    trades = []

    for i in range(1, len(closes)):
        if mid[i] is None or mid[i - 1] is None:
            continue
        prev_close = closes[i - 1]
        curr_close = closes[i]

        if not position:
            if lower[i] is not None and lower[i - 1] is not None:
                # Entry: close crosses BELOW lower band
                if prev_close >= lower[i - 1] and curr_close < lower[i]:
                    position = True
                    entry_price = curr_close
                    entry_time = times[i]
                    entry_adx = adx_vals[i]
                    entry_bar = i
        else:
            exited = False
            reason = None
            # Exit 1: close crosses ABOVE middle band (reversion target)
            if prev_close <= mid[i - 1] and curr_close > mid[i]:
                exited = True
                reason = "reversion"
            # Exit 2: max hold time
            elif (i - entry_bar) >= MAX_HOLD_BARS:
                exited = True
                reason = "max_hold"

            if exited:
                gross = (curr_close - entry_price) / entry_price
                net = gross - COST_ROUNDTRIP
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': times[i],
                    'net_return': net,
                    'adx_entry': entry_adx,
                    'bars_held': i - entry_bar,
                    'exit_reason': reason,
                })
                position = False

    if not trades:
        print("No trades generated.")
        return

    trades_with_adx = [t for t in trades if t['adx_entry'] is not None]

    # ==================================================
    # OVERALL STATS
    # ==================================================
    print("=" * 60)
    print("PHASE 0.5 — MEAN REVERSION (Bollinger Bands)")
    print("=" * 60)
    n = len(trades_with_adx)
    wins = [t for t in trades_with_adx if t['net_return'] > 0]
    losses = [t for t in trades_with_adx if t['net_return'] <= 0]
    avg = sum(t['net_return'] for t in trades_with_adx) / n
    months = (END - START).days / 30.44

    print(f"Symbol:        {SYMBOL} on {EXCHANGE}")
    print(f"Timeframe:     {BAR_HOURS}h")
    print(f"Period:        {START.date()} → {END.date()}  ({months:.1f} months)")
    print(f"Round-trip:    {COST_ROUNDTRIP * 100:.3f}%\n")
    print(f"Total trades:      {n}")
    print(f"Trades per month:  {n / months:.2f}")
    print(f"Win rate:          {len(wins) / n * 100:.1f}%")
    print(f"Avg win (net):     {sum(t['net_return'] for t in wins) / len(wins) * 100:+.2f}%" if wins else "Avg win: n/a")
    print(f"Avg loss (net):    {sum(t['net_return'] for t in losses) / len(losses) * 100:+.2f}%" if losses else "Avg loss: n/a")
    print(f"AVG NET PER TRADE: {avg * 100:+.3f}%   <-- the key number")

    # Exit reason breakdown
    rev = [t for t in trades_with_adx if t['exit_reason'] == 'reversion']
    mh = [t for t in trades_with_adx if t['exit_reason'] == 'max_hold']
    print(f"\nExits by reversion target: {len(rev)}")
    print(f"Exits by max hold:         {len(mh)}")
    if rev:
        print(f"  reversion avg net: {sum(t['net_return'] for t in rev) / len(rev) * 100:+.3f}%")
    if mh:
        print(f"  max_hold  avg net: {sum(t['net_return'] for t in mh) / len(mh) * 100:+.3f}%")

    # Cumulative
    equity = 1.0
    for t in trades_with_adx:
        equity *= (1 + t['net_return'])
    cum = (equity - 1) * 100
    bh = (closes[-1] - closes[0]) / closes[0] * 100
    print(f"\nCumulative return: {cum:+.2f}%")
    print(f"Buy & hold return: {bh:+.2f}%")

    # ==================================================
    # ADX SPLIT — mean reversion should work in LOW ADX
    # ==================================================
    print("\n" + "=" * 60)
    print("ADX SPLIT — does mean reversion work in low-ADX (range) regimes?")
    print("=" * 60)

    print("\n--- Fixed ADX buckets ---")
    low = [t for t in trades_with_adx if t['adx_entry'] < 20]
    mid_b = [t for t in trades_with_adx if 20 <= t['adx_entry'] < 25]
    high = [t for t in trades_with_adx if 25 <= t['adx_entry'] < 30]
    vhigh = [t for t in trades_with_adx if t['adx_entry'] >= 30]
    bucket_stats("ADX < 20", low)
    bucket_stats("20 <= ADX < 25", mid_b)
    bucket_stats("25 <= ADX < 30", high)
    bucket_stats("ADX >= 30", vhigh)

    if wins and losses:
        avg_w = sum(t['adx_entry'] for t in wins) / len(wins)
        avg_l = sum(t['adx_entry'] for t in losses) / len(losses)
        print(f"\nAvg ADX of winners: {avg_w:.1f}  (n={len(wins)})")
        print(f"Avg ADX of losers:  {avg_l:.1f}  (n={len(losses)})")
        print("(For mean reversion, winners SHOULD have LOWER ADX than losers)")

    # Threshold sweep: only take trades when ADX < X
    print("\n--- Threshold sweep: keep only trades with ADX < X ---")
    print(f"{'Threshold':>10}  {'n_kept':>7}  {'n_dropped':>10}  {'kept_avg_net':>14}  {'dropped_avg_net':>16}")
    for thr in [15, 18, 20, 22, 25, 28, 30, 35, 40]:
        kept = [t for t in trades_with_adx if t['adx_entry'] < thr]
        dropped = [t for t in trades_with_adx if t['adx_entry'] >= thr]
        if not kept:
            continue
        kept_avg = sum(t['net_return'] for t in kept) / len(kept)
        dropped_avg = sum(t['net_return'] for t in dropped) / len(dropped) if dropped else 0
        print(f"{thr:>10}  {len(kept):>7}  {len(dropped):>10}  {kept_avg * 100:>13.3f}%  {dropped_avg * 100:>15.3f}%")

    print("\n" + "=" * 60)
    print("INTERPRETATION")
    print("=" * 60)
    print("If 'kept_avg_net' is POSITIVE at LOW thresholds and turns negative")
    print("at HIGH thresholds, the mean-reversion + regime thesis holds.")
    print("If kept_avg_net stays flat or negative everywhere, it doesn't.")


if __name__ == "__main__":
    asyncio.run(main())