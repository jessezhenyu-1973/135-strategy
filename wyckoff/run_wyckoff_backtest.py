#!/usr/bin/env python3
"""
威科夫战法 — 任务14: 信号层回测 + V18-ATR 对照组
口径与135项目一致:
  - 数据: 沪深300 (hithink-finance, 前复权, 20230101起)
  - 组合层: 单笔10%资金, 最多同时5只, 先到先得 (复用 run_joint_validation.portfolio_simulate)
  - 对照: V18-ATR (135信号 + ATR14×2.5吊灯止损)
威科夫信号: S1 Spring缩量收回 / S2 Test缩量再探 / S3 SOS放量突破
  出场: max(信号结构止损, 吊灯止损最高价-2.5×ATR14), 收盘跌破离场; 可选R1顶部Upthrust离场
  单只持仓时后续信号跳过; 离场后冷却20日
用法:
  python3 run_wyckoff_backtest.py --top 30        # 快速
  python3 run_wyckoff_backtest.py                 # 全池300
  python3 run_wyckoff_backtest.py --no-r1         # 关闭R1顶部离场
"""
import os
import sys
import csv
import argparse
import tempfile
import statistics as st
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs'))
from run_param_sensitivity import get_hs300_codes, get_stock_history, df_to_csv  # noqa: E402
from run_joint_validation import portfolio_simulate, extract_segments  # noqa: E402
from wyckoff_signals import detect_wyckoff, WyckoffParams  # noqa: E402
import numpy as np

import pandas as pd


def wyckoff_segments(df, use_r1_exit=True, time_stop=0):
    """把威科夫信号转成135口径的持仓段(entry/exit日+价), 单只顺序持仓+20日冷却。
    出场: close < max(结构止损, 吊灯止损(最高close-2.5×ATR14)) | R1预警次日 | 期末虚拟平仓
    返回: [{'entry_date','entry_price','exit_date','exit_price','sig'}]
    """
    p = WyckoffParams()
    sig = detect_wyckoff(df)
    if sig.empty:
        return []
    c = df['close']
    trv = pd.concat([df['high'] - df['low'],
                     (df['high'] - c.shift()).abs(),
                     (df['low'] - c.shift()).abs()], axis=1).max(axis=1)
    atr = trv.rolling(14, min_periods=7).mean()

    buys = sig[sig['sig'].isin(['S1', 'S2', 'S3'])].copy()
    r1 = sig[sig['sig'] == 'R1'].copy()
    r1_dates = set(r1['date']) if len(r1) else set()   # 字符串 YYYY-MM-DD
    buy_map = {}
    for s in buys.itertuples():
        buy_map.setdefault(s.date, []).append(s)

    segs, cd_until, pos = [], None, None  # pos: dict(entry_i, entry_date, entry_px, stop, highest, sig)
    idx = df.index
    close_arr = df['close'].to_numpy()
    atr_arr = atr.to_numpy()
    ymd = lambda ts: ts.strftime('%Y%m%d')

    for i in range(60, len(df)):
        d = str(idx[i].date())
        # ---- 持仓中: 检查离场 ----
        if pos:
            highest = max(pos['highest'], close_arr[i])
            chand = highest - 2.5 * atr_arr[i] if not np.isnan(atr_arr[i]) else -1e18
            stop = max(pos['stop'], chand)
            exit_now = close_arr[i] < stop
            if use_r1_exit and d in r1_dates and idx[i] > pos['entry_ts']:
                exit_now = True
            if time_stop and i - pos['entry_i'] >= time_stop:
                exit_now = True
            if exit_now:
                segs.append({'entry_date': pos['entry_date'], 'entry_price': pos['entry_px'],
                             'exit_date': ymd(idx[i]), 'exit_price': float(close_arr[i]),
                             'sig': pos['sig']})
                pos = None
                cd_until = idx[i]
            continue
        # 冷却期
        if cd_until is not None and (idx[i] - cd_until).days <= 20:
            continue
        # ---- 空仓: 当日信号入场(入场价=次日开盘, 持仓段入场日=次日) ----
        rows = buy_map.get(d, [])
        if not rows:
            continue
        s = rows[0]
        j = i + 1
        if j >= len(df) or pd.isna(s.entry) or s.entry <= 0:
            continue
        pos = {'entry_i': j, 'entry_date': ymd(idx[j]), 'entry_px': float(s.entry),
               'stop': float(s.stop), 'highest': float(s.entry), 'sig': s.sig,
               'entry_ts': idx[j]}
    if pos:  # 期末虚拟平仓
        i = len(df) - 1
        segs.append({'entry_date': pos['entry_date'], 'entry_price': pos['entry_px'],
                     'exit_date': ymd(idx[i]), 'exit_price': float(close_arr[i]),
                     'sig': pos['sig'] + '_eod'})
    return segs


