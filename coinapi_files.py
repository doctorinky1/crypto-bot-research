import boto3
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

# Probe multiple exchanges in the same hour for direct comparison
HOUR = 'T-LIMITBOOK_FULL/D-2026092109/'
EXCHANGES = ['E-BINANCE', 'E-BINANCEFTS', 'E-HYPERLIQUID']

for ex in EXCHANGES:
    prefix = f"{HOUR}{ex}/"
    print(f"\n{'='*70}")
    print(f"=== {prefix} ===")
    print('='*70)
    try:
        # Get ALL files (not just first few) to find BTC
        paginator = s3.get_paginator('list_objects_v2')
        total_size = 0
        total_count = 0
        btc_files = []

        for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
            for obj in page.get('Contents', []):
                total_count += 1
                total_size += obj['Size']
                if 'BTC' in obj['Key'].upper() and 'USDT' in obj['Key'].upper():
                    btc_files.append(obj)

        print(f"Total files in this folder: {total_count}")
        print(f"Total size: {total_size / 1024 / 1024:.2f} MB")
        print(f"\nBTC/USDT files found: {len(btc_files)}")
        for obj in btc_files[:10]:
            size_mb = obj['Size'] / 1024 / 1024
            print(f"  {obj['Key'].split('/')[-1]}  ({size_mb:.2f} MB)")

    except Exception as e:
        print(f"  Failed: {type(e).__name__}: {e}")

print("\n" + "="*70)
print("COST MATH (based on BinanceFTS BTC/USDT hourly file size):")
print("="*70)
print("If an hourly BTC/USDT file is X MB:")
print("  - One day (24h) = 24X MB")
print("  - One month (720h) = 720X MB = ~0.7X GB")
print("  - Three months (2160h) = 2160X MB = ~2.1X GB")
print("  - At $0.05/GB, 3 months of single-pair data = ~$0.11X")
print("\nExample: if each hour is 100 MB, 3 months = ~216 GB = ~$10.80")
print("Example: if each hour is 10 MB, 3 months = ~21.6 GB = ~$1.08")