#!/usr/bin/env python3
"""
威科夫交易法 — 任务14: TR/Spring/Test/SOS 检测 (量化工化)
最小信号集:
  S1 Spring  — 底部TR内 跌破下界后当日/次日收盘收回区间 + 下穿缩量
  S2 Test    — Spring 后10日内再探底(低点抬高或持平)+缩量 → 确认加仓点
  S3 SOS     — 放量收上TR上界 (给无Spring的Schematic#2情形)
  R1 Upthrust— 顶部TR 突破上界后快速收回 + 突破放量 → 风控离场预警

TR(交易区间)判定:
  近 TR_LEN 日 内: 高低价差 ≤ TR_MAX_WIDTH (因果: 区间足够宽=横盘蓄势)
  且区间内有 ≥1 根放量恐慌K线 (vol ≥ SC_VOL×20日均量, 实体/影线放大) → SC/BC 密集区
  TR_low/TR_high = 区间高低点

用法:
  python3 wyckoff_signals.py 601728.SH          # 单票最近信号演示
  python3 wyckoff_signals.py 601728.SH --all    # 列出全部历史信号
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs'))
from run_param_sensitivity import get_stock_history, get_hs300_codes  # noqa: E402


class WyckoffParams:
    """参数(第一版冻结值, 后续网格可调)"""
    TR_LEN = 40          # 回看窗口(交易日): 识别当前处于TR
    TR_MAX_WIDTH = 0.25  # 区间最大幅宽 (high-low)/mid
    MIN_TR_DAYS = 20     # 区间最少持续天数 (因果定律: 横有多长竖有多高)
    SC_VOL = 1.8         # 高潮K线 量 ≥ 20日均量×SC_VOL
    SPRING_VOL = 1.0     # Spring 下穿日 量 ≤ 20日均量×SPRING_VOL (缩量洗盘)
    SPRING_DEPTH = 0.03  # Spring 浅破约束: 下穿低 ≤ tr_low×(1+SPRING_DEPTH), 排除深破(Spring#1型)
    SPRING_RECLAIM = 0.0 # 收盘收回 TR_low 之上 多少(0=收回即可)
    TEST_DAYS = 10       # Spring 后 Test 观察窗口
    SOS_VOL = 1.5        # SOS 突破日 量 ≥ 20日均量×SOS_VOL
    UTAD_DAYS = 5        # Upthrust: 突破后 N 日内收回上界内
    ATR_PERIOD = 14
    ATR_MULT = 2.5       # chandelier 移动止损 (与 V18-ATR 一致)
    HARD_STOP = 0.99     # Spring 低点 × 0.99 为结构性硬止损
    TIME_STOP = 60       # 最长持有天数
    COOLDOWN = 20        # 离场后冷却


def detect_wyckoff(df, p=None, cooldown_from=None):
    """对日线 DataFrame(open/high/low/close/volume, DatetimeIndex) 生成信号.
    返回 DataFrame: 每行 = 一个信号事件
      date, sig(S1/S2/S3/R1), tr_low, tr_high, entry, stop, vol_ratio
    信号判定只用当日及以前数据(无未来函数), entry=次日开盘。
    cooldown_from: 离场日期列表 — 离场后 p.COOLDOWN 日内不再发买入信号(去重防刷屏)。
    """
    p = p or WyckoffParams()
    df = df.copy()
    df['vol_ma20'] = df['volume'].rolling(20, min_periods=10).mean()
    df['atr'] = bt_atr(df, p.ATR_PERIOD)
    df['hh'] = df['high'].rolling(p.TR_LEN, min_periods=p.MIN_TR_DAYS).max()
    df['ll'] = df['low'].rolling(p.TR_LEN, min_periods=p.MIN_TR_DAYS).min()

    rows = []
    cd = pd.DatetimeIndex(cooldown_from or [])

    def _in_cd(d):
        if len(cd) == 0:
            return False
        j = cd.searchsorted(d)
        if j == 0:
            return False
        return (d - cd[j - 1]).days <= p.COOLDOWN

    for i in range(p.TR_LEN + 1, len(df)):
        w = df.index[i - p.TR_LEN: i]  # TR窗口截至 i-1 (不含当日) — 当日才能跌破/突破前区
        win = df.loc[w]
        tr_low, tr_high = win['low'].min(), win['high'].max()
        mid = (tr_low + tr_high) / 2
        width = (tr_high - tr_low) / mid if mid > 0 else 9.9
        # SC/BC 密集区: 窗口内存在恐慌放量K线
        sc_mask = (win['volume'] >= win['vol_ma20'] * p.SC_VOL) & (win.index > win.index[0])
        has_calm = sc_mask.any()
        is_tr = (width <= p.TR_MAX_WIDTH) and has_calm

        row = df.iloc[i]
        c, o, l, h, v = row['close'], row['open'], row['low'], row['high'], row['volume']
        vm = row['vol_ma20']
        date = str(df.index[i].date())

        if is_tr and vm > 0:
            # ---- S1 Spring: 下穿TR_low后收盘收回, 下穿缩量, 浅破(不深穿) ----
            depth_ok = l >= tr_low * (1 - p.SPRING_DEPTH)  # 浅破: 低点不深穿下界
            if (l < tr_low and c > tr_low * (1 + p.SPRING_RECLAIM)
                    and v <= vm * p.SPRING_VOL and depth_ok and not _in_cd(df.index[i])):
                stop = min(l * p.HARD_STOP, tr_low)
                rows.append(dict(date=date, sig='S1', tr_low=tr_low, tr_high=tr_high,
                                 entry=0.0, stop=stop, vol_ratio=v / vm,
                                 width=width, calm_ok=True))
            # ---- R1 Upthrust: 突破TR_high后N日内收回 + 突破放量 → 派发预警(风控) ----
            if h > tr_high and c < tr_high and v >= vm * p.SOS_VOL:
                rows.append(dict(date=date, sig='R1', tr_low=tr_low, tr_high=tr_high,
                                 entry=0.0, stop=0.0, vol_ratio=v / vm,
                                 width=width, calm_ok=True))

        # ---- S2 Test: Spring 后 TEST_DAYS 日内缩量再探底(不深破Spring低点) ----
        sp_recent = next((r for r in reversed(rows) if r['sig'] == 'S1'), None)
        if (sp_recent is not None and vm > 0
                and 0 < (df.index[i] - pd.Timestamp(sp_recent['date'])).days <= p.TEST_DAYS
                and l >= sp_recent['tr_low'] * 0.99 and l < sp_recent['tr_high']
                and v < vm and not _in_cd(df.index[i])):
            stop = min(l * p.HARD_STOP, sp_recent['stop'])
            rows.append(dict(date=date, sig='S2', tr_low=sp_recent['tr_low'], tr_high=sp_recent['tr_high'],
                             entry=0.0, stop=stop, vol_ratio=v / vm,
                             width=width, calm_ok=True))

        # ---- S3 SOS: 放量收上TR上界(无近期Spring时用) ----
        spring_recent = any(r['sig'] in ('S1', 'S2') for r in rows[-15:])
        if c > tr_high and v >= vm * p.SOS_VOL and not spring_recent:
            stop = max(tr_low, c * 0.97)  # SOS入场: 硬止损放区间下沿
            rows.append(dict(date=date, sig='S3', tr_low=tr_low, tr_high=tr_high,
                             entry=0.0, stop=stop, vol_ratio=v / vm,
                             width=width, calm_ok=True))

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values('date').reset_index(drop=True)

    # 同一TR内 S1/S2/S3 只保留第一个买入信号(去重), R1 独立保留
    buy, keep = out[out['sig'] != 'R1'].copy(), []
    last_tr = None
    for _, r in buy.iterrows():
        key = round((r['tr_low'] + r['tr_high']) / 2, 3)
        if r['sig'] != 'R1' and key == last_tr:
            continue
        keep.append(r)
        last_tr = key
    buy2 = pd.DataFrame(keep) if keep else out[out['sig'] == 'R1'].iloc[0:0]
    out = pd.concat([buy2, out[out['sig'] == 'R1']], ignore_index=True).sort_values('date')

    # entry = 信号日次日开盘 (次日数据可得性: 用 shift)
    prices = df[['open']].reindex(out['date'].apply(lambda d: pd.Timestamp(d)))
    out['entry'] = np.nan
    for k, d in enumerate(out['date']):
        idx = df.index.searchsorted(pd.Timestamp(d))
        out.iloc[k, out.columns.get_loc('entry')] = (
            df['open'].iloc[idx + 1] if idx + 1 < len(df) else np.nan)
    out = out.dropna(subset=['entry'])
    return out.reset_index(drop=True)


def bt_atr(df, period):
    """真实波幅均值(Wilder化不够, 用SMA口径与135 ATR一致)"""
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period // 2).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('code', nargs='?', default=None)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--top', type=int, default=0, help='全池扫描(N只, 0=沪深300全部)')
    args = ap.parse_args()

    if args.code is None:
        n = args.top if args.top > 0 else 300
        codes = get_hs300_codes(n)
        if not codes:
            sys.exit('hithink-finance 取不到沪深300成分股')
        print(f'全池扫描 {len(codes)} 只 → 分信号前向收益统计')
        fwd = {10: [], 30: [], 60: []}
        per_code = []
        for i, c in enumerate(codes):
            df = get_stock_history(c)
            if df is None or len(df) < 200:
                continue
            s = detect_wyckoff(df)
            n_buys = int((s['sig'].isin(['S1','S2','S3'])).sum()) if len(s) else 0
            per_code.append((c, n_buys, int((s['sig']=='R1').sum()) if len(s) else 0))
            if len(s):
                for _, r in s[s['sig'].isin(['S1','S2','S3'])].iterrows():
                    d = pd.Timestamp(r['date'])
                    fut = df.loc[df.index > d]
                    entry = r['entry']
                    if pd.isna(entry) or entry <= 0:
                        continue
                    for horizon in (10, 30, 60):
                        if len(fut) >= horizon:
                            fwd[horizon].append(fut['close'].iloc[horizon-1] / entry - 1)
            print(f'\r  {i+1}/{len(codes)} {c}', end='', flush=True)
        print('\n')
        import numpy as _np
        n_trig = sum(b for _, b, _ in per_code)
        n_r1 = sum(u for _, _, u in per_code)
        covered = sum(1 for _, b, _ in per_code if b > 0)
        print(f'买入信号覆盖: {covered}/{len(per_code)} 只, 共 {n_trig} 次Spring/Test/SOS; '
              f'R1顶部预警 {n_r1} 次')
        print('\n买入信号 前向收益分布 (entry=次日开盘):')
        print(f'{"horizon":>7} {"n":>5} {"mean":>8} {"median":>8} {"p25":>8} {"p75":>8} {"hit>0":>7}')
        for h in (10, 30, 60):
            a = _np.array(fwd[h]) if fwd[h] else _np.array([0.0])
            hit = float(_np.mean(_np.array(fwd[h]) > 0)) if fwd[h] else float('nan')
            print(f'{h:>7} {len(fwd[h]):>5} {a.mean():>8.1%} {_np.median(a):>8.1%} '
                  f'{_np.percentile(a,25):>8.1%} {_np.percentile(a,75):>8.1%} {hit:>7.1%}')
        return

    df = get_stock_history(args.code)
    if df is None:
        sys.exit(f'{args.code} 取不到数据')
    sig = detect_wyckoff(df)
    print(f'{args.code} {df.index[0].date()} → {df.index[-1].date()}  '
          f'共{len(df)}根K线, 信号{len(sig)}个')
    show = sig if args.all else sig.tail(8)
    if show.empty:
        print('无信号')
        return
    print(show.to_string())
    # 最近一个买入信号的简易验证
    buys = sig[sig['sig'].isin(['S1', 'S2', 'S3'])]
    if not buys.empty:
        last = buys.iloc[-1]
        d = pd.Timestamp(last['date'])
        fut = df.loc[df.index > d]
        if len(fut) >= 10:
            r10 = fut['close'].iloc[min(9, len(fut) - 1)] / last['entry'] - 1
            r30 = fut['close'].iloc[min(29, len(fut) - 1)] / last['entry'] - 1
            mhh = fut['high'].max() / last['entry'] - 1
            mll = fut['low'].min() / last['entry'] - 1
            print(f"\n最近{last['sig']}@{last['date']}: entry={last['entry']:.2f} "
                  f"10日={r10:+.1%} 30日={r30:+.1%} 最大浮盈={mhh:+.1%} 最大回撤={mll:+.1%}")


if __name__ == '__main__':
    main()
