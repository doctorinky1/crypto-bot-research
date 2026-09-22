import pandas as pd
import numpy as np

SPOT = 'ofi_spot.parquet'
FUTURES = 'ofi_futures.parquet'

# Cost model — same framework we've been using
SPOT_COST = 0.00240      # 0.10% taker fee x 2 sides + 0.02% slippage x 2
FUTURES_COST = 0.00120   # 0.05% taker fee x 2 sides + 0.01% slippage x 2


def load_and_prepare(path):
    df = pd.read_parquet(path)
    # Sort chronologically across the full week
    df = df.sort_values(['hour_key', 'minute']).reset_index(drop=True)
    # Build a timestamp
    df['ts'] = pd.to_datetime(df['hour_key'], format='%Y%m%d%H') + pd.to_timedelta(df['minute'], unit='m')
    df = df.set_index('ts')

    # Two OFI variants
    # Level: imbalance at end of minute, normalized to [-1, 1]
    total = df['bid_vol_last'] + df['ask_vol_last']
    df['imbalance'] = (df['bid_vol_last'] - df['ask_vol_last']) / total.replace(0, np.nan)
    # Change: OFI as change in imbalance
    df['ofi_change'] = df['imbalance'].diff()

    # Raw change in top-K bid/ask volume (Cont-style OFI)
    df['ofi_raw'] = (df['bid_vol_last'].diff() - df['ask_vol_last'].diff())

    # Next-minute return
    df['ret_next'] = df['mid_last'].shift(-1) / df['mid_last'] - 1

    # Same-minute return (for reference)
    df['ret_same'] = df['mid_last'].pct_change()

    return df.dropna(subset=['ret_next'])


def report(name, df, cost):
    print(f"\n{'='*70}")
    print(f"  {name}  —  {len(df):,} one-minute bars")
    print(f"{'='*70}")
    print(f"Round-trip cost: {cost*100:.3f}%")
    print(f"Period: {df.index[0]} → {df.index[-1]}")
    print(f"Price move over period: {(df['mid_last'].iloc[-1]/df['mid_last'].iloc[0]-1)*100:+.2f}%")

    for sig in ['imbalance', 'ofi_change', 'ofi_raw']:
        valid = df.dropna(subset=[sig, 'ret_next'])
        corr = valid[sig].corr(valid['ret_next'])
        corr_same = valid[sig].corr(valid['ret_same'])
        print(f"\n  [{sig}]")
        print(f"    Correlation with NEXT-minute return: {corr:+.4f}  (n={len(valid):,})")
        print(f"    Correlation with SAME-minute return: {corr_same:+.4f}")

    # Threshold strategy test using the standardized imbalance signal
    print(f"\n  --- Threshold strategies (signal = imbalance) ---")
    print(f"  {'Threshold':>10}  {'n_trades':>9}  {'win%':>7}  {'avg_gross':>11}  {'avg_net':>10}  {'cum_net':>10}")

    imb = df['imbalance'].copy()
    # Z-score the imbalance so thresholds are comparable across time
    z = (imb - imb.rolling(1440, min_periods=60).mean()) / imb.rolling(1440, min_periods=60).std()

    for thr in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        # Long when z > thr, short when z < -thr, exit at next bar (1-minute hold)
        signals = pd.Series(0, index=df.index)
        signals[z > thr] = 1
        signals[z < -thr] = -1
        # Offset by 1 so signal at t → return at t+1
        signals_shifted = signals.shift(1)

        # Gross returns per trade
        gross_ret = signals_shifted * df['ret_next']
        trades = gross_ret.dropna()
        trades = trades[trades != 0]
        if len(trades) == 0:
            continue
        net = trades - cost
        wins = (net > 0).sum()
        avg_gross = trades.mean()
        avg_net = net.mean()
        cum = (1 + net).prod() - 1
        print(f"  {thr:>10.1f}  {len(trades):>9,}  {wins/len(trades)*100:>6.1f}%  {avg_gross*100:>10.4f}%  {avg_net*100:>9.4f}%  {cum*100:>9.2f}%")


def main():
    print("Loading data...")
    spot = load_and_prepare(SPOT)
    futures = load_and_prepare(FUTURES)

    report("BINANCE SPOT BTC/USDT", spot, SPOT_COST)
    report("BINANCE FUTURES BTC/USDT PERP", futures, FUTURES_COST)

    print("\n" + "="*70)
    print("INTERPRETATION")
    print("="*70)
    print("Look for:")
    print("  1. Correlation with NEXT-minute return > +0.02 with n > 5000")
    print("     → OFI has real predictive power")
    print("  2. avg_net > 0 in the threshold table at some reasonable threshold")
    print("     → an exploitable strategy after costs")
    print("  3. Futures should show stronger signal than spot (deeper book, more informed flow)")
    print()
    print("If everything is negative and correlations are near zero,")
    print("the OFI signal as computed does not work at 1-minute horizon.")


if __name__ == "__main__":
    main()