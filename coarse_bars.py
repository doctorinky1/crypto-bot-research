import pandas as pd
import numpy as np

WALLET_FILE = 'hl_wallet_minute.parquet'
MINUTE_FILE = 'hl_minute.parquet'

TRAIN_START = pd.Timestamp('2026-08-17', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-08-24', tz='UTC')
TEST_START  = pd.Timestamp('2026-08-24', tz='UTC')
TEST_END    = pd.Timestamp('2026-09-21', tz='UTC')

HL_COST = 0.00090

# ---- Load ----
print("Loading...")
wm = pd.read_parquet(WALLET_FILE)
mm = pd.read_parquet(MINUTE_FILE)
wm['minute'] = pd.to_datetime(wm['minute'], utc=True)
mm['minute'] = pd.to_datetime(mm['minute'], utc=True)
mm = mm.set_index('minute').sort_index()
mm = mm[~mm.index.duplicated(keep='last')]

# ---- Recompute top 500 wallet scores on training period ----
train = wm[(wm['minute'] >= TRAIN_START) & (wm['minute'] < TRAIN_END)].copy()
train['signed_flow'] = train['buy_vol'] - train['sell_vol']

mm_train = mm.loc[TRAIN_START:TRAIN_END].copy()
mm_train['ret_next'] = mm_train['vwap'].shift(-1) / mm_train['vwap'] - 1

train = train.merge(mm_train[['ret_next']], left_on='minute', right_index=True, how='left')

def score(g):
    n = len(g)
    if n < 50: return None
    v = g.dropna(subset=['signed_flow', 'ret_next'])
    if len(v) < 50: return None
    c = v['signed_flow'].corr(v['ret_next'])
    if pd.isna(c): return None
    if g['total_vol'].sum() < 0.5 or g['minute'].dt.date.nunique() < 3: return None
    return c * n / (n + 100)

scores = train.groupby('wallet').apply(score, include_groups=False).dropna()
top500 = set(scores.sort_values(ascending=False).head(500).index)
print(f"Top 500 wallets selected from training period.\n")

# ---- Resample to coarser bars and test ----
# We'll test each bar size independently.
def resample_bars(bar_size):
    # Wallet-level aggregation to bar_size
    wm_sub = wm.copy()
    wm_sub['bar'] = wm_sub['minute'].dt.floor(bar_size)
    w_agg = wm_sub.groupby(['bar', 'wallet']).agg(
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        total_vol=('total_vol', 'sum'),
    ).reset_index()

    # Minute-level aggregation to bar_size for VWAP and returns
    mm_sub = mm.copy()
    mm_sub['bar'] = mm_sub.index.floor(bar_size)
    m_agg = mm_sub.groupby('bar').agg(
        notional=('notional', 'sum'),
        total_vol=('total_vol', 'sum'),
        px_last=('px_last', 'last'),
    )
    m_agg['vwap'] = m_agg['notional'] / m_agg['total_vol']
    m_agg['ret_next'] = m_agg['vwap'].shift(-1) / m_agg['vwap'] - 1

    # Aggregate flow per bar
    agg_flow = w_agg.groupby('bar').agg(
        b=('buy_vol', 'sum'), s=('sell_vol', 'sum'), t=('total_vol', 'sum')
    )
    agg_flow['aggregate'] = (agg_flow['b'] - agg_flow['s']) / agg_flow['t'].replace(0, np.nan)

    # Smart money flow per bar
    sm = w_agg[w_agg['wallet'].isin(top500)]
    sm_flow = sm.groupby('bar').agg(
        b=('buy_vol', 'sum'), s=('sell_vol', 'sum'), t=('total_vol', 'sum')
    )
    sm_flow['sm500'] = (sm_flow['b'] - sm_flow['s']) / sm_flow['t'].replace(0, np.nan)

    combo = m_agg.join(agg_flow[['aggregate']]).join(sm_flow[['sm500']])
    return combo.dropna(subset=['ret_next'])

print("=" * 90)
print(f"COARSE-BAR TEST — Hyperliquid BTC perp, cost = {HL_COST*100:.3f}%")
print("=" * 90)
print(f"{'Bar':>6}  {'n_test':>7}  {'agg_corr':>9}  {'sm500_corr':>11}  "
      f"{'agg_gross%':>11}  {'sm_gross%':>10}  {'sm_net%':>10}")
print("-" * 90)

for bar_size, label in [('5min', '5m'), ('15min', '15m'), ('1h', '1h'), ('4h', '4h')]:
    bars = resample_bars(bar_size)
    test = bars.loc[TEST_START:TEST_END]
    if len(test) < 50:
        print(f"{label:>6}  insufficient")
        continue

    # Correlations
    agg_c = test['aggregate'].corr(test['ret_next'])
    sm_c = test['sm500'].corr(test['ret_next'])

    # Threshold strategy: |z| > 1.0
    for sig_col, prefix in [('aggregate', 'agg'), ('sm500', 'sm')]:
        z = (test[sig_col] - test[sig_col].mean()) / test[sig_col].std()
        s = np.sign(z) * (z.abs() > 1.0)
        gross = (s * test['ret_next']).dropna()
        gross = gross[gross != 0]
        if sig_col == 'aggregate':
            agg_g = gross.mean() * 100
            agg_n = len(gross)
        else:
            sm_g = gross.mean() * 100
            sm_net = (gross - HL_COST).mean() * 100
            sm_n = len(gross)

    print(f"{label:>6}  {len(test):>7}  {agg_c:>+9.4f}  {sm_c:>+11.4f}  "
          f"{agg_g:>+10.4f}%  {sm_g:>+9.4f}%  {sm_net:>+9.4f}%")

print()
print("=" * 90)
print("WHAT TO LOOK FOR")
print("=" * 90)
print("1. Does sm500_corr stay > 0.2 as bars get coarser?")
print("   → The signal has real information content, not just microstructure noise.")
print()
print("2. Does sm_gross% grow faster than cost as bars get coarser?")
print("   → If gross% grows linearly with bar size but cost stays fixed, the")
print("     economics flip at some horizon.")
print()
print("3. Watch sm_net% — the first positive number changes everything.")