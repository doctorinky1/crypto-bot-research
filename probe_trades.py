import boto3
import gzip
import io
from botocore.config import Config
import pandas as pd

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url='https://s3.flatfiles.coinapi.io',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

# Probe one hour of trades for both venues
PROBES = [
    ('spot',    'T-TRADES/D-2026092109/E-BINANCE/',    'SC-BINANCE_SPOT_BTC_USDT'),
    ('futures', 'T-TRADES/D-2026092109/E-BINANCEFTS/', 'SC-BINANCEFTS_PERP_BTC_USDT'),
]

for venue, prefix, symbol_match in PROBES:
    print(f"\n{'='*70}\n{venue.upper()}: {prefix}\n{'='*70}")

    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=2000)
    target = None
    for obj in resp.get('Contents', []):
        key = obj['Key']
        if symbol_match in key and key.endswith('.csv.gz'):
            target = key
            size_mb = obj['Size'] / 1024 / 1024
            print(f"Found: {key}  ({size_mb:.2f} MB)")
            break

    if not target:
        print("No matching file found.")
        continue

    gz = s3.get_object(Bucket=BUCKET, Key=target)['Body'].read()
    raw = gzip.decompress(gz)
    print(f"Decompressed: {len(raw)/1024/1024:.2f} MB")

    # Read first 5 lines raw to see delimiter
    print("\n--- Raw first 5 lines ---")
    text = raw[:2000].decode('utf-8', errors='replace')
    for line in text.split('\n')[:5]:
        print(line[:300])

    # Try semicolon first (matches our book data)
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=';', nrows=1000)
        if len(df.columns) <= 1:
            raise ValueError("Single column — wrong delimiter")
    except Exception:
        df = pd.read_csv(io.BytesIO(raw), sep=',', nrows=1000)

    print(f"\n--- Detected schema ---")
    print(f"Columns: {list(df.columns)}")
    print(f"dtypes:\n{df.dtypes}")
    print(f"\n--- First 5 rows ---")
    print(df.head().to_string())