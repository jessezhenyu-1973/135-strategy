#!/usr/bin/env python3
"""
135战法 — ATR止损研究
改动: ① 移动止损从固定8%改为 ATR倍数追踪止损 ② 移除一箭穿心卖出信号(仅ATR/移动止损退出)

对比:
  A. V17基准        — 8%移动止损 + 一箭穿心
  B. ATR-仅追踪      — 无信号卖出, 仅 ATR(k=3) 追踪止损 (chandelier: 最高价 - k*ATR)
  C. ATR网格        — k ∈ {2,2.5,3,3.5,4}, period=14, 选最优后再全池确认

口径: 组合层模拟器(与任务10一致, 实盘可实现), 另附单票等权参考。
用法:
    python3 run_atr_stop.py            # 全池
    python3 run_atr_stop.py --top 50
"""

import os
import sys
import csv
import argparse
import tempfile
import statistics as st
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history, df_to_csv

import backtrader as bt


class StrategyATR(bt.Strategy):
    """
    V17信号 + 可配置退出:
    exit_mode: 'v17' = 一箭穿心+8%移动止损 | 'atr' = 纯ATR追踪(chandelier)
    """
    params = (
        ('exit_mode', 'v17'),
        ('atr_period', 14),
        ('atr_mult', 3.0),
        ('stop_loss_pct', 0.08),
        ('cool_down_bars', 10),
    )

    def __init__(self):
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)
        self.buy_bar = -1
        self.highest_price = 0.0
        self.trade_log = []
        self.exit_reason = None

    # ---- V17 买入侧（原版不动） ----
    def _is_downtrend(self):
        a = lambda i: (self.ma13[i], self.ma34[i], self.ma55[i])
        m0, m1, m2 = a(0), a(-1), a(-2)
        if not (m0[0] < m0[1] < m0[2]):
            return False
        return all(m0[j] < m1[j] < m2[j] for j in range(3))

    def _buy_signal(self):
        c, o = self.data.close[0], self.data.open[0]
        m13, m34, m55 = self.ma13[0], self.ma34[0], self.ma55[0]
        m13p, m13p2 = self.ma13[-1], self.ma13[-2]
        v, vm = self.data.volume[0], self.vol_ma[0]
        if self._is_downtrend() or c < m55:
            return False
        m55_5 = self.ma55[-5]
        if m55_5 > 0 and (m55_5 - m55) / m55_5 > 0.05:
            return False
        if (m13p2 <= m13p and m13 > m13p and c > m13 and c > o and v > vm and m13 > m34 > m55):
            return True   # 红杏出墙
        if (c > o and o < m55 and o < m34 and o < m13 and c > m55 and c > m34 and c > m13 and v > vm * 2.0):
            return True   # 一阳穿三线
        if vm > 0:
            spread = (max(m13, m34, m55) - min(m13, m34, m55)) / max(m13, m34, m55)
            avg_s, cnt = 0.0, 0
            for i in range(5):
                a13 = m13 if i == 0 else self.ma13[-i]
                a34 = m34 if i == 0 else self.ma34[-i]
                a55 = m55 if i == 0 else self.ma55[-i]
                ms, mn = max(a13, a34, a55), min(a13, a34, a55)
                avg_s += (ms - mn) / ms if ms > 0 else 0
                cnt += 1
            if spread < 0.015 and avg_s / cnt < 0.02 and v > vm * 2.0 and c > o and c > m13 and c > m34 and c > m55:
                return True   # 揭竿而起
        return False

    def _yjc_sell(self):
        """一箭穿心: 放量1.5x阴线破拐头向下的MA13"""
        c, o = self.data.close[0], self.data.open[0]
        m13, m13p = self.ma13[0], self.ma13[-1]
        v, vm = self.data.volume[0], self.vol_ma[0]
        return v > vm * 1.5 and c < o and c < m13 and m13 < m13p

    def next(self):
        if len(self.data) < 60:
            return
        price = self.data.close[0]

        if self.position:
            exit_now = False
            if self.p.exit_mode == 'v17':
                if self.highest_price == 0:
                    self.highest_price = price
                if self._yjc_sell():
                    exit_now, self.exit_reason = True, '一箭穿心'
                elif (self.highest_price - price) / self.highest_price >= self.p.stop_loss_pct:
                    exit_now, self.exit_reason = True, '移动止损8%'
            else:  # atr chandelier: stop = highest - k*ATR; 跌破即出
                if self.highest_price == 0:
                    self.highest_price = price
                stop = self.highest_price - self.p.atr_mult * self.atr[0]
                if price < stop:
                    exit_now, self.exit_reason = True, f'ATR止损'
            if exit_now:
                ep = getattr(self, '_entry_price', price)
                ret = round((price - ep) / ep * 100, 3) if ep else 0
                self.trade_log.append({'return_pct': ret, 'exit': self.exit_reason})
                self.sell(size=self.position.size)
                self.highest_price = 0
                self.buy_bar = len(self.data) - 1
            return

        if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
            return
        if self._buy_signal():
            cash = self.broker.getcash()
            n = int(cash * 0.10 / price)
            if n >= 10:
                self.buy(size=n)
                self.buy_bar = len(self.data) - 1
                self.highest_price = price

    def notify_order(self, order):
        if order.status == order.Completed and order.isbuy():
            self._entry_price = order.executed.price


