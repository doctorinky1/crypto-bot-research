import boto3, io, os, gzip
from datetime import datetime, timedelta
from botocore.config import Config
import pandas as pd
import numpy as np

# ============================================================
# CONFIG
# ============================================================
API_KEY = "db96d463-7567-40e8-b744-7d2472938853"
BUCKET = 'coinapi'
ENDPOINT = 'https://s3.flatfiles.coinapi.io'
EXCHANGE = 'E-HYPERLIQUIDL4'

# 35 days: weeks 1 = train, weeks 2-5 = test
END_DATE = datetime(2026, 9, 21)
START_DATE = END_DATE - timedelta(days=35)

TRAIN_START = pd.Timestamp('2026-08-17', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-08-24', tz='UTC')
TEST_START  = pd.Timestamp('2026-08-24', tz='UTC')
TEST_END    = pd.Timestamp('2026-09-21', tz='UTC')

HL_COST = 0.00090   # 0.045% per side x2

ASSETS = {
    'BTC': {'symbol': 'SC-HYPERLIQUIDL4_PERP_BTC_USDC', 'cache': 'hl_cache_btc'},
    'ETH': {'symbol': 'SC-HYPERLIQUIDL4_PERP_ETH_USDC', 'cache': 'hl_cache_eth'},
    'SOL': {'symbol': 'SC-HYPERLIQUIDL4_PERP_SOL_USDC', 'cache': 'hl_cache_sol'},
}

s3 = boto3.client(
    's3',
    aws_access_key_id=API_KEY,
    aws_secret_access_key='coinapi',
    endpoint_url=ENDPOINT,
    config=Config(signature_version='s3v4', region_name='us-east-1'),
)


# ============================================================
# DATA DOWNLOAD
# ============================================================
def find_file(prefix, sym):
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=2000)
    for obj in resp.get('Contents', []):
        if sym in obj['Key'] and obj['Key'].endswith('.csv.gz'):
            return obj['Key']
    return None


def process_hour(gz_bytes):
    raw = gzip.decompress(gz_bytes)
    df = pd.read_csv(
        io.BytesIO(raw),
        sep=';',
        usecols=['time_coinapi', 'price', 'base_amount', 'taker_side', 'user_taker'],
    )
    df = df.dropna(subset=['user_taker'])
    df = df[df['base_amount'] > 0]
    if len(df) == 0:
        return None, None

    df['minute'] = pd.to_datetime(df['time_coinapi'], format='ISO8601', utc=True).dt.floor('1min')
    df['is_buy'] = df['taker_side'] == 'BUY'
    df['buy_vol'] = df['base_amount'].where(df['is_buy'], 0.0)
    df['sell_vol'] = df['base_amount'].where(~df['is_buy'], 0.0)
    df['notional'] = df['price'] * df['base_amount']

    wallet = df.groupby(['minute', 'user_taker'], sort=False).agg(
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        total_vol=('base_amount', 'sum'),
        notional=('notional', 'sum'),
        trade_count=('price', 'size'),
    ).reset_index().rename(columns={'user_taker': 'wallet'})

    minute = df.groupby('minute', sort=False).agg(
        total_vol=('base_amount', 'sum'),
        notional=('notional', 'sum'),
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        px_last=('price', 'last'),
    ).reset_index()
    minute['vwap'] = minute['notional'] / minute['total_vol']

    return wallet, minute


