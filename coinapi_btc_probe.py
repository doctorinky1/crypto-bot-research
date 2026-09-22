import boto3
from botocore.config import Config

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'
# Let's look at a specific hour. 
# Using 2026092111 based on your latest listing, which should be recent data.
PREFIX = 'T-LIMITBOOK_FULL/D-2026092111/' 

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url='https://s3.flatfiles.coinapi.io',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

print(f"=== Searching for BTC pairs in {PREFIX} ===\n")
try:
    paginator = s3.get_paginator('list_objects_v2')
    count = 0
    found_btc = False
    
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get('Contents', []):
            key = obj['Key']
            # Filter for BTC pairs
            if 'BTC' in key.upper():
                size_mb = obj['Size'] / 1024 / 1024
                print(f"  {key}")
                print(f"  -> Size: {size_mb:.2f} MB\n")
                count += 1
                found_btc = True
                if count >= 10:  # Only show first 10 to keep output manageable
                    break
        if count >= 10:
            break
            
    if not found_btc:
        print("No BTC pairs found in this hour. Trying a different symbol filter...")
        # Just list all files in the hour to see what's there
        for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
            for obj in page.get('Contents', []):
                key = obj['Key']
                size_mb = obj['Size'] / 1024 / 1024
                print(f"  {key} ({size_mb:.2f} MB)")
                count += 1
                if count >= 20:
                    break
            if count >= 20:
                break

except Exception as e:
    print(f"Failed: {type(e).__name__}: {e}")