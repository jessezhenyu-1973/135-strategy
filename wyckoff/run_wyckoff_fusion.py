#!/usr/bin/env python3
"""
威科夫×135 — 步骤②: 组合层信号融合
把 威科夫 S1(Spring) 与 135 V18 作为两个候选信号源, 同一只股票内顺序竞争
(先到先得, 吊灯止损, 20日冷却), 在 单票层面比较 "V18+WyckoffS1" vs "V18-only"
是否提升; 同时报 跨票组合层(10%×5只) 净值。

判定标准(与135一致): 全池≥60% 股票 融合>V18-only 才落地。
用法:
  python3 run_wyckoff_fusion.py            # 全池
  python3 run_wyckoff_fusion.py --top 30
"""
import os
import sys
import csv
import argparse
import statistics as st

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history  # noqa: E402
from run_joint_validation import extract_segments, portfolio_simulate  # noqa: E402
from run_wyckoff_s1_shallow import s1_shallow_segments  # noqa: E402


def single_equity(segs):
    eq = 1.0
    for s in segs:
        if s.get('entry_price') and s['entry_price'] > 0:
            eq *= 1.0 + (s['exit_price'] - s['entry_price']) / s['entry_price']
    return eq


def merged_segs_v18_wyckoff(df, use_r1=True):
    """V18 段 + 威科夫 S1(纯Spring, depth=9.9 不限深) 段, 按入场日合并去重"""
    v18 = extract_segments(df, 'atr')
    wy = s1_shallow_segments(df, use_r1_exit=use_r1, depth=9.9)
    both = [dict(s, src='v18') for s in v18] + [dict(s, src='wyckoff') for s in wy]
    # 同日同股: V18优先(已验证配置), 丢弃威科夫重复日
    seen, out = set(), []
    for s in sorted(both, key=lambda x: (x['entry_date'], x['src'] != 'v18')):
        k = (s['entry_date'], s['exit_date'])
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--cash', type=float, default=1e6)
    args = ap.parse_args()
    n = args.top if args.top > 0 else 300

    codes = get_hs300_codes(n)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df
    print(f'获取沪深300(前{n})... 可用 {len(datasets)} 只')

    prices = {c: dict(zip(df.index.strftime('%Y%m%d'), df['close']))
              for c, df in datasets.items()}
    calendar = sorted(set(d for df in datasets.values()
                          for d in df.index.strftime('%Y%m%d')))

    segs_v, segs_f, eq_v, eq_f = {}, {}, {}, {}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        sv = extract_segments(df, 'atr')
        segs_v[code] = sv
        segs_f[code] = merged_segs_v18_wyckoff(df)
        eq_v[code] = single_equity(sv)
        eq_f[code] = single_equity(segs_f[code])
        if (i + 1) % 50 == 0:
            print(f'  ...{i+1}/{len(datasets)}')

    # ---- 单票占优 (核心判定) ----
    n_st = len(eq_v)
    n_win = sum(1 for c in eq_v if eq_f[c] > eq_v[c])
    n_tie = sum(1 for c in eq_v if abs(eq_f[c] - eq_v[c]) < 1e-9)
    med_v = st.median([v - 1 for v in eq_v.values()]) if eq_v else 0
    med_f = st.median([v - 1 for v in eq_f.values()]) if eq_f else 0

    # ---- 跨票组合层净值 ----
    res_v = portfolio_simulate(segs_v, prices, calendar, args.cash)
    res_f = portfolio_simulate(segs_f, prices, calendar, args.cash)
    rv = res_v['total_return'] / res_v['max_drawdown'] if res_v['max_drawdown'] else 0
    rf = res_f['total_return'] / res_f['max_drawdown'] if res_f['max_drawdown'] else 0

    print(f"\n{'='*62}")
    print(f"V18+威科夫S1融合  vs  V18-only  [{n_st}只]")
    print(f"--- 单票顺序复利 (落地判定) ---")
    print(f"单票占优率 (融合>V18-only): {n_win}/{n_st} = {n_win/max(n_st,1)*100:.1f}%  "
          f"(平 {n_tie}, 落地线≥60%)")
    print(f"单票中位收益: V18-only {med_v:+.1%}  →  融合 {med_f:+.1%}")
    print(f"--- 跨票组合层 (10%×5只, 先到先得) ---")
    print(f"{'指标':<14}{'V18-only':>16}{'V18+Wyckoff':>18}")
    for k, lab in [('total_return', '总收益%'), ('n_trades', '交易数'),
                   ('max_drawdown', '最大回撤%')]:
        print(f"{lab:<14}{res_v[k]:>16}{res_f[k]:>18}")
    print(f"{'收益/回撤比':<13}{rv:>16.2f}{rf:>18.2f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wyckoff_fusion_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['single_stock_winrate', n_win, n_st,
                    round(n_win / max(n_st, 1) * 100, 1)])
        w.writerow(['v18_only', res_v['total_return'], res_v['n_trades'],
                    res_v['max_drawdown'], round(rv, 2)])
        w.writerow(['v18_wyckoff_fusion', res_f['total_return'], res_f['n_trades'],
                    res_f['max_drawdown'], round(rf, 2)])
    print(f'\n结果: {out}')


if __name__ == '__main__':
    main()
