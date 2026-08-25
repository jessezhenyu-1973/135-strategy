#!/usr/bin/env python3
"""
135战法 — 任务7b: V18推荐参数全池样本外验证
对比 V17基准 vs V18推荐 在沪深300全部成分股上的表现。

用法:
    python3 run_full_pool_validation.py          # 全300只
    python3 run_full_pool_validation.py --top 50 # 前50只
"""

import subprocess
import json
import os
import tempfile
import datetime
import csv
import argparse
from run_param_sensitivity import (
    get_hs300_codes, get_stock_history, run_one,
)

V17 = dict(hx_vol_mult=1.0, yycs_vol_mult=2.0, jzjq_spread=0.015,
           jzjq_vol_mult=2.0, stop_loss_pct=0.08)
V18 = dict(hx_vol_mult=1.5, yycs_vol_mult=2.0, jzjq_spread=0.01,
           jzjq_vol_mult=2.0, stop_loss_pct=0.08)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0, help='0 = 全部')
    args = parser.parse_args()

    n = args.top if args.top > 0 else 300
    print(f"获取沪深300成分股 (前{n})...")
    codes = get_hs300_codes(n)
    datasets = {}
    for code in codes:
        df = get_stock_history(code)
        if df is not None:
            datasets[code] = df
    print(f"可用数据: {len(datasets)} 只，开始验证...\n")

    rows = []
    agg = {k: {'V17': [], 'V18': []} for k in
           ['total_return', 'n_trades', 'win_rate', 'avg_ret_per_trade']}
    v18_better = 0

    for i, (code, df) in enumerate(datasets.items()):
        r17 = run_one(df, V17)
        r18 = run_one(df, V18)
        s17 = r17['avg_ret_per_trade'] * (1 + r17['win_rate'] / 100)
        s18 = r18['avg_ret_per_trade'] * (1 + r18['win_rate'] / 100)
        if s18 > s17:
            v18_better += 1
        for k in agg:
            agg[k]['V17'].append(r17[k])
            agg[k]['V18'].append(r18[k])
        rows.append({'code': code, **{f'{k}_v17': round(v, 3) for k, v in r17.items()},
                     **{f'{k}_v18': round(v, 3) for k, v in r18.items()}})
        print(f"[{i+1}/{len(datasets)}] {code}: "
              f"V17 单笔{r17['avg_ret_per_trade']:+.2f}%/胜率{r17['win_rate']:.0f}% | "
              f"V18 单笔{r18['avg_ret_per_trade']:+.2f}%/胜率{r18['win_rate']:.0f}%"
              f" {'✓' if s18 > s17 else '✗'}")

    n_all = len(datasets)
    print(f"\n{'='*60}\n全池汇总 ({n_all} 只)\n{'='*60}")
    summary = {}
    for k in agg:
        m17 = sum(agg[k]['V17']) / n_all
        m18 = sum(agg[k]['V18']) / n_all
        summary[k] = (round(m17, 3), round(m18, 3))
        print(f"{k:20s}: V17={m17:>8.3f}   V18={m18:>8.3f}")
    print(f"\nV18 综合得分占优的股票: {v18_better}/{n_all} ({v18_better/n_all*100:.0f}%)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'full_pool_validation.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n明细已保存: {out}")


if __name__ == '__main__':
    main()
