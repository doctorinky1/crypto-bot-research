import pandas as pd
import numpy as np

SPOT = 'trades_spot.parquet'
FUTURES = 'trades_futures.parquet'
SPOT_COST = 0.00240
FUTURES_COST = 0.00120

def load(path):
    df = pd.read_parquet(path)
    df['minute'] = pd.to_datetime(df['minute'], utc=True)
    df = df.set_index('minute').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    df['flow_z'] = (
        df['flow_imb'] - df['flow_imb'].rolling(1440, min_periods=60).mean()
    ) / df['flow_imb'].rolling(1440, min_periods=60).std()
    return df

def test_horizon(df, horizon_min, cost, threshold):
    fwd = df['vwap'].shift(-horizon_min) / df['vwap'] - 1
    sig = df['flow_z'].shift(0)
    s = np.sign(sig) * (sig.abs() > threshold)
    gross = s * fwd
    trades = gross.dropna()[gross.dropna() != 0]
    if len(trades) == 0:
        return None
    net = trades - cost
    wins = (net > 0).sum()
    cum = (1 + net).prod() - 1
    return {
        'n': len(trades),
        'win%': wins / len(trades) * 100,
        'gross%': trades.mean() * 100,
        'net%': net.mean() * 100,
        'cum%': cum * 100,
    }

def report(name, df, cost):
    print(f"\n{'='*80}")
    print(f"  {name}  —  horizon test (threshold |z| > 1.0)")
    print(f"{'='*80}")
    print(f"  {'Horizon':>8}  {'n':>7}  {'win%':>7}  {'gross%':>10}  {'net%':>10}  {'cum%':>12}")
    for h in [1, 2, 5, 10, 15, 30, 60]:
        r = test_horizon(df, h, cost, 1.0)
        if r:
            print(f"  {h:>7}m  {r['n']:>7,}  {r['win%']:>6.1f}%  {r['gross%']:>9.4f}%  {r['net%']:>9.4f}%  {r['cum%']:>11.2f}%")

if __name__ == "__main__":
    spot = load(SPOT)
    futures = load(FUTURES)
    report("BINANCE SPOT BTC/USDT", spot, SPOT_COST)
    report("BINANCE FUTURES BTC/USDT PERP", futures, FUTURES_COST)
    print("\nKey question: does gross% grow with horizon, or decay?")