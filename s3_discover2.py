import boto3
from botocore.config import Config

FINFEED_API_KEY = "47d4256b-1907-42bd-96c0-3cd912a923e6"

s3 = boto3.client(
    's3',
    aws_access_key_id=FINFEED_API_KEY,
    aws_secret_access_key='FinFeedAPI',
    endpoint_url='https://s3.flatfiles.finfeedapi.com',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

print("=== ALL top-level prefixes in bucket: finfeedapi ===\n")
paginator = s3.get_paginator('list_objects_v2')
prefixes = []
for page in paginator.paginate(Bucket='finfeedapi', Delimiter='/'):
    for p in page.get('CommonPrefixes', []):
        prefixes.append(p['Prefix'])

print(f"Total top-level prefixes: {len(prefixes)}\n")

# Filter for anything that isn't a stock exchange (E-*)
print("=== Non-E-* prefixes (looking for crypto) ===")
for p in prefixes:
    if not p.startswith('E-'):
        print(f"  {p}")

print("\n=== All prefixes containing crypto keywords ===")
keywords = ['BINANCE', 'COINBASE', 'KRAKEN', 'BYBIT', 'OKX', 'CRYPTO', 'BIT', 'L2', 'ORDERBOOK', 'BOOK']
for p in prefixes:
    up = p.upper()
    if any(k in up for k in keywords):
        print(f"  {p}")

print("\n=== First 20 E-* prefixes (for reference) ===")
for p in prefixes[:20]:
    print(f"  {p}")

print("\n=== Last 20 prefixes alphabetically (to see what comes after E-) ===")
for p in prefixes[-20:]:
    print(f"  {p}")

# Also list predictionmarkets top-level more thoroughly
print("\n=== predictionmarkets bucket — full top-level listing ===")
paginator2 = s3.get_paginator('list_objects_v2')
for page in paginator2.paginate(Bucket='predictionmarkets', Delimiter='/'):
    for p in page.get('CommonPrefixes', []):
        print(f"  {p['Prefix']}")