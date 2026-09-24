#!/usr/bin/env python3
"""
威科夫 — S1-only + 浅破收紧探针 (步骤1)
Spring 按 ZeaFx 三型: 深破(Spring#1,放量)最危险 → 加 下穿深度≤SPRING_DEPTH 约束,
只保留缩量浅破型(Spring#2/#3)。全池266只, 对照 V18-ATR。
用法: python3 run_wyckoff_s1_shallow.py [--depth 0.03]
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_wyckoff_backtest as R  # noqa: E402
from run_param_sensitivity import get_hs300_codes, get_stock_history  # noqa: E402
from run_joint_validation import extract_segments, portfolio_simulate  # noqa: E402
from wyckoff_signals import detect_wyckoff, WyckoffParams  # noqa: E402


def s1_shallow_segments(df, use_r1_exit=True, depth=0.03, time_stop=0):
    """S1-only + 浅破约束(下穿深度≤depth×tr_low) + ATR吊灯/R1离场 + 20日冷却"""
    p = WyckoffParams()
    p.SPRING_DEPTH = depth
    sig = detect_wyckoff(df, p=p)
    if sig.empty:
        return []
    buys = sig[sig['sig'] == 'S1'].copy()
    r1 = sig[sig['sig'] == 'R1'].copy()
    c = df['close']
    trv = pd.concat([df['high'] - df['low'],
                     (df['high'] - c.shift()).abs(),
                     (df['low'] - c.shift()).abs()], axis=1).max(axis=1)
    atr = trv.rolling(14, min_periods=7).mean()
    r1_dates = set(r1['date']) if len(r1) else set()
    bm = {}
    for s in buys.itertuples():
        bm.setdefault(s.date, []).append(s)

    segs, cd, pos = [], None, None
    idx = df.index
    ca, aa = df['close'].to_numpy(), atr.to_numpy()
    ymd = lambda t: t.strftime('%Y%m%d')
    for i in range(60, len(df)):
        d = str(idx[i].date())
        if pos:
            hi = max(pos['highest'], ca[i])
            ch = hi - 2.5 * aa[i] if not np.isnan(aa[i]) else -1e18
            ex = ca[i] < max(pos['stop'], ch)
            if use_r1_exit and d in r1_dates and idx[i] > pos['entry_ts']:
                ex = True
            if time_stop and i - pos['entry_i'] >= time_stop:
                ex = True
            if ex:
                segs.append({'entry_date': pos['entry_date'], 'entry_price': pos['entry_px'],
                             'exit_date': ymd(idx[i]), 'exit_price': float(ca[i]),
                             'sig': pos['sig']})
                pos, cd = None, idx[i]
            continue
        if cd is not None and (idx[i] - cd).days <= 20:
            continue
        rows = bm.get(d, [])
        if not rows:
            continue
        s = rows[0]
        j = i + 1
        if j >= len(df) or pd.isna(s.entry) or s.entry <= 0:
            continue
        pos = {'entry_i': j, 'entry_date': ymd(idx[j]), 'entry_px': float(s.entry),
               'stop': float(s.stop), 'highest': float(s.entry), 'sig': s.sig,
               'entry_ts': idx[j]}
    if pos:
        i = len(df) - 1
        segs.append({'entry_date': pos['entry_date'], 'entry_price': pos['entry_px'],
                     'exit_date': ymd(idx[i]), 'exit_price': float(ca[i]),
                     'sig': pos['sig'] + '_eod'})
    return segs


def single_equity(segs):
    eq = 1.0
    for s in segs:
        if s['entry_price'] > 0:
            eq *= 1.0 + (s['exit_price'] - s['entry_price']) / s['entry_price']
    return eq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=float, default=0.03)
    ap.add_argument('--no-r1', action='store_true')
    args = ap.parse_args()

    codes = get_hs300_codes(300)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df
    print(f'可用数据 {len(datasets)} 只, 浅破深度={args.depth:.0%}')

    prices = {c: dict(zip(df.index.strftime('%Y%m%d'), df['close'])) for c, df in datasets.items()}
    calendar = sorted(set(d for df in datasets.values() for d in df.index.strftime('%Y%m%d')))

    segs_w, segs_v, eq_w, eq_v = {}, {}, {}, {}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        segs_w[code] = s1_shallow_segments(df, use_r1_exit=not args.no_r1, depth=args.depth)
        segs_v[code] = extract_segments(df, 'atr')
        eq_w[code] = single_equity(segs_w[code])
        eq_v[code] = single_equity(segs_v[code])
        if (i + 1) % 50 == 0:
            print(f'  ...{i+1}/{len(datasets)}')

    res_w = portfolio_simulate(segs_w, prices, calendar, 1e6)
    res_v = portfolio_simulate(segs_v, prices, calendar, 1e6)
    n = len(eq_w)
    wins = sum(1 for c in eq_w if eq_w[c] > eq_v[c])
    import statistics as st
    r1_on = 'R1开' if not args.no_r1 else 'R1关'
    print(f"\n{'='*62}")
    print(f"威科夫 S1-only 浅破≤{args.depth:.0%} ({r1_on})  vs  V18-ATR  [{n}只]")
    print(f"{'指标':<14}{'威科夫S1浅破':>18}{'V18-ATR':>18}")
    for k, lab in [('total_return', '总收益%'), ('n_trades', '交易数'),
                   ('win_rate', '胜率%'), ('max_drawdown', '最大回撤%')]:
        print(f"{lab:<14}{res_w[k]:>18}{res_v[k]:>18}")
    print(f"单票占优率: {wins}/{n} = {wins/max(n,1)*100:.1f}%  (落地线≥60%)")


if __name__ == '__main__':
    main()
