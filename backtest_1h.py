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
TIMEFRAME = "60"      # 1 hour
BAR_HOURS = 1

# --- Cost config (per round-trip) ---
FEES_ROUNDTRIP = 0.00140
SLIPPAGE_ROUNDTRIP = 0.00100
COST_ROUNDTRIP = FEES_ROUNDTRIP + SLIPPAGE_ROUNDTRIP

# --- Backtest window ---
START = datetime(2024, 9, 20, tzinfo=timezone.utc)
END = datetime(2026, 9, 20, tzinfo=timezone.utc)
BAR_DURATION = timedelta(hours=BAR_HOURS)


async def fetch_all_candles(session):
    all_candles = []
    cursor = START
    window = timedelta(days=60)  # 60d * 24h = 1440 candles, under 2000 limit

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
                except json.JSONDecodeError:
                    print(f"Could not parse response for {cursor.date()}: {block.text[:200]}")
                    candles = []
                if not candles:
                    print(f"No candles from {cursor.date()} to {window_end.date()}")
                else:
                    print(f"Fetched {len(candles)} candles: {cursor.date()} → {window_end.date()}")
                    all_candles.extend(candles)
        cursor = window_end

    return all_candles


def ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1)
    sma = sum(values[:period]) / period
    result.append(sma)
    multiplier = 2 / (period + 1)
    prev = sma
    for v in values[period:]:
        prev = (v - prev) * multiplier + prev
        result.append(prev)
    return result


def compute_stats(trades, start, end, closes):
    if not trades:
        print("No trades generated.")
        return

    n = len(trades)
    wins = [t for t in trades if t['net_return'] > 0]
    losses = [t for t in trades if t['net_return'] <= 0]
    months = (end - start).days / 30.44

    avg_win = sum(t['net_return'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['net_return'] for t in losses) / len(losses) if losses else 0
    win_rate = len(wins) / n
    avg_trade = sum(t['net_return'] for t in trades) / n

    print("\n" + "=" * 50)
    print(f"PHASE 0.5 — ECONOMICS CHECK ({BAR_HOURS}h)")
    print("=" * 50)
    print(f"Symbol:        {SYMBOL} on {EXCHANGE}")
    print(f"Timeframe:     {BAR_HOURS}h")
    print(f"Period:        {start.date()} → {end.date()}  ({months:.1f} months)")
    print(f"Round-trip cost (fees + slippage): {COST_ROUNDTRIP * 100:.3f}%\n")

    print(f"Total trades:          {n}")
    print(f"Trades per month:      {n / months:.2f}")
    print(f"Win rate:              {win_rate * 100:.1f}%")
    print(f"Avg win (net):         {avg_win * 100:.2f}%")
    print(f"Avg loss (net):        {avg_loss * 100:.2f}%")
    if avg_loss != 0:
        print(f"Payoff ratio:          {abs(avg_win / avg_loss):.2f}")
    print(f"AVG NET PER TRADE:     {avg_trade * 100:.3f}%   <-- the key number")

    equity = 1.0
    curve = [1.0]
    for t in trades:
        equity *= (1 + t['net_return'])
        curve.append(equity)
    cum_return = (equity - 1) * 100

    peak = curve[0]
    max_dd = 0
    for v in curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    bh_return = (closes[-1] - closes[0]) / closes[0] * 100

    print(f"\nCumulative return:     {cum_return:.2f}%")
    print(f"Buy & hold return:     {bh_return:.2f}%")
    print(f"Max drawdown:          {max_dd * 100:.2f}%")

    print("\n--- VERDICT ---")
    if avg_trade <= 0:
        print("❌ Average net per trade is NEGATIVE. Strategy loses money after costs.")
        print("   Do not build. Go back to signal design.")
    elif avg_trade < 0.001:
        print("⚠️  Average net per trade is < 0.10%. Edge is trivially small.")
        print("   Probably not worth building. Costs will eat it in live trading.")
    elif avg_trade < 0.005:
        print("🟡 Average net per trade is modest. Worth building but keep expectations low.")
    else:
        print("✅ Average net per trade is solid. Worth building.")


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

    print(f"\nTotal candles: {len(candles)}\n")
    if len(candles) < 300:
        print("Not enough candles for 50/200 EMA. Aborting.")
        return

    closes = [float(c['close']) for c in candles]
    times = [c['time'] for c in candles]

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    position = False
    entry_price = None
    entry_time = None
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
        elif position and not curr_above and prev_above:
            exit_price = closes[i]
            gross = (exit_price - entry_price) / entry_price
            net = gross - COST_ROUNDTRIP
            trades.append({
                'entry_time': entry_time,
                'exit_time': times[i],
                'entry': entry_price,
                'exit': exit_price,
                'gross_return': gross,
                'net_return': net,
            })
            position = False

    compute_stats(trades, START, END, closes)


if __name__ == "__main__":
    asyncio.run(main())