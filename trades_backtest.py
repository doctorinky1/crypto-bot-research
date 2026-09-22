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

    # Mid from VWAP
    df['ret_next'] = df['vwap'].shift(-1) / df['vwap'] - 1
    df['ret_same'] = df['vwap'].pct_change()

    # Rolling z-score of flow imbalance (24h = 1440 minutes)
    df['flow_z'] = (
        df['flow_imb'] - df['flow_imb'].rolling(1440, min_periods=60).mean()
    ) / df['flow_imb'].rolling(1440, min_periods=60).std()

    # Also: signed volume z-score
    df['signed_vol_z'] = (
        df['signed_vol'] - df['signed_vol'].rolling(1440, min_periods=60).mean()
    ) / df['signed_vol'].rolling(1440, min_periods=60).std()

    return df.dropna(subset=['ret_next'])


def report(name, df, cost):
    print(f"\n{'='*72}")
    print(f"  {name}  —  {len(df):,} bars")
    print(f"{'='*72}")
    print(f"Round-trip cost: {cost*100:.3f}%")
    print(f"Period: {df.index[0]} → {df.index[-1]}")
    print(f"VWAP change over period: {(df['vwap'].iloc[-1]/df['vwap'].iloc[0]-1)*100:+.2f}%")

    for sig in ['flow_imb', 'signed_vol']:
        v = df.dropna(subset=[sig, 'ret_next'])
        c_next = v[sig].corr(v['ret_next'])
        c_same = v[sig].corr(v['ret_same'])
        print(f"\n  [{sig}]")
        print(f"    Corr with NEXT-min return: {c_next:+.4f}  (n={len(v):,})")
        print(f"    Corr with SAME-min return: {c_same:+.4f}")

    # Threshold strategy using flow_z
    print(f"\n  --- Threshold strategies (signal = flow_imb z-score, 1-min hold) ---")
    print(f"  {'Threshold':>10}  {'Side':>6}  {'n':>7}  {'win%':>6}  {'avg_gross':>11}  {'avg_net':>10}  {'cum_net':>10}")

    z = df['flow_z']
    for thr in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        for side, mask in [('LONG', z > thr), ('SHORT', z < -thr)]:
            signals = pd.Series(0, index=df.index)
            signals[mask] = 1 if side == 'LONG' else -1
            # Align signal at t with return t→t+1
            gross = signals * df['ret_next']
            trades = gross.dropna()[gross.dropna() != 0]
            if len(trades) == 0:
                continue
            net = trades - cost
            wins = (net > 0).sum()
            cum = (1 + net).prod() - 1
            print(f"  {thr:>10.1f}  {side:>6}  {len(trades):>7,}  {wins/len(trades)*100:>5.1f}%  "
                  f"{trades.mean()*100:>10.4f}%  {net.mean()*100:>9.4f}%  {cum*100:>9.2f}%")


def main():
    print("Loading trade flow data...")
    spot = load(SPOT)
    futures = load(FUTURES)

    report("BINANCE SPOT BTC/USDT — TRADE FLOW", spot, SPOT_COST)
    report("BINANCE FUTURES BTC/USDT PERP — TRADE FLOW", futures, FUTURES_COST)

    print("\n" + "="*72)
    print("INTERPRETATION")
    print("="*72)
    print("Watch for:")
    print("  - Corr with NEXT-min > +0.02 → trade flow has predictive power")
    print("  - Any avg_net > 0 → exploitable after costs")
    print("  - Trade flow (aggressor side) is a stronger signal than book imbalance")
    print("  - Futures should be cleaner than spot")


if __name__ == "__main__":
    main()