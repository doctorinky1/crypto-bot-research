import pandas as pd
import numpy as np

WALLET_FILE = 'hl_wallet_minute.parquet'
MINUTE_FILE = 'hl_minute.parquet'

TRAIN_START = pd.Timestamp('2026-08-17', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-08-24', tz='UTC')
TEST_START  = pd.Timestamp('2026-08-24', tz='UTC')
TEST_END    = pd.Timestamp('2026-09-21', tz='UTC')

HL_COST = 0.00090   # 0.045% per side × 2

MIN_ACTIVE_MINUTES = 50
MIN_ACTIVE_DAYS = 3
MIN_TOTAL_VOL = 0.5
SHRINK_K = 100


print("Loading data...")
wm = pd.read_parquet(WALLET_FILE)
mm = pd.read_parquet(MINUTE_FILE)
wm['minute'] = pd.to_datetime(wm['minute'], utc=True)
mm['minute'] = pd.to_datetime(mm['minute'], utc=True)
mm = mm.set_index('minute').sort_index()
mm = mm[~mm.index.duplicated(keep='last')]
mm['ret_next'] = mm['vwap'].shift(-1) / mm['vwap'] - 1

print(f"Wallet-minutes total: {len(wm):,}")
print(f"Minute bars total:    {len(mm):,}\n")

# ---------------------------------------------------------------
# Split
# ---------------------------------------------------------------
train = wm[(wm['minute'] >= TRAIN_START) & (wm['minute'] < TRAIN_END)].copy()
test  = wm[(wm['minute'] >= TEST_START)  & (wm['minute'] < TEST_END)].copy()

print(f"Train: {len(train):,} wallet-minutes across "
      f"{(TRAIN_END - TRAIN_START).days} days")
print(f"Test:  {len(test):,} wallet-minutes across "
      f"{(TEST_END - TEST_START).days} days\n")

# ---------------------------------------------------------------
# Score wallets on the training period
# ---------------------------------------------------------------
train['signed_flow'] = train['buy_vol'] - train['sell_vol']
train = train.merge(
    mm[['ret_next']], left_on='minute', right_index=True, how='left'
)

print("Scoring wallets...")
def score_wallet(g):
    n = len(g)
    if n < MIN_ACTIVE_MINUTES:
        return None
    valid = g.dropna(subset=['signed_flow', 'ret_next'])
    if len(valid) < MIN_ACTIVE_MINUTES:
        return None
    corr = valid['signed_flow'].corr(valid['ret_next'])
    if pd.isna(corr):
        return None
    total_vol = g['total_vol'].sum()
    active_days = g['minute'].dt.date.nunique()
    if total_vol < MIN_TOTAL_VOL or active_days < MIN_ACTIVE_DAYS:
        return None
    shrunk = corr * n / (n + SHRINK_K)
    return pd.Series({
        'corr_raw': corr,
        'corr_shrunk': shrunk,
        'n_minutes': n,
        'active_days': active_days,
        'total_vol_btc': total_vol,
        'trade_count': g['trade_count'].sum(),
    })

wallet_scores = train.groupby('wallet').apply(score_wallet, include_groups=False).dropna()
print(f"Wallets passing filter: {len(wallet_scores):,}\n")

# ---------------------------------------------------------------
# Print top of the ranking
# ---------------------------------------------------------------
wallet_scores = wallet_scores.sort_values('corr_shrunk', ascending=False)
print("=" * 90)
print("TOP 20 WALLETS BY SHRUNKEN CORRELATION")
print("=" * 90)
print(wallet_scores.head(20).to_string())
print("\n" + "=" * 90)
print("BOTTOM 10 WALLETS (systematically WRONG — anti-signal)")
print("=" * 90)
print(wallet_scores.tail(10).to_string())
print()

# ---------------------------------------------------------------
# Build smart-money flow signals on the test period
# ---------------------------------------------------------------
test['signed_flow'] = test['buy_vol'] - test['sell_vol']
test = test.merge(
    mm[['ret_next']], left_on='minute', right_index=True, how='left'
)

# Also need same-minute return for comparison
mm['ret_same'] = mm['vwap'].pct_change()
test = test.merge(
    mm[['ret_same']], left_on='minute', right_index=True, how='left'
)

# Which of the selected wallets are actually active in the test period?
for top_n in [50, 100, 500]:
    top_wallets = set(wallet_scores.head(top_n).index)
    active_in_test = test[test['wallet'].isin(top_wallets)]['wallet'].nunique()
    test_minutes = test[test['wallet'].isin(top_wallets)]['minute'].nunique()
    print(f"Top {top_n:>3}: {active_in_test:>4} / {top_n} wallets active in test, "
          f"covering {test_minutes:>6,} minutes "
          f"({test_minutes/len(mm.loc[TEST_START:TEST_END])*100:.1f}% of test minutes)")

print()

# ---------------------------------------------------------------
# Compute aggregate vs smart-money flow per minute in the test period
# ---------------------------------------------------------------
def build_flow(trades_df, wallet_set=None, label='flow'):
    """Return per-minute flow imbalance."""
    df = trades_df
    if wallet_set is not None:
        df = df[df['wallet'].isin(wallet_set)]
    agg = df.groupby('minute').agg(
        buy_vol=('buy_vol', 'sum'),
        sell_vol=('sell_vol', 'sum'),
        total_vol=('total_vol', 'sum'),
    )
    agg['flow_imb'] = (agg['buy_vol'] - agg['sell_vol']) / agg['total_vol'].replace(0, np.nan)
    agg = agg.rename(columns={'flow_imb': label})
    return agg[[label]]

# Aggregate (all wallets) — baseline
agg_flow = build_flow(test, wallet_set=None, label='aggregate')

# Smart money variants
top50 = set(wallet_scores.head(50).index)
top100 = set(wallet_scores.head(100).index)
top500 = set(wallet_scores.head(500).index)

sm50 = build_flow(test, wallet_set=top50, label='sm50')
sm100 = build_flow(test, wallet_set=top100, label='sm100')
sm500 = build_flow(test, wallet_set=top500, label='sm500')

# Combine with minute-level returns
combo = mm.loc[TEST_START:TEST_END, ['vwap', 'ret_next', 'ret_same']].copy()
combo = combo.join(agg_flow).join(sm50).join(sm100).join(sm500)
combo = combo.dropna(subset=['ret_next'])

print("=" * 90)
print("CORRELATION WITH NEXT-MINUTE RETURN (test period)")
print("=" * 90)
print(f"{'Signal':>12}  {'n':>7}  {'corr_next':>11}  {'corr_same':>11}")
for sig in ['aggregate', 'sm50', 'sm100', 'sm500']:
    v = combo.dropna(subset=[sig])
    if len(v) < 50:
        print(f"{sig:>12}  insufficient data")
        continue
    c_next = v[sig].corr(v['ret_next'])
    c_same = v[sig].corr(v['ret_same'])
    print(f"{sig:>12}  {len(v):>7,}  {c_next:>+11.4f}  {c_same:>+11.4f}")

# ---------------------------------------------------------------
# Horizon test on the strongest signal
# ---------------------------------------------------------------
print("\n" + "=" * 90)
print("HORIZON TEST — cost = {:.3f}% round-trip".format(HL_COST * 100))
print("=" * 90)

def horizon_report(signal_name, threshold):
    sig = combo[signal_name]
    z = (sig - sig.mean()) / sig.std()
    entries = np.sign(z) * (z.abs() > threshold)
    print(f"\nSignal = {signal_name}   Threshold |z| > {threshold}")
    print(f"  {'Horizon':>8}  {'n':>7}  {'win%':>7}  {'gross%':>10}  {'net%':>10}  {'cum%':>12}")
    for h in [1, 2, 5, 15, 30]:
        fwd = mm['vwap'].shift(-h) / mm['vwap'] - 1
        fwd = fwd.loc[TEST_START:TEST_END]
        gross = entries * fwd
        trades = gross.dropna()[gross.dropna() != 0]
        if len(trades) == 0:
            continue
        net = trades - HL_COST
        wins = (net > 0).sum()
        cum = (1 + net).prod() - 1
        print(f"  {h:>7}m  {len(trades):>7,}  {wins/len(trades)*100:>6.1f}%  "
              f"{trades.mean()*100:>9.4f}%  {net.mean()*100:>9.4f}%  {cum*100:>11.2f}%")

horizon_report('aggregate', 1.0)
horizon_report('sm500', 1.0)
horizon_report('sm100', 1.0)
horizon_report('sm50', 1.0)

print("\n" + "=" * 90)
print("INTERPRETATION")
print("=" * 90)
print("If sm50/sm100/sm500 corr_next >> aggregate corr_next:")
print("  → Smart-money filter is working. Their flow is genuinely more predictive.")
print("If sm*_corr ≈ aggregate corr:")
print("  → Wallet ranking is noise. Aggregate flow already contains all information.")
print("If sm*_corr < aggregate corr:")
print("  → Top-ranked wallets are overfit to training week. Classic look-ahead failure.")
print()
print("Watch the horizon table for sm* — even if net is still negative,")
print("a larger gross% than aggregate would be a real finding.")