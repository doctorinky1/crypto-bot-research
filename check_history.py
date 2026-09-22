import boto3
from botocore.config import Config

API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
s3 = boto3.client('s3', aws_access_key_id=API_KEY,
                  aws_secret_access_key='coinapi',
                  endpoint_url='https://s3.flatfiles.coinapi.io',
                  config=Config(signature_version='s3v4', region_name='us-east-1'))

# Binary search for the earliest available hour
import datetime
for probe_month in ['202601', '202512', '202509', '202506', '202503', '202412', '202409', '202406', '202403', '202401', '202312']:
    prefix = f"T-TRADES/D-{probe_month}0100/E-HYPERLIQUIDL4/"
    try:
        resp = s3.list_objects_v2(Bucket='coinapi', Prefix=prefix, MaxKeys=5)
        contents = resp.get('Contents', [])
        if contents:
            print(f"  {probe_month}: {len(contents)} files found")
        else:
            print(f"  {probe_month}: empty")
    except Exception as e:
        print(f"  {probe_month}: error {e}")