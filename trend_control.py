import pandas as pd
import numpy as np
import statsmodels.api as sm

ASSETS = {
    'BTC': ('hl_cache_btc_wallet.parquet', 'hl_cache_btc_minute.parquet'),
    'ETH': ('hl_cache_eth_wallet.parquet', 'hl_cache_eth_minute.parquet'),
    'SOL': ('hl_cache_sol_wallet.parquet', 'hl_cache_sol_minute.parquet'),
}

TEST_START = pd.Timestamp('2026-08-24', tz='UTC')
TEST_END   = pd.Timestamp('2026-09-21', tz='UTC')
HL_COST = 0.00090


def build_bars(wallet_file, minute_file, bar_size):
    wm = pd.read_parquet(wallet_file)
    mm = pd.read_parquet(minute_file)
    wm['minute'] = pd.to_datetime(wm['minute'], utc=True)
    mm['minute'] = pd.to_datetime(mm['minute'], utc=True)
    mm = mm.set_index('minute').sort_index()
    mm = mm[~mm.index.duplicated(keep='last')]

    wm['bar'] = wm['minute'].dt.floor(bar_size)
    w = wm.groupby('bar').agg(
        b=('buy_vol','sum'), s=('sell_vol','sum'), t=('total_vol','sum')
    )
    w['flow_imb'] = (w['b'] - w['s']) / w['t'].replace(0, np.nan)

    mm['bar'] = mm.index.floor(bar_size)
    m = mm.groupby('bar').agg(notional=('notional','sum'), total_vol=('total_vol','sum'))
    m['vwap'] = m['notional'] / m['total_vol']
    m['next_ret'] = m['vwap'].shift(-1) / m['vwap'] - 1
    m['past_ret'] = m['vwap'] / m['vwap'].shift(1) - 1

    combo = m.join(w[['flow_imb']]).dropna()
    combo['flow_z'] = (combo['flow_imb'] - combo['flow_imb'].rolling(42, min_periods=10).mean()) / combo['flow_imb'].rolling(42, min_periods=10).std()
    return combo


def trend_report(name, combo):
    test = combo.loc[TEST_START:TEST_END].dropna()
    if len(test) < 20:
        print(f"{name}: insufficient")
        return

    print(f"\n{'='*78}\n{name}\n{'='*78}")
    print(f"Test period: {len(test)} bars, "
          f"VWAP change: {(test['vwap'].iloc[-1]/test['vwap'].iloc[0]-1)*100:+.2f}%")

    # Regression: next_ret ~ flow_z + past_ret
    X = sm.add_constant(test[['flow_z','past_ret']])
    y = test['next_ret']
    model = sm.OLS(y, X, missing='drop').fit()
    print(f"\nRegression: next_ret ~ flow_z + past_ret")
    print(f"  flow_z coef:    {model.params['flow_z']:+.6f}   p={model.pvalues['flow_z']:.4f}")
    print(f"  past_ret coef:  {model.params['past_ret']:+.6f}   p={model.pvalues['past_ret']:.4f}")
    print(f"  R^2:            {model.rsquared:.4f}")

    # Split by past_ret sign: does flow still work in down bars?
    for regime, mask in [('UP past_ret > 0', test['past_ret'] > 0),
                         ('DOWN past_ret < 0', test['past_ret'] < 0)]:
        sub = test[mask].copy()
        z = (sub['flow_z'] - sub['flow_z'].mean()) / sub['flow_z'].std()
        s = np.sign(z) * (z.abs() > 1.0)
        gross = (s * sub['next_ret']).dropna()
        gross = gross[gross != 0]
        if len(gross) < 5:
            print(f"\n  {regime}: too few trades")
            continue
        net = gross.mean() - HL_COST
        wins = ((gross - HL_COST) > 0).sum() / len(gross) * 100
        print(f"\n  {regime}: n={len(gross):>3}  gross={gross.mean()*100:+.4f}%  "
              f"net={net*100:+.4f}%  win%={wins:.1f}")


def main():
    for asset, (wf, mf) in ASSETS.items():
        print(f"\n\n### {asset} ###")
        for bar_size in ['1h', '4h']:
            combo = build_bars(wf, mf, bar_size)
            trend_report(f"{asset} @ {bar_size}", combo)


if __name__ == "__main__":
    main()