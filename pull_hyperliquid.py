import boto3, io, os, gzip
from datetime import datetime, timedelta
from botocore.config import Config
import pandas as pd

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'
ENDPOINT = 'https://s3.flatfiles.coinapi.io'

cfg = {
    'exchange': 'E-HYPERLIQUIDL4',
    'symbol_match': 'SC-HYPERLIQUIDL4_PERP_BTC_USDC',
    'cache_dir': 'trades_cache/hyperliquid',
    'output': 'trades_hyperliquid.parquet',
}

END_DATE = datetime(2026, 9, 21)
START_DATE = END_DATE - timedelta(days=7)

s3 = boto3.client('s3', aws_access_key_id=API_KEY,
                  aws_secret_access_key='coinapi',
                  endpoint_url=ENDPOINT,
                  config=Config(signature_version='s3v4', region_name='us-east-1'))

def find_file(prefix, symbol_match):
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=2000)
    for obj in resp.get('Contents', []):
        key = obj['Key']
        if symbol_match in key and key.endswith('.csv.gz'):
            return key
    return None

def process_hour(gz_bytes):
    raw = gzip.decompress(gz_bytes)
    df = pd.read_csv(io.BytesIO(raw), sep=';')
    # Print columns once so we can see the Hyperliquid L4 schema
    if not hasattr(process_hour, '_printed'):
        print(f"Columns: {list(df.columns)}")
        print(df.head(3).to_string())
        process_hour._printed = True
    return df

os.makedirs(cfg['cache_dir'], exist_ok=True)
cursor = START_DATE
while cursor < END_DATE:
    hour_key = cursor.strftime('%Y%m%d%H')
    prefix = f"T-TRADES/D-{hour_key}/{cfg['exchange']}/"
    file_key = find_file(prefix, cfg['symbol_match'])
    if file_key:
        gz = s3.get_object(Bucket=BUCKET, Key=file_key)['Body'].read()
        df = process_hour(gz)
        print(f"  {hour_key}: {len(gz)/1024/1024:.1f} MB → {len(df):,} trades")
    else:
        print(f"  {hour_key}: not found")
    cursor += timedelta(hours=1)
    if cursor > START_DATE + timedelta(hours=3):
        print("\n(Stopping after 3 hours — schema check only)")
        break