def single_stock_equity(segs):
    """单票顺序复利净值 (不扣费, 与组合口径一致)"""
    eq = 1.0
    for s in segs:
        if s['entry_price'] > 0:
            eq *= 1.0 + (s['exit_price'] - s['entry_price']) / s['entry_price']
    return eq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--no-r1', action='store_true', help='关闭R1顶部Upthrust离场')
    ap.add_argument('--s1-only', action='store_true', help='仅用S1 Spring信号(不含S2/S3)')
    ap.add_argument('--cash', type=float, default=1e6)
    args = ap.parse_args()
    n = args.top if args.top > 0 else 300
    use_r1 = not args.no_r1

    print(f'获取沪深300(前{n})...')
    codes = get_hs300_codes(n)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df
    print(f'可用数据 {len(datasets)} 只')

    prices_by_code = {c: dict(zip(df.index.strftime('%Y%m%d'), df['close']))
                      for c, df in datasets.items()}
    calendar = sorted(set(d for df in datasets.values() for d in df.index.strftime('%Y%m%d')))

    print('提取威科夫持仓段 + V18-ATR对照组...')
    segs_wyck, segs_v18, eqs_wyck, eqs_v18 = {}, {}, {}, {}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        segs_wyck[code] = wyckoff_segments(df, use_r1_exit=use_r1)
        segs_v18[code] = extract_segments(df, 'atr')
        eqs_wyck[code] = single_stock_equity(segs_wyck[code])
        eqs_v18[code] = single_stock_equity(segs_v18[code])
        if (i + 1) % 30 == 0:
            print(f'  ...{i+1}/{len(datasets)}')

    r1_on = 'R1离场=开' if use_r1 else 'R1离场=关'
    res_w = portfolio_simulate(segs_wyck, prices_by_code, calendar, args.cash)
    res_v = portfolio_simulate(segs_v18, prices_by_code, calendar, args.cash)
    ratio_w = res_w['total_return'] / res_w['max_drawdown'] if res_w['max_drawdown'] else 0
    ratio_v = res_v['total_return'] / res_v['max_drawdown'] if res_v['max_drawdown'] else 0

    # 单票占优 (全池标准)
    n_st = len(eqs_wyck)
    n_win = sum(1 for c in eqs_wyck if eqs_wyck[c] > eqs_v18[c])
    med_w = st.median(v - 1 for v in eqs_wyck.values()) if eqs_wyck else 0
    med_v = st.median(v - 1 for v in eqs_v18.values()) if eqs_v18 else 0

    print(f"\n{'='*62}")
    print(f"威科夫 S1/S2/S3 + ATR吊灯止损 ({r1_on})  vs  135 V18-ATR  [{n_st}只, 组合10%×5]")
    print(f"{'指标':<14}{'威科夫':>16}{'V18-ATR(对照)':>20}")
    for k, lab in [('total_return', '总收益%'), ('n_trades', '交易数'),
                   ('win_rate', '胜率%'), ('max_drawdown', '最大回撤%')]:
        print(f"{lab:<14}{res_w[k]:>16}{res_v[k]:>20}")
    print(f"{'收益/回撤比':<13}{ratio_w:>16.2f}{ratio_v:>20.2f}")
    print(f"{'单票中位收益':<13}{med_w:>16.1%}{med_v:>20.1%}")
    print(f"单票占优率: {n_win}/{n_st} = {n_win/max(n_st,1)*100:.0f}%  (落地线≥60%)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wyckoff_backtest_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['scheme', 'total_return', 'n_trades', 'win_rate', 'max_drawdown', 'ret_dd_ratio'])
        w.writerow([f'wyckoff_{r1_on}'] + [res_w[k] for k in ('total_return', 'n_trades', 'win_rate', 'max_drawdown')] + [round(ratio_w, 2)])
        w.writerow(['v18_atr'] + [res_v[k] for k in ('total_return', 'n_trades', 'win_rate', 'max_drawdown')] + [round(ratio_v, 2)])
        w.writerow(['single_stock_winrate', n_win, n_st, round(n_win / max(n_st, 1) * 100, 1), '', ''])
    print(f'\n结果: {out}')


if __name__ == '__main__':
    main()
