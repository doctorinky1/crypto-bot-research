import boto3
from botocore.config import Config

# --- EDIT THIS WITH YOUR FINFEED API KEY ---
FINFEED_API_KEY = "47d4256b-1907-42bd-96c0-3cd912a923e6"
# ------------------------------------------

s3 = boto3.client(
    's3',
    aws_access_key_id=FINFEED_API_KEY,
    aws_secret_access_key='FinFeedAPI',
    endpoint_url='https://s3.flatfiles.finfeedapi.com',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

print("=== Buckets ===")
try:
    buckets = s3.list_buckets()
    for b in buckets.get('Buckets', []):
        print(f"  {b['Name']}  (created {b.get('CreationDate')})")
except Exception as e:
    print(f"Failed: {type(e).__name__}: {e}")
    raise SystemExit

# For each bucket, peek at the top-level prefixes
for b in buckets.get('Buckets', []):
    name = b['Name']
    print(f"\n=== First 50 objects in bucket: {name} ===")
    try:
        resp = s3.list_objects_v2(Bucket=name, MaxKeys=50, Delimiter='/')
        # Show "folders" (common prefixes)
        for prefix in resp.get('CommonPrefixes', []):
            print(f"  [DIR]  {prefix['Prefix']}")
        # Show files
        for obj in resp.get('Contents', [])[:50]:
            print(f"  [FILE] {obj['Key']}  ({obj['Size']} bytes)")
    except Exception as e:
        print(f"  Failed: {type(e).__name__}: {e}")