import boto3
import io
import os
from datetime import datetime, timedelta
from botocore.config import Config
import pandas as pd
import numpy as np

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'
ENDPOINT = 'https://s3.flatfiles.coinapi.io'
TOP_K = 10

VENUES = {
    'spot': {
        'exchange': 'E-BINANCE',
        'symbol_match': 'SC-BINANCE_SPOT_BTC_USDT',
        'cache_dir': 'ofi_cache/spot',
        'output': 'ofi_spot.parquet',
    },
    'futures': {
        'exchange': 'E-BINANCEFTS',
        'symbol_match': 'SC-BINANCEFTS_PERP_BTC_USDT',
        'cache_dir': 'ofi_cache/futures',
        'output': 'ofi_futures.parquet',
    },
}

# Last 7 full days, ending yesterday
END_DATE = datetime(2026, 9, 21)
START_DATE = END_DATE - timedelta(days=7)

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url=ENDPOINT,
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)


def find_file(prefix, symbol_match):
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=2000)
    for obj in resp.get('Contents', []):
        key = obj['Key']
        if symbol_match in key and key.endswith('.csv.gz'):
            return key
    return None


def process_hour(gz_bytes):
    import gzip
    decompressed = gzip.decompress(gz_bytes)
    df = pd.read_csv(io.BytesIO(decompressed), sep=';', dtype={'order_id': str})
    live = df[df['entry_sx'] > 0].copy()
    if len(live) == 0:
        return None

    # Sort: bids descending price, asks ascending price, within each snapshot
    live['sort_key'] = np.where(live['is_buy'] == 1, -live['entry_px'], live['entry_px'])
    live = live.sort_values(['time_coinapi', 'sort_key'], kind='mergesort')
    live['rank'] = live.groupby('time_coinapi', sort=False).cumcount()
    top = live[live['rank'] < TOP_K]

    # Per-snapshot top-K volume by side
    agg = top.groupby(['time_coinapi', 'is_buy'])['entry_sx'].sum().unstack(fill_value=0.0)
    for c in [0, 1]:
        if c not in agg.columns:
            agg[c] = 0.0
    agg = agg.rename(columns={1: 'bid_vol', 0: 'ask_vol'})

    # Best bid/ask/mid per snapshot
    bids = top[top['is_buy'] == 1].groupby('time_coinapi')['entry_px'].max()
    asks = top[top['is_buy'] == 0].groupby('time_coinapi')['entry_px'].min()
    agg['best_bid'] = bids
    agg['best_ask'] = asks
    agg['mid'] = (agg['best_bid'] + agg['best_ask']) / 2

    # Resample to 1-min bars using simple minute extraction
    agg = agg.reset_index()
    agg['minute'] = agg['time_coinapi'].str.slice(3, 5).astype(int)

    bars = agg.groupby('minute').agg({
        'bid_vol': ['last', 'mean'],
        'ask_vol': ['last', 'mean'],
        'mid': 'last',
        'best_bid': 'last',
        'best_ask': 'last',
    })
    bars.columns = [
        'bid_vol_last', 'bid_vol_mean',
        'ask_vol_last', 'ask_vol_mean',
        'mid_last', 'best_bid_last', 'best_ask_last',
    ]
    bars = bars.reset_index()
    return bars


def main():
    for venue_name, cfg in VENUES.items():
        print(f"\n{'='*60}\n{venue_name.upper()} — {cfg['symbol_match']}\n{'='*60}")
        os.makedirs(cfg['cache_dir'], exist_ok=True)

        cursor = START_DATE
        files_done = 0
        files_skipped = 0
        files_failed = 0

        while cursor < END_DATE:
            hour_key = cursor.strftime('%Y%m%d%H')
            cache_path = os.path.join(cfg['cache_dir'], f"{hour_key}.parquet")

            if os.path.exists(cache_path):
                files_skipped += 1
                cursor += timedelta(hours=1)
                continue

            prefix = f"T-LIMITBOOK_FULL/D-{hour_key}/{cfg['exchange']}/"
            file_key = find_file(prefix, cfg['symbol_match'])
            if not file_key:
                print(f"  {hour_key}: not found")
                files_failed += 1
                cursor += timedelta(hours=1)
                continue

            try:
                resp = s3.get_object(Bucket=BUCKET, Key=file_key)
                gz_bytes = resp['Body'].read()
                bars = process_hour(gz_bytes)
                if bars is not None and len(bars) > 0:
                    bars['hour_key'] = hour_key
                    bars.to_parquet(cache_path)
                    files_done += 1
                    print(f"  {hour_key}: {len(gz_bytes)/1024/1024:.1f} MB → {len(bars)} bars")
                else:
                    print(f"  {hour_key}: empty")
                    files_failed += 1
            except Exception as e:
                print(f"  {hour_key}: ERR {type(e).__name__}: {e}")
                files_failed += 1

            cursor += timedelta(hours=1)

        # Combine all cached hours
        print(f"\n{venue_name}: {files_done} processed, {files_skipped} cached, {files_failed} failed")
        all_files = sorted(os.listdir(cfg['cache_dir']))
        if all_files:
            dfs = [pd.read_parquet(os.path.join(cfg['cache_dir'], f)) for f in all_files]
            combined = pd.concat(dfs, ignore_index=True)
            combined.to_parquet(cfg['output'])
            print(f"Saved {len(combined):,} bars → {cfg['output']}")


if __name__ == "__main__":
    main()