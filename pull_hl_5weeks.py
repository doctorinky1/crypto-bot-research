import boto3, io, os, gzip
from datetime import datetime, timedelta
from botocore.config import Config
import pandas as pd
import numpy as np

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'
ENDPOINT = 'https://s3.flatfiles.coinapi.io'
SYMBOL = 'SC-HYPERLIQUIDL4_PERP_BTC_USDC'
EXCHANGE = 'E-HYPERLIQUIDL4'
CACHE = 'hl_cache'
OUTPUT_WALLET = 'hl_wallet_minute.parquet'
OUTPUT_MINUTE = 'hl_minute.parquet'

# 35 days: weeks 1 = train, weeks 2-5 = test
END_DATE = datetime(2026, 9, 21)
START_DATE = END_DATE - timedelta(days=35)

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url=ENDPOINT,
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)


def find_file(prefix, sym):
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=2000)
    for obj in resp.get('Contents', []):
        if sym in obj['Key'] and obj['Key'].endswith('.csv.gz'):
            return obj['Key']
    return None


def process_hour(gz_bytes):
    """Return (wallet_minute_df, minute_df) for one hour."""
    raw = gzip.decompress(gz_bytes)
    df = pd.read_csv(
        io.BytesIO(raw),
        sep=';',
        usecols=['time_coinapi', 'price', 'base_amount', 'taker_side', 'user_taker'],
    )
    if len(df) == 0:
        return None, None

    # Drop any rows with missing wallet or invalid size
    df = df.dropna(subset=['user_taker'])
    df = df[df['base_amount'] > 0]
    if len(df) == 0:
        return None, None

    df['minute'] = pd.to_datetime(df['time_coinapi'], format='ISO8601', utc=True).dt.floor('1min')
    df['is_buy'] = df['taker_side'] == 'BUY'
    df['buy_vol'] = df['base_amount'].where(df['is_buy'], 0.0)
    df['sell_vol'] = df['base_amount'].where(~df['is_buy'], 0.0)
    df['notional'] = df['price'] * df['base_amount']

    # Wallet-minute aggregation (taker side)
    wallet = df.groupby(['minute', 'user_taker'], sort=False).agg(
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        total_vol=('base_amount', 'sum'),
        notional=('notional', 'sum'),
        trade_count=('price', 'size'),
    ).reset_index().rename(columns={'user_taker': 'wallet'})

    # Minute-level aggregates (for VWAP & price return)
    minute = df.groupby('minute', sort=False).agg(
        total_vol=('base_amount', 'sum'),
        notional=('notional', 'sum'),
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        px_first=('price', 'first'),
        px_last=('price', 'last'),
        trade_count=('price', 'size'),
    ).reset_index()
    minute['vwap'] = minute['notional'] / minute['total_vol']

    return wallet, minute


def main():
    os.makedirs(CACHE, exist_ok=True)
    cursor = START_DATE
    done = skipped = failed = 0
    total_hours = int((END_DATE - START_DATE).total_seconds() // 3600)

    while cursor < END_DATE:
        hk = cursor.strftime('%Y%m%d%H')
        wallet_path = os.path.join(CACHE, f"{hk}_wallet.parquet")
        minute_path = os.path.join(CACHE, f"{hk}_minute.parquet")

        if os.path.exists(wallet_path) and os.path.exists(minute_path):
            skipped += 1
            cursor += timedelta(hours=1)
            continue

        fk = find_file(f"T-TRADES/D-{hk}/{EXCHANGE}/", SYMBOL)
        if not fk:
            print(f"  {hk}: not found")
            failed += 1
            cursor += timedelta(hours=1)
            continue

        try:
            gz = s3.get_object(Bucket=BUCKET, Key=fk)['Body'].read()
            wallet, minute = process_hour(gz)
            if wallet is not None and len(wallet) > 0:
                wallet['hour_key'] = hk
                minute['hour_key'] = hk
                wallet.to_parquet(wallet_path)
                minute.to_parquet(minute_path)
                done += 1
                if done % 20 == 0 or done <= 3:
                    print(f"  [{done + skipped}/{total_hours}] {hk}: "
                          f"{len(gz)/1024:.0f} KB → {len(wallet):,} wallet-rows, "
                          f"{len(minute)} minute-bars")
        except Exception as e:
            print(f"  {hk}: ERR {type(e).__name__}: {e}")
            failed += 1

        cursor += timedelta(hours=1)

    print(f"\n{done} new, {skipped} cached, {failed} failed")

    # Combine caches
    print("\nCombining cached files...")
    wallet_files = sorted(f for f in os.listdir(CACHE) if f.endswith('_wallet.parquet'))
    minute_files = sorted(f for f in os.listdir(CACHE) if f.endswith('_minute.parquet'))

    if wallet_files:
        dfs = [pd.read_parquet(os.path.join(CACHE, f)) for f in wallet_files]
        combined_w = pd.concat(dfs, ignore_index=True).sort_values('minute').reset_index(drop=True)
        combined_w.to_parquet(OUTPUT_WALLET)
        print(f"  Wallet-minute: {len(combined_w):,} rows → {OUTPUT_WALLET}")

    if minute_files:
        dfs = [pd.read_parquet(os.path.join(CACHE, f)) for f in minute_files]
        combined_m = pd.concat(dfs, ignore_index=True).sort_values('minute').reset_index(drop=True)
        combined_m.to_parquet(OUTPUT_MINUTE)
        print(f"  Minute bars:   {len(combined_m):,} rows → {OUTPUT_MINUTE}")


if __name__ == "__main__":
    main()