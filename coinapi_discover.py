import boto3
from botocore.config import Config

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"  # db96d463...
s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',  # CoinAPI's static secret
    endpoint_url='https://s3.flatfiles.coinapi.io',
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)

print("=== Buckets accessible to your key ===")
try:
    buckets = s3.list_buckets()
    for b in buckets.get('Buckets', []):
        print(f"  {b['Name']}")
except Exception as e:
    print(f"Failed: {type(e).__name__}: {e}")