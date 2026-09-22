import boto3
from botocore.config import Config

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url='https://s3.flatfiles.coinapi.io',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

BUCKET = 'coinapi'

print(f"=== Top-level prefixes in {BUCKET} ===\n")
paginator = s3.get_paginator('list_objects_v2')
for page in paginator.paginate(Bucket=BUCKET, Delimiter='/'):
    for p in page.get('CommonPrefixes', []):
        print(f"  [DIR] {p['Prefix']}")

# Drill into the LIMITBOOK_FULL prefix if it exists
print(f"\n=== Contents of T-LIMITBOOK_FULL/ (first 100 entries) ===\n")
try:
    paginator2 = s3.get_paginator('list_objects_v2')
    count = 0
    for page in paginator2.paginate(Bucket=BUCKET, Prefix='T-LIMITBOOK_FULL/', Delimiter='/'):
        for p in page.get('CommonPrefixes', []):
            print(f"  [DIR] {p['Prefix']}")
            count += 1
            if count >= 100:
                break
        if count >= 100:
            break
except Exception as e:
    print(f"  Failed: {type(e).__name__}: {e}")