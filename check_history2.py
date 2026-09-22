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
EXCHANGE = 'E-HYPERLIQUIDL4'

# For each month, probe 3 different hours/days to rule out single-hour gaps
PROBES = [
    '20260805', '20260815', '20260825',  # Aug 2026 (known: data exists)
    '20260705', '20260715', '20260725',  # Jul 2026
    '20260605', '20260615', '20260625',  # Jun 2026
    '20260505', '20260515', '20260525',  # May 2026
    '20260405', '20260415', '20260425',  # Apr 2026
    '20260305', '20260315', '20260325',  # Mar 2026
    '20260205', '20260215', '20260225',  # Feb 2026
    '20260105', '20260115', '20260125',  # Jan 2026
    '20251205', '20251215', '20251225',  # Dec 2025
    '20250905', '20250915', '20250925',  # Sep 2025
    '20250605', '20250615', '20250625',  # Jun 2025
    '20250305', '20250315', '20250325',  # Mar 2025
    '20241205', '20241215', '20241225',  # Dec 2024
]

print(f"Probing Hyperliquid L4 data availability (multiple days per month)\n")
print(f"{'Month':>8}  {'Day-05':>10}  {'Day-15':>10}  {'Day-25':>10}")

current_month = None
for day_key in PROBES:
    month = day_key[:6]
    if month != current_month:
        if current_month is not None:
            print()  # blank line between months
        current_month = month

    # Probe this day at hour 12 (mid-day, more likely to have data)
    full_key = f"{day_key}12"
    prefix = f"T-TRADES/D-{full_key}/{EXCHANGE}/"
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=2)
        contents = resp.get('Contents', [])
        count = len(contents)
        status = f"{count} file(s)" if count else "empty"
    except Exception as e:
        status = f"ERR {type(e).__name__}"

    # Determine which slot this is in
    day_num = day_key[-2:]
    if day_num == '05':
        row = f"{month:>8}  {status:>10}"
    elif day_num == '15':
        row += f"  {status:>10}"
    elif day_num == '25':
        row += f"  {status:>10}"
        print(row)

print("\nDone.")