def download_asset(name, cfg):
    print(f"\n=== {name} — {cfg['symbol']} ===")
    cache = cfg['cache']
    wallet_path = f"{cache}_wallet.parquet"
    minute_path = f"{cache}_minute.parquet"

    if os.path.exists(wallet_path) and os.path.exists(minute_path):
        print(f"  Cached files exist — skipping download.")
        return

    os.makedirs(cache, exist_ok=True)
    cursor = START_DATE
    done = skipped = failed = 0

    while cursor < END_DATE:
        hk = cursor.strftime('%Y%m%d%H')
        wp = os.path.join(cache, f"{hk}_wallet.parquet")
        mp = os.path.join(cache, f"{hk}_minute.parquet")
        if os.path.exists(wp) and os.path.exists(mp):
            skipped += 1
            cursor += timedelta(hours=1)
            continue

        fk = find_file(f"T-TRADES/D-{hk}/{EXCHANGE}/", cfg['symbol'])
        if not fk:
            failed += 1
            cursor += timedelta(hours=1)
            continue

        try:
            gz = s3.get_object(Bucket=BUCKET, Key=fk)['Body'].read()
            w, m = process_hour(gz)
            if w is not None and len(w):
                w.to_parquet(wp)
                m.to_parquet(mp)
                done += 1
        except Exception as e:
            print(f"  {hk}: ERR {e}")
            failed += 1
        cursor += timedelta(hours=1)

    print(f"  Downloaded {done}, skipped {skipped}, failed {failed}")

    wallet_files = sorted(f for f in os.listdir(cache) if f.endswith('_wallet.parquet'))
    minute_files = sorted(f for f in os.listdir(cache) if f.endswith('_minute.parquet'))
    wdfs = [pd.read_parquet(os.path.join(cache, f)) for f in wallet_files]
    mdfs = [pd.read_parquet(os.path.join(cache, f)) for f in minute_files]
    combined_w = pd.concat(wdfs, ignore_index=True).sort_values('minute').reset_index(drop=True)
    combined_m = pd.concat(mdfs, ignore_index=True).sort_values('minute').reset_index(drop=True)
    combined_w.to_parquet(wallet_path)
    combined_m.to_parquet(minute_path)
    print(f"  Combined: {len(combined_w):,} wallet-rows, {len(combined_m):,} minute-bars")


# ============================================================
# WALLET SCORING (same as before)
# ============================================================
def score_wallets(wm_train, mm_train):
    train = wm_train.copy()
    train['signed_flow'] = train['buy_vol'] - train['sell_vol']
    mm = mm_train.copy()
    mm['ret_next'] = mm['vwap'].shift(-1) / mm['vwap'] - 1
    train = train.merge(mm[['ret_next']], left_on='minute', right_index=True, how='left')

    def _score(g):
        n = len(g)
        if n < 50: return None
        v = g.dropna(subset=['signed_flow', 'ret_next'])
        if len(v) < 50: return None
        c = v['signed_flow'].corr(v['ret_next'])
        if pd.isna(c): return None
        if g['total_vol'].sum() < 0.5 or g['minute'].dt.date.nunique() < 3: return None
        return c * n / (n + 100)

    scores = train.groupby('wallet').apply(_score, include_groups=False).dropna()
    return scores.sort_values(ascending=False)


