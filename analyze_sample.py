import pandas as pd

FILE = 'btc_usdt_sample.csv'

print("Loading sample (this may take 30-60 seconds)...")
df = pd.read_csv(FILE, sep=';', dtype={'order_id': str})
print(f"Rows loaded: {len(df):,}\n")

# 1. Update type distribution
print("=== update_type distribution ===")
print(df['update_type'].value_counts())
print()

# 2. Snapshot count
print("=== Snapshot structure ===")
print(f"Distinct time_exchange values: {df['time_exchange'].nunique():,}")
print(f"Orders per snapshot (avg): {len(df) / df['time_exchange'].nunique():,.0f}")
print()

# 3. Book depth per snapshot (using first snapshot as example)
first_ts = df['time_exchange'].iloc[0]
snap = df[df['time_exchange'] == first_ts]
bids = snap[snap['is_buy'] == 1]
asks = snap[snap['is_buy'] == 0]
print(f"=== First snapshot ({first_ts}) ===")
print(f"Bid orders: {len(bids):,}  |  Ask orders: {len(asks):,}")
if len(bids):
    print(f"Bid price range: {bids['entry_px'].min():.2f} – {bids['entry_px'].max():.2f}")
    print(f"Total bid size:  {bids['entry_sx'].sum():,.4f} BTC")
if len(asks):
    print(f"Ask price range: {asks['entry_px'].min():.2f} – {asks['entry_px'].max():.2f}")
    print(f"Total ask size:  {asks['entry_sx'].sum():,.4f} BTC")
print()

# 4. Order size distribution
print("=== Order size stats (all orders) ===")
print(df['entry_sx'].describe())
print()

# 5. Snapshot frequency
print("=== Timing ===")
time_idx = pd.to_datetime(df['time_coinapi'])
time_diffs = time_idx.drop_duplicates().diff().dropna()
print(f"Distinct time_coinapi values: {time_idx.nunique():,}")
print(f"Median gap between snapshots: {time_diffs.median()}")
print(f"Mean gap: {time_diffs.mean()}")