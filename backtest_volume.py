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

FEES_ROUNDTRIP = 0.00140
SLIPPAGE_ROUNDTRIP = 0.00100
COST_ROUNDTRIP = FEES_ROUNDTRIP + SLIPPAGE_ROUNDTRIP

START = datetime(2024, 9, 20, tzinfo=timezone.utc)
END = datetime(2026, 9, 20, tzinfo=timezone.utc)

VWAP_PERIOD = 24           # 24h rolling VWAP
VWAP_STD_PERIOD = 100      # std dev of deviations
VOL_AVG_PERIOD = 20
VOL_SPIKE_MULT = 2.0
VOL_SPIKE_MAXHOLD = 20     # exit after 20 bars if no stop
VOL_SPIKE_STOP = 0.02      # 2% hard stop
OBV_EMA_PERIOD = 20
MFI_PERIOD = 14
MFI_ENTRY = 20
MFI_EXIT = 50


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


def ema(values, period):
    n = len(values)
    out = [None] * n
    if n < period:
        return out
    sma = sum(values[:period]) / period
    out[period - 1] = sma
    mult = 2 / (period + 1)
    prev = sma
    for i in range(period, n):
        prev = (values[i] - prev) * mult + prev
        out[i] = prev
    return out


def compute_vwap_and_dev(closes, volumes, period, dev_period):
    n = len(closes)
    vwap = [None] * n
    dev = [None] * n
    # rolling VWAP
    for i in range(period - 1, n):
        pv = sum(closes[j] * volumes[j] for j in range(i - period + 1, i + 1))
        v = sum(volumes[i - period + 1:i + 1])
        vwap[i] = pv / v if v > 0 else None
    # deviation of close from vwap, then rolling std of that deviation
    raw_dev = [None] * n
    for i in range(n):
        if vwap[i] is not None:
            raw_dev[i] = closes[i] - vwap[i]
    for i in range(dev_period - 1, n):
        window = [raw_dev[j] for j in range(i - dev_period + 1, i + 1) if raw_dev[j] is not None]
        if len(window) >= dev_period:
            m = sum(window) / len(window)
            var = sum((x - m) ** 2 for x in window) / len(window)
            dev[i] = var ** 0.5
    return vwap, dev


def compute_obv(closes, volumes):
    n = len(closes)
    obv = [0.0] * n
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def compute_mfi(highs, lows, closes, volumes, period):
    n = len(closes)
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n)]
    mf = [tp[i] * volumes[i] for i in range(n)]
    pos = [0.0] * n
    neg = [0.0] * n
    for i in range(1, n):
        if tp[i] > tp[i - 1]:
            pos[i] = mf[i]
        elif tp[i] < tp[i - 1]:
            neg[i] = mf[i]
    mfi = [None] * n
    for i in range(period, n):
        p = sum(pos[i - period + 1:i + 1])
        ng = sum(neg[i - period + 1:i + 1])
        if ng == 0:
            mfi[i] = 100.0
        else:
            mfi[i] = 100 - 100 / (1 + p / ng)
    return mfi


def run_signal(name, entries, exits, closes, times):
    """entries/exits are lists of booleans aligned to close bars."""
    position = False
    entry_price = None
    entry_time = None
    trades = []
    for i in range(1, len(closes)):
        if not position and entries[i]:
            position = True
            entry_price = closes[i]
            entry_time = times[i]
        elif position and exits[i]:
            gross = (closes[i] - entry_price) / entry_price
            net = gross - COST_ROUNDTRIP
            trades.append({'net_return': net, 'entry_time': entry_time, 'exit_time': times[i]})
            position = False
    return trades


