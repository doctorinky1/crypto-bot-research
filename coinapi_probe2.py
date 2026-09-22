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

# Test several hours — older ones are more likely to be fully populated
HOURS_TO_TEST = [
    'T-LIMITBOOK_FULL/D-2026092109/',
    'T-LIMITBOOK_FULL/D-2026092105/',
    'T-LIMITBOOK_FULL/D-2026092020/',
    'T-LIMITBOOK_FULL/D-2026091900/',
]

for PREFIX in HOURS_TO_TEST:
    print(f"\n{'='*70}")
    print(f"=== {PREFIX} ===")
    print('='*70)

    # List with NO delimiter to see every object recursively
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, MaxKeys=20)
        contents = resp.get('Contents', [])
        print(f"\nRecursive listing (first 20 objects):")
        if not contents:
            print("  (empty)")
        for obj in contents:
            size_kb = obj['Size'] / 1024
            print(f"  {obj['Key']}  ({size_kb:.1f} KB)")
        
        # Also list subfolders
        print(f"\nSubfolders (Delimiter='/'):")
        resp2 = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, Delimiter='/', MaxKeys=20)
        subfolders = resp2.get('CommonPrefixes', [])
        if not subfolders:
            print("  (none)")
        for p in subfolders:
            print(f"  [DIR] {p['Prefix']}")

    except Exception as e:
        print(f"  Failed: {type(e).__name__}: {e}")