import pandas as pd

df = pd.read_csv('btc_usdt_sample.csv', sep=';', dtype={'order_id': str})

# Skip the initial SNAPSHOT block, look only at updates
updates = df[df['update_type'] != 'SNAPSHOT'].copy()

# Look at SET events specifically
sets = updates[updates['update_type'] == 'SET']
print(f"=== SET events ({len(sets):,}) ===")
print(f"Distinct order_ids: {sets['order_id'].nunique():,}")
print(f"Distinct (price, size) pairs: {sets[['entry_px','entry_sx']].drop_duplicates().shape[0]:,}")
print(f"Distinct time_coinapi values: {sets['time_coinapi'].nunique():,}")

# Show a few consecutive SET events and their time gaps
print(f"\n=== First 15 SET events ===")
print(sets.head(15).to_string())

# Sample updates in a 1-second window 30 min in
t0 = updates['time_coinapi'].iloc[len(updates)//2]
window = updates[(updates['time_coinapi'] >= t0) & (updates['time_coinapi'] < t0)]  # placeholder
# Instead: use actual time strings
import datetime
ts = pd.to_datetime(updates['time_coinapi'], format='%H:%M:%S.%f')
target = ts.iloc[len(ts)//2]
mask = (ts >= target - pd.Timedelta(seconds=1)) & (ts < target)
sample = updates[mask]
print(f"\n=== All updates in a 1-second window around {target} ===")
print(sample[['time_exchange','update_type','is_buy','entry_px','entry_sx','order_id']].to_string())