def stats(name, trades, months, closes):
    if not trades:
        print(f"{name:30s}  n=0")
        return
    n = len(trades)
    wins = [t for t in trades if t['net_return'] > 0]
    losses = [t for t in trades if t['net_return'] <= 0]
    avg = sum(t['net_return'] for t in trades) / n
    wr = len(wins) / n * 100
    eq = 1.0
    for t in trades:
        eq *= (1 + t['net_return'])
    cum = (eq - 1) * 100
    print(f"{name:30s}  n={n:4d}  t/mo={n/months:5.2f}  win%={wr:5.1f}  avg_net={avg*100:+7.3f}%  cum={cum:+8.2f}%")


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
    if len(candles) < 500:
        print("Not enough candles. Aborting.")
        return

    closes = [float(c['close']) for c in candles]
    opens = [float(c['open']) for c in candles]
    highs = [float(c['high']) for c in candles]
    lows = [float(c['low']) for c in candles]
    volumes = [float(c['volume']) for c in candles]
    times = [c['time'] for c in candles]
    n = len(closes)
    months = (END - START).days / 30.44

    print("=" * 100)
    print("VOLUME SIGNAL LAB — all signals, same cost model, same period")
    print("=" * 100)
    print(f"Round-trip cost: {COST_ROUNDTRIP*100:.3f}%   Period: {START.date()} → {END.date()} ({months:.1f} mo)\n")

    # --- Signal 1: VWAP reversion ---
    vwap, dev = compute_vwap_and_dev(closes, volumes, VWAP_PERIOD, VWAP_STD_PERIOD)
    e = [False] * n
    x = [False] * n
    for i in range(1, n):
        if vwap[i] is None or dev[i] is None or vwap[i-1] is None:
            continue
        lower = vwap[i] - 2 * dev[i]
        if closes[i] < lower:
            e[i] = True
        if closes[i] >= vwap[i]:
            x[i] = True
    t_vwap = run_signal("VWAP Reversion", e, x, closes, times)
    stats("VWAP Reversion", t_vwap, months, closes)

    # --- Signal 2: Volume spike continuation ---
    vol_avg = [None] * n
    for i in range(VOL_AVG_PERIOD - 1, n):
        vol_avg[i] = sum(volumes[i - VOL_AVG_PERIOD + 1:i + 1]) / VOL_AVG_PERIOD
    e = [False] * n
    x = [False] * n
    pos = False
    entry_idx = None
    entry_px = None
    for i in range(1, n):
        if pos:
            bars_held = i - entry_idx
            hit_stop = closes[i] < entry_px * (1 - VOL_SPIKE_STOP)
            if hit_stop or bars_held >= VOL_SPIKE_MAXHOLD:
                x[i] = True
                pos = False
        if not pos and vol_avg[i] is not None:
            bullish = closes[i] > opens[i]
            spike = volumes[i] > VOL_SPIKE_MULT * vol_avg[i]
            if bullish and spike:
                e[i] = True
                pos = True
                entry_idx = i
                entry_px = closes[i]
    t_vspike = run_signal("Volume Spike Continuation", e, x, closes, times)
    stats("Volume Spike Continuation", t_vspike, months, closes)

    # --- Signal 3: OBV trend ---
    obv = compute_obv(closes, volumes)
    obv_ema = ema(obv, OBV_EMA_PERIOD)
    e = [False] * n
    x = [False] * n
    for i in range(1, n):
        if obv_ema[i] is None or obv_ema[i-1] is None:
            continue
        if obv[i] > obv_ema[i] and obv[i-1] <= obv_ema[i-1]:
            e[i] = True
        if obv[i] < obv_ema[i] and obv[i-1] >= obv_ema[i-1]:
            x[i] = True
    t_obv = run_signal("OBV Trend", e, x, closes, times)
    stats("OBV Trend", t_obv, months, closes)

    # --- Signal 4: MFI reversion ---
    mfi = compute_mfi(highs, lows, closes, volumes, MFI_PERIOD)
    e = [False] * n
    x = [False] * n
    for i in range(1, n):
        if mfi[i] is None:
            continue
        if mfi[i] < MFI_ENTRY and (mfi[i-1] is None or mfi[i-1] >= MFI_ENTRY):
            e[i] = True
        if mfi[i] > MFI_EXIT and (mfi[i-1] is not None and mfi[i-1] <= MFI_EXIT):
            x[i] = True
    t_mfi = run_signal("MFI Reversion", e, x, closes, times)
    stats("MFI Reversion", t_mfi, months, closes)

    # --- Buy and hold reference ---
    bh = (closes[-1] - closes[0]) / closes[0] * 100
    print()
    print(f"{'Buy & Hold (reference)':30s}  return over period: {bh:+.2f}%")

    print("\n" + "=" * 100)
    print("READ THIS BEFORE INTERPRETING")
    print("=" * 100)
    print("- We tested 4 signals. One may look positive by chance.")
    print("- A 'winner' must be tested on a different asset (ETH, SOL) before we believe it.")
    print("- If everything is negative, volume proxies from OHLCV don't carry edge at these costs.")
    print("- The real order flow signals (VPIN, order book imbalance) need L2 data we don't have.")


if __name__ == "__main__":
    asyncio.run(main())