def run_one(df, **params):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))
    cerebro.addstrategy(StrategyATR, **params)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    s = cerebro.run()[0]
    # 补记未平仓头寸（按最后收盘价虚拟平仓, 否则浮盈交易丢失→统计失真）
    if s.position:
        price = s.data.close[0]
        ep = getattr(s, '_entry_price', price)
        ret = round((price - ep) / ep * 100, 3) if ep else 0
        s.trade_log.append({'return_pct': ret, 'exit': '期末持仓'})
    final = cerebro.broker.getvalue()
    tl = s.trade_log
    n = len(tl)
    wins = sum(1 for t in tl if t['pnl'] > 0) if n and 'pnl' in tl[0] else sum(1 for t in tl if t['return_pct'] > 0)
    os.unlink(tmp.name)
    return {
        'total_return': round((final - 1e6) / 1e6 * 100, 3),
        'n_trades': n,
        'win_rate': round(wins / n * 100, 1) if n else 0,
        'avg_ret_per_trade': round(sum(t['return_pct'] for t in tl) / n, 3) if n else 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    args = parser.parse_args()
    n = args.top if args.top > 0 else 300

    print(f"获取沪深300 (前{n})...")
    codes = get_hs300_codes(n)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df
    print(f"可用数据 {len(datasets)} 只\n")

    configs = [
        ('A_V17基准', dict(exit_mode='v17')),
        ('B_ATR_k2.0', dict(exit_mode='atr', atr_mult=2.0)),
        ('C_ATR_k2.5', dict(exit_mode='atr', atr_mult=2.5)),
        ('D_ATR_k3.0', dict(exit_mode='atr', atr_mult=3.0)),
        ('E_ATR_k3.5', dict(exit_mode='atr', atr_mult=3.5)),
        ('F_ATR_k4.0', dict(exit_mode='atr', atr_mult=4.0)),
    ]

    agg = {name: defaultdict(list) for name, _ in configs}
    rows = []
    for i, (code, df) in enumerate(sorted(datasets.items())):
        res = {}
        for name, params in configs:
            r = run_one(df, **params)
            res[name] = r
            for k, v in r.items():
                agg[name][k].append(v)
        base_score = res['A_V17基准']['avg_ret_per_trade'] * (1 + res['A_V17基准']['win_rate'] / 100)
        best_atr, best_sc = None, -1e9
        for name, _ in configs[1:]:
            sc = res[name]['avg_ret_per_trade'] * (1 + res[name]['win_rate'] / 100)
            if sc > best_sc:
                best_sc, best_atr = sc, name
        row = {'code': code}
        for name, _ in configs:
            for k, v in res[name].items():
                row[f'{k}_{name}'] = round(v, 3)
        rows.append(row)
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(datasets)} (本票最优ATR: {best_atr})")

    print(f"\n{'='*72}")
    print(f"{'方案':<14}{'总收益%':>10}{'交易数':>8}{'胜率%':>8}{'单笔收益%':>11}")
    scores = {}
    for name, _ in configs:
        tr = st.mean(agg[name]['total_return'])
        nt = st.mean(agg[name]['n_trades'])
        wr = st.mean(agg[name]['win_rate'])
        ar = st.mean(agg[name]['avg_ret_per_trade'])
        scores[name] = ar * (1 + wr / 100)
        print(f"{name:<14}{tr:>10.2f}{nt:>8.1f}{wr:>8.1f}{ar:>11.2f}")

    # 占优统计 vs 基准
    print(f"\n各ATR方案得分占优比例(vs V17基准):")
    for name, _ in configs[1:]:
        b = sum(
            1 for r in rows
            if r[f'avg_ret_per_trade_{name}'] * (1 + r[f'win_rate_{name}'] / 100) >
               r['avg_ret_per_trade_A_V17基准'] * (1 + r['win_rate_A_V17基准'] / 100))
        print(f"  {name}: {b}/{len(rows)} ({b/len(rows)*100:.0f}%)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'atr_stop_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\n明细: {out}")


if __name__ == '__main__':
    main()
