import boto3
import gzip
import io
from botocore.config import Config

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url='https://s3.flatfiles.coinapi.io',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

# The exact key from your probe
KEY = 'T-LIMITBOOK_FULL/D-2026092109/E-BINANCE/IDDI-138123+SC-BINANCE_SPOT_BTC_USDT+S-BTCUSDT.csv.gz'
LOCAL_FILE = 'btc_usdt_sample.csv.gz'
LOCAL_DECOMPRESSED = 'btc_usdt_sample.csv'

print(f"Downloading {KEY}...")
s3.download_file(BUCKET, KEY, LOCAL_FILE)

import os
size_mb = os.path.getsize(LOCAL_FILE) / 1024 / 1024
print(f"Downloaded: {size_mb:.2f} MB\n")

# Decompress
print(f"Decompressing to {LOCAL_DECOMPRESSED}...")
with gzip.open(LOCAL_FILE, 'rb') as f_in:
    with open(LOCAL_DECOMPRESSED, 'wb') as f_out:
        f_out.write(f_in.read())

decomp_size_mb = os.path.getsize(LOCAL_DECOMPRESSED) / 1024 / 1024
print(f"Decompressed: {decomp_size_mb:.2f} MB\n")

# Print the first 10 lines and count total rows
print("=== First 10 lines ===")
with open(LOCAL_DECOMPRESSED, 'r', encoding='utf-8', errors='replace') as f:
    for i, line in enumerate(f):
        if i >= 10:
            break
        print(line.rstrip()[:300])

print("\n=== Counting rows ===")
row_count = 0
with open(LOCAL_DECOMPRESSED, 'r', encoding='utf-8', errors='replace') as f:
    for _ in f:
        row_count += 1
print(f"Total rows: {row_count:,}")

# Print header analysis
print("\n=== Column header analysis ===")
with open(LOCAL_DECOMPRESSED, 'r', encoding='utf-8', errors='replace') as f:
    header = f.readline().rstrip()
print(f"Header: {header}")
print(f"Number of columns: {len(header.split(','))}")