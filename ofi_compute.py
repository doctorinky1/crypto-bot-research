import pandas as pd
import numpy as np

FILE = 'btc_usdt_sample.csv'
TOP_K = 10

print("Loading sample...")
df = pd.read_csv(FILE, sep=';', dtype={'order_id': str})
print(f"Rows: {len(df):,}\n")

# Use only non-zero size rows
live = df[df['entry_sx'] > 0].copy()
print(f"Non-zero size rows: {len(live):,}")

# Group by snapshot time
groups = live.groupby('time_coinapi', sort=True)
print(f"Snapshots: {len(groups):,}\n")

# For each snapshot, compute top-K bid/ask volume
records = []
for ts, snap in groups:
    bids = snap[snap['is_buy'] == 1].nlargest(TOP_K, 'entry_px')
    asks = snap[snap['is_buy'] == 0].nsmallest(TOP_K, 'entry_px')
    bid_vol = bids['entry_sx'].sum()
    ask_vol = asks['entry_sx'].sum()
    best_bid = bids['entry_px'].max() if len(bids) else np.nan
    best_ask = asks['entry_px'].min() if len(asks) else np.nan
    mid = (best_bid + best_ask) / 2 if not np.isnan(best_bid) and not np.isnan(best_ask) else np.nan
    records.append({
        'time': ts,
        'bid_vol': bid_vol,
        'ask_vol': ask_vol,
        'mid': mid,
    })

ofi_df = pd.DataFrame(records)
print(f"Snapshots processed: {len(ofi_df):,}\n")

# Compute OFI as change in imbalance
ofi_df['imbalance'] = ofi_df['bid_vol'] - ofi_df['ask_vol']
ofi_df['ofi'] = ofi_df['imbalance'].diff()

# Parse time — note format is H:M:S.ffffff with no date
ofi_df['time_parsed'] = pd.to_datetime(ofi_df['time'], format='%H:%M:%S.%f')
ofi_df = ofi_df.set_index('time_parsed')

# Resample to 1-minute bars: mean OFI, last mid
resampled = ofi_df.resample('1min').agg({
    'ofi': 'mean',
    'mid': 'last',
    'bid_vol': 'mean',
    'ask_vol': 'mean',
})
resampled = resampled.dropna()

# Forward return: next minute's mid price change
resampled['ret_next'] = resampled['mid'].shift(-1) / resampled['mid'] - 1

# =====================================================
# SUMMARY
# =====================================================
print("=" * 60)
print("OFI SUMMARY (1-hour sample, 1-minute bars)")
print("=" * 60)
print(f"Bars: {len(resampled)}")
print(f"\nOFI stats:")
print(f"  Mean:   {resampled['ofi'].mean():.4f}")
print(f"  Std:    {resampled['ofi'].std():.4f}")
print(f"  Min:    {resampled['ofi'].min():.4f}")
print(f"  Max:    {resampled['ofi'].max():.4f}")

print(f"\nMid-price stats:")
print(f"  First:  {resampled['mid'].iloc[0]:.2f}")
print(f"  Last:   {resampled['mid'].iloc[-1]:.2f}")
print(f"  Change: {resampled['mid'].iloc[-1] - resampled['mid'].iloc[0]:.2f} "
      f"({(resampled['mid'].iloc[-1]/resampled['mid'].iloc[0]-1)*100:+.3f}%)")

# Correlation between OFI and next-minute return
valid = resampled.dropna(subset=['ofi', 'ret_next'])
corr = valid['ofi'].corr(valid['ret_next'])
print(f"\nCorrelation(OFI(t), return(t→t+1)): {corr:+.4f}")
print(f"  (Positive = OFI predicts next-minute direction)")
print(f"  (Sample size: {len(valid)} bars)")

# Also: correlation of OFI with same-minute return
resampled['ret_same'] = resampled['mid'].pct_change()
valid_same = resampled.dropna(subset=['ofi', 'ret_same'])
corr_same = valid_same['ofi'].corr(valid_same['ret_same'])
print(f"Correlation(OFI(t), return(t-1→t)): {corr_same:+.4f}")

# Top 10 OFI values and their next-minute returns
print(f"\n=== Top 10 positive OFI bars ===")
top_pos = resampled.nlargest(10, 'ofi')[['ofi', 'ret_next']]
print(top_pos.to_string())

print(f"\n=== Top 10 negative OFI bars ===")
top_neg = resampled.nsmallest(10, 'ofi')[['ofi', 'ret_next']]
print(top_neg.to_string())

print("\n" + "=" * 60)
print("HONEST CAVEAT")
print("=" * 60)
print("1 hour = 60 bars. This is a PROOF-OF-CONCEPT run only.")
print("Any correlation here is not statistically meaningful.")
print("If the code runs and the numbers look sane, the next step is")
print("to pull 1 week of data (~$0.75-1.50) for a real test.")