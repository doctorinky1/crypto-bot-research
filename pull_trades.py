import boto3
import io
import os
import gzip
from datetime import datetime, timedelta
from botocore.config import Config
import pandas as pd
import numpy as np

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'
ENDPOINT = 'https://s3.flatfiles.coinapi.io'

VENUES = {
    'spot': {
        'exchange': 'E-BINANCE',
        'symbol_match': 'SC-BINANCE_SPOT_BTC_USDT',
        'cache_dir': 'trades_cache/spot',
        'output': 'trades_spot.parquet',
    },
    'futures': {
        'exchange': 'E-BINANCEFTS',
        'symbol_match': 'SC-BINANCEFTS_PERP_BTC_USDT',
        'cache_dir': 'trades_cache/futures',
        'output': 'trades_futures.parquet',
    },
}

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
    raw = gzip.decompress(gz_bytes)
    df = pd.read_csv(
        io.BytesIO(raw),
        sep=';',
        usecols=['time_coinapi', 'price', 'base_amount', 'taker_side'],
    )
    if len(df) == 0:
        return None

    df['ts'] = pd.to_datetime(df['time_coinapi'], format='ISO8601', utc=True)
    df['minute'] = df['ts'].dt.floor('1min')

    is_buy = (df['taker_side'] == 'BUY')
    df['buy_vol'] = df['base_amount'].where(is_buy, 0.0)
    df['sell_vol'] = df['base_amount'].where(~is_buy, 0.0)
    df['notional'] = df['price'] * df['base_amount']

    bars = df.groupby('minute').agg(
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        total_vol=('base_amount', 'sum'),
        notional=('notional', 'sum'),
        trade_count=('price', 'size'),
        px_first=('price', 'first'),
        px_last=('price', 'last'),
        px_min=('price', 'min'),
        px_max=('price', 'max'),
    ).reset_index()

    bars['vwap'] = bars['notional'] / bars['total_vol']
    bars['flow_imb'] = (bars['buy_vol'] - bars['sell_vol']) / bars['total_vol']
    bars['signed_vol'] = bars['buy_vol'] - bars['sell_vol']
    bars['minute_str'] = bars['minute'].dt.strftime('%Y%m%d%H%M')
    return bars


def main():
    for venue_name, cfg in VENUES.items():
        print(f"\n{'='*60}\n{venue_name.upper()} — {cfg['symbol_match']}\n{'='*60}")
        os.makedirs(cfg['cache_dir'], exist_ok=True)

        cursor = START_DATE
        files_done = files_skipped = files_failed = 0

        while cursor < END_DATE:
            hour_key = cursor.strftime('%Y%m%d%H')
            cache_path = os.path.join(cfg['cache_dir'], f"{hour_key}.parquet")

            if os.path.exists(cache_path):
                files_skipped += 1
                cursor += timedelta(hours=1)
                continue

            prefix = f"T-TRADES/D-{hour_key}/{cfg['exchange']}/"
            file_key = find_file(prefix, cfg['symbol_match'])
            if not file_key:
                print(f"  {hour_key}: not found")
                files_failed += 1
                cursor += timedelta(hours=1)
                continue

            try:
                gz = s3.get_object(Bucket=BUCKET, Key=file_key)['Body'].read()
                bars = process_hour(gz)
                if bars is not None and len(bars):
                    bars['hour_key'] = hour_key
                    bars.to_parquet(cache_path)
                    files_done += 1
                    print(f"  {hour_key}: {len(gz)/1024/1024:.1f} MB → {len(bars)} bars")
                else:
                    files_failed += 1
                    print(f"  {hour_key}: empty")
            except Exception as e:
                print(f"  {hour_key}: ERR {type(e).__name__}: {e}")
                files_failed += 1

            cursor += timedelta(hours=1)

        print(f"\n{venue_name}: {files_done} processed, {files_skipped} cached, {files_failed} failed")
        all_files = sorted(os.listdir(cfg['cache_dir']))
        if all_files:
            dfs = [pd.read_parquet(os.path.join(cfg['cache_dir'], f)) for f in all_files]
            combined = pd.concat(dfs, ignore_index=True)
            combined = combined.sort_values('minute').reset_index(drop=True)
            combined.to_parquet(cfg['output'])
            print(f"Saved {len(combined):,} bars → {cfg['output']}")


if __name__ == "__main__":
    main()