import asyncio
import json
from datetime import datetime, timezone, timedelta
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = "http://127.0.0.1:6850/mcp"
MCP_TOKEN = "sUADWs9dvL_OjtcFiATs0DczDIw30UE6ew1zAYx99QE"

# --- Strategy config ---
EXCHANGE = "BINA"
SYMBOL = "BTC/USDT"
TIMEFRAME = "60"
BAR_HOURS = 1

# --- Cost config ---
FEES_ROUNDTRIP = 0.00140
SLIPPAGE_ROUNDTRIP = 0.00100
COST_ROUNDTRIP = FEES_ROUNDTRIP + SLIPPAGE_ROUNDTRIP

# --- Backtest window ---
START = datetime(2024, 9, 20, tzinfo=timezone.utc)
END = datetime(2026, 9, 20, tzinfo=timezone.utc)

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
                    candles = data.get("candles", [])
                    all_candles.extend(candles)
                except json.JSONDecodeError:
                    print(f"Parse error at {cursor.date()}: {block.text[:200]}")
        cursor = window_end

    return all_candles


def ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1)
    sma = sum(values[:period]) / period
    result.append(sma)
    mult = 2 / (period + 1)
    prev = sma
    for v in values[period:]:
        prev = (v - prev) * mult + prev
        result.append(prev)
    return result


def compute_adx(highs, lows, closes, period=14):
    """Standard Wilder's ADX."""
    n = len(closes)
    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n

    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    if n < 2 * period + 1:
        return [None] * n

    # Wilder's smoothing
    str_ = [None] * n
    sp = [None] * n
    sm = [None] * n
    str_[period] = sum(tr[1:period+1])
    sp[period] = sum(plus_dm[1:period+1])
    sm[period] = sum(minus_dm[1:period+1])

    for i in range(period + 1, n):
        str_[i] = str_[i-1] - str_[i-1] / period + tr[i]
        sp[i] = sp[i-1] - sp[i-1] / period + plus_dm[i]
        sm[i] = sm[i-1] - sm[i-1] / period + minus_dm[i]

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
        if dx[i] is not None and adx[i-1] is not None:
            adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period

    return adx


def summarize_bucket(name, trades):
    if not trades:
        print(f"{name:20s}  n=0")
        return
    n = len(trades)
    wins = [t for t in trades if t['net_return'] > 0]
    avg = sum(t['net_return'] for t in trades) / n
    wr = len(wins) / n * 100
    print(f"{name:20s}  n={n:3d}  win%={wr:5.1f}  avg_net={avg*100:+.3f}%")


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
    if len(candles) < 300:
        print("Not enough candles. Aborting.")
        return

    closes = [float(c['close']) for c in candles]
    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    times = [c['time'] for c in candles]

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    adx_vals = compute_adx(highs, lows, closes, ADX_PERIOD)

    position = False
    entry_price = None
    entry_time = None
    entry_adx = None
    trades = []

    for i in range(1, len(closes)):
        if ema50[i] is None or ema200[i] is None or ema50[i-1] is None or ema200[i-1] is None:
            continue
        prev_above = ema50[i-1] > ema200[i-1]
        curr_above = ema50[i] > ema200[i]

        if not position and curr_above and not prev_above:
            position = True
            entry_price = closes[i]
            entry_time = times[i]
            entry_adx = adx_vals[i]
        elif position and not curr_above and prev_above:
            exit_price = closes[i]
            gross = (exit_price - entry_price) / entry_price
            net = gross - COST_ROUNDTRIP
            trades.append({
                'entry_time': entry_time,
                'exit_time': times[i],
                'net_return': net,
                'adx_entry': entry_adx,
            })
            position = False

    if not trades:
        print("No trades generated.")
        return

    # Skip trades where ADX wasn't yet computed
    trades_with_adx = [t for t in trades if t['adx_entry'] is not None]
    print(f"Total trades: {len(trades)}  (with ADX at entry: {len(trades_with_adx)})\n")

    # ============================================================
    # SPLIT ANALYSIS
    # ============================================================
    print("=" * 60)
    print("ADX SPLIT ANALYSIS — does regime filtering help?")
    print("=" * 60)

    # Overall
    print("\n--- All trades ---")
    summarize_bucket("ALL", trades_with_adx)

    # Fixed buckets
    print("\n--- Fixed ADX buckets ---")
    low = [t for t in trades_with_adx if t['adx_entry'] < 20]
    mid = [t for t in trades_with_adx if 20 <= t['adx_entry'] < 25]
    high = [t for t in trades_with_adx if 25 <= t['adx_entry'] < 30]
    vhigh = [t for t in trades_with_adx if t['adx_entry'] >= 30]
    summarize_bucket("ADX < 20", low)
    summarize_bucket("20 <= ADX < 25", mid)
    summarize_bucket("25 <= ADX < 30", high)
    summarize_bucket("ADX >= 30", vhigh)

    # Winners vs losers ADX
    winners = [t for t in trades_with_adx if t['net_return'] > 0]
    losers = [t for t in trades_with_adx if t['net_return'] <= 0]
    print("\n--- ADX at entry: winners vs losers ---")
    if winners:
        avg_w = sum(t['adx_entry'] for t in winners) / len(winners)
        print(f"Avg ADX of winners: {avg_w:.1f}  (n={len(winners)})")
    if losers:
        avg_l = sum(t['adx_entry'] for t in losers) / len(losers)
        print(f"Avg ADX of losers:  {avg_l:.1f}  (n={len(losers)})")

    # Threshold sweep: "only take trades with ADX > X"
    print("\n--- Threshold sweep: keep only trades with ADX > X ---")
    print(f"{'Threshold':>10}  {'n_kept':>7}  {'n_dropped':>10}  {'kept_avg_net':>14}  {'dropped_avg_net':>16}")
    for thr in [15, 18, 20, 22, 25, 28, 30, 35, 40]:
        kept = [t for t in trades_with_adx if t['adx_entry'] > thr]
        dropped = [t for t in trades_with_adx if t['adx_entry'] <= thr]
        if not kept:
            continue
        kept_avg = sum(t['net_return'] for t in kept) / len(kept)
        dropped_avg = sum(t['net_return'] for t in dropped) / len(dropped) if dropped else 0
        print(f"{thr:>10}  {len(kept):>7}  {len(dropped):>10}  {kept_avg*100:>13.3f}%  {dropped_avg*100:>15.3f}%")

    print("\n" + "=" * 60)
    print("INTERPRETATION")
    print("=" * 60)
    print("If 'kept_avg_net' turns positive at some threshold, the regime thesis")
    print("has legs — you can filter out the unprofitable chop trades.")
    print("If 'kept_avg_net' stays negative at every threshold, ADX filtering")
    print("doesn't separate winners from losers, and the thesis is dead.")


if __name__ == "__main__":
    asyncio.run(main())