# ============================================================
# COARSE-BAR TEST
# ============================================================
def coarse_test(wm, mm, top500, start, end, label=''):
    wm = wm.copy(); mm = mm.copy()
    wm['minute'] = pd.to_datetime(wm['minute'], utc=True)
    if 'minute' in mm.columns:
        mm['minute'] = pd.to_datetime(mm['minute'], utc=True)
        mm = mm.set_index('minute')
    else:
        mm.index = pd.to_datetime(mm.index, utc=True)
    mm = mm.sort_index()
    mm = mm[~mm.index.duplicated(keep='last')]

    results = []
    for bar_size, blabel in [('5min','5m'), ('15min','15m'), ('1h','1h'), ('4h','4h')]:
        wm_b = wm.copy()
        wm_b['bar'] = wm_b['minute'].dt.floor(bar_size)
        w_agg = wm_b.groupby(['bar','wallet']).agg(
            buy_vol=('buy_vol','sum'),
            sell_vol=('sell_vol','sum'),
            total_vol=('total_vol','sum'),
        ).reset_index()

        mm_b = mm.copy()
        mm_b['bar'] = mm_b.index.floor(bar_size)
        m_agg = mm_b.groupby('bar').agg(
            notional=('notional','sum'),
            total_vol=('total_vol','sum'),
        )
        m_agg['vwap'] = m_agg['notional'] / m_agg['total_vol']
        m_agg['ret_next'] = m_agg['vwap'].shift(-1) / m_agg['vwap'] - 1

        # Aggregate flow (all wallets)
        agg_flow = w_agg.groupby('bar').agg(
            b=('buy_vol','sum'), s=('sell_vol','sum'), t=('total_vol','sum')
        )
        agg_flow['aggregate'] = (agg_flow['b'] - agg_flow['s']) / agg_flow['t'].replace(0, np.nan)

        # Smart money flow (top500)
        sm = w_agg[w_agg['wallet'].isin(top500)]
        sm_flow = sm.groupby('bar').agg(
            b=('buy_vol','sum'), s=('sell_vol','sum'), t=('total_vol','sum')
        )
        sm_flow['sm500'] = (sm_flow['b'] - sm_flow['s']) / sm_flow['t'].replace(0, np.nan)

        combo = m_agg.join(agg_flow[['aggregate']]).join(sm_flow[['sm500']])
        combo = combo.dropna(subset=['ret_next'])
        test = combo.loc[start:end]
        if len(test) < 30:
            continue

        agg_c = test['aggregate'].corr(test['ret_next'])
        sm_c = test['sm500'].corr(test['ret_next'])

        # Aggregate strategy
        z = (test['aggregate'] - test['aggregate'].mean()) / test['aggregate'].std()
        s = np.sign(z) * (z.abs() > 1.0)
        gross = (s * test['ret_next']).dropna()
        gross = gross[gross != 0]
        agg_g = gross.mean() * 100 if len(gross) else float('nan')
        agg_n = (gross - HL_COST).mean() * 100 if len(gross) else float('nan')
        agg_cnt = len(gross)

        # Smart money strategy
        z = (test['sm500'] - test['sm500'].mean()) / test['sm500'].std()
        s = np.sign(z) * (z.abs() > 1.0)
        gross = (s * test['ret_next']).dropna()
        gross = gross[gross != 0]
        sm_g = gross.mean() * 100 if len(gross) else float('nan')
        sm_n = (gross - HL_COST).mean() * 100 if len(gross) else float('nan')
        sm_cnt = len(gross)

        results.append({
            'bar': blabel, 'n_bars': len(test),
            'agg_corr': agg_c, 'sm_corr': sm_c,
            'agg_n': agg_cnt, 'agg_gross%': agg_g, 'agg_net%': agg_n,
            'sm_n': sm_cnt, 'sm_gross%': sm_g, 'sm_net%': sm_n,
        })

    return pd.DataFrame(results)


# ============================================================
# MAIN
# ============================================================
def main():
    # --- Ensure data is downloaded ---
    for name, cfg in ASSETS.items():
        download_asset(name, cfg)

    # --- Load all three assets ---
    loaded = {}
    for name, cfg in ASSETS.items():
        wm = pd.read_parquet(f"{cfg['cache']}_wallet.parquet")
        mm = pd.read_parquet(f"{cfg['cache']}_minute.parquet")
        wm['minute'] = pd.to_datetime(wm['minute'], utc=True)
        mm['minute'] = pd.to_datetime(mm['minute'], utc=True)
        mm = mm.set_index('minute').sort_index()
        mm = mm[~mm.index.duplicated(keep='last')]
        loaded[name] = (wm, mm)

    # --- Print results per asset ---
    for name in ['BTC','ETH','SOL']:
        wm, mm = loaded[name]
        wm_train = wm[(wm['minute'] >= TRAIN_START) & (wm['minute'] < TRAIN_END)]
        mm_train = mm.loc[TRAIN_START:TRAIN_END]

        scores = score_wallets(wm_train, mm_train)
        top500 = set(scores.head(500).index)
        print(f"\n{name}: {len(scores):,} wallets passing filter, top500 selected.")

        # TEST period
        df = coarse_test(wm, mm, top500, TEST_START, TEST_END)
        print(f"\n--- {name} TEST PERIOD (weeks 2–5) ---")
        print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

        # TRAIN period (only BTC for brevity)
        if name == 'BTC':
            df_tr = coarse_test(wm, mm, top500, TRAIN_START, TRAIN_END)
            print(f"\n--- BTC TRAIN PERIOD (week 1, in-sample check) ---")
            print(df_tr.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print("\n" + "="*90)
    print("HOW TO READ THIS")
    print("="*90)
    print("agg_net% column is the number that matters: net expectancy per trade after cost.")
    print("Positive and consistent across BTC/ETH/SOL in the TEST period = real edge.")
    print("BTC train period should also be positive for consistency; if train is")
    print("much stronger than test, we may have been lucky in-sample.")


if __name__ == "__main__":
    main()