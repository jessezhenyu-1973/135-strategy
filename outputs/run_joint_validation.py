#!/usr/bin/env python3
"""
135战法 — 任务11: V18-ATR × 组合层联合回测
在任务10的组合模拟器上, 对比退出机制:
  A. V17退出   — 一箭穿心 + 8%移动止损
  B. ATR退出   — chandelier stop = 最高价 - 2.5×ATR14 (无信号卖出)

组合规则不变: 单笔10%仓位, 最多同时5只, 先到先得。
用法:
    python3 run_joint_validation.py            # 全池
    python3 run_joint_validation.py --top 50
"""
import os
import sys
import csv
import argparse
import tempfile
import statistics as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history, df_to_csv

import backtrader as bt


class JointStrategy(bt.Strategy):
    params = (
        ('exit_mode', 'v17'),        # 'v17' | 'atr'
        ('atr_mult', 2.5),
        ('stop_loss_pct', 0.08),
        ('cool_down_bars', 10),
    )

    def __init__(self):
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)
        self.atr = bt.ind.ATR(self.data, period=14)
        self.buy_bar = -1
        self.highest_price = 0.0
        self.pending_entry = None   # (date, price) 在信号日记录, 组合层用
        self.segments = []          # 持仓段记录

    # ---- V17 买入信号（原版） ----
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
            return True
        if (c > o and o < m55 and o < m34 and o < m13 and c > m55 and c > m34 and c > m13 and v > vm * 2.0):
            return True
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
                return True
        return False

    def next(self):
        """单票模式: 记录该票全部"持仓段"(entry_date/price → exit_date/price)。
        组合层随后用这些持仓段做资金约束重放。"""
        if len(self.data) < 60:
            return
        price = self.data.close[0]
        d = str(self.data.datetime.date(0)).replace('-', '')

        if self.position:
            exit_now = False
            if self.p.exit_mode == 'v17':
                if self.highest_price == 0:
                    self.highest_price = price
                yjc = (self.data.volume[0] > self.vol_ma[0] * 1.5 and
                       self.data.close[0] < self.data.open[0] and
                       self.data.close[0] < self.ma13[0] and self.ma13[0] < self.ma13[-1])
                if yjc or (self.highest_price - price) / self.highest_price >= self.p.stop_loss_pct:
                    exit_now = True
            else:
                if self.highest_price == 0:
                    self.highest_price = price
                stop = self.highest_price - self.p.atr_mult * self.atr[0]
                if price < stop:
                    exit_now = True
            if exit_now and self.pending_entry:
                ed, ep = self.pending_entry
                self.segments.append({'entry_date': ed, 'entry_price': ep,
                                      'exit_date': d, 'exit_price': price})
                self.pending_entry = None
                self.highest_price = 0
                self.buy_bar = len(self.data) - 1
            return

        if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
            return
        if self._buy_signal():
            n = int(1e6 * 0.10 / price)
            if n >= 10:
                self.buy(size=n)
                self.pending_entry = (d, price)
                self.highest_price = price

    def notify_order(self, order):
        if order.status == order.Completed and order.isbuy():
            if self.pending_entry:
                d, _ = self.pending_entry
                self.pending_entry = (d, order.executed.price)


def extract_segments(df, exit_mode):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))
    cerebro.addstrategy(JointStrategy, exit_mode=exit_mode)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    s = cerebro.run()[0]
    segs = s.segments
    # 补记期末未平仓
    if s.position and s.pending_entry:
        ed, ep = s.pending_entry
        segs.append({'entry_date': ed, 'entry_price': ep,
                     'exit_date': None, 'exit_price': s.data.close[0]})
    os.unlink(tmp.name)
    return segs


def portfolio_simulate(all_segments, prices_by_code, calendar, cash0=1e6, max_pos=5):
    """事件驱动组合模拟: 持仓段即交易。entry日以10%资金买入(若名额与资金允许)。"""
    cash = cash0
    holdings = {}       # code -> {'entry_price','shares'}
    realized = []
    equity_curve = []
    events = defaultdict(list)
    for code, segs in all_segments.items():
        for s in segs:
            events[s['entry_date']].append(('buy', code, s))
            if s['exit_date']:
                events[s['exit_date']].append(('sell', code, s))
    for d in calendar:
        # 先卖后买
        for typ, code, s in events.get(d, []):
            if typ == 'sell' and code in holdings:
                h = holdings.pop(code)
                pnl = h['shares'] * (s['exit_price'] - h['entry_price'])
                cash += h['shares'] * s['exit_price']
                realized.append(pnl)
        for typ, code, s in events.get(d, []):
            if typ != 'buy' or code in holdings:
                continue
            if len(holdings) >= max_pos:
                continue
            price = prices_by_code[code].get(d)
            if not price:
                continue
            alloc = cash * 0.10
            if alloc < price * 10:
                continue
            shares = int(alloc / price)
            cash -= shares * price
            holdings[code] = {'entry_price': price, 'shares': shares}
        eq = cash + sum(h['shares'] * prices_by_code[c].get(d, h['entry_price'])
                        for c, h in holdings.items())
        equity_curve.append((d, eq))
    final = equity_curve[-1][1] if equity_curve else cash0
    peak, maxdd = -1e18, 0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        maxdd = max(maxdd, (peak - eq) / peak)
    n_tr = len(realized)
    wins = sum(1 for p in realized if p > 0)
    return {
        'total_return': round((final - cash0) / cash0 * 100, 2),
        'n_trades': n_tr,
        'win_rate': round(wins / n_tr * 100, 1) if n_tr else 0,
        'max_drawdown': round(maxdd * 100, 2),
    }


from collections import defaultdict

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    parser.add_argument('--cash', type=float, default=1e6)
    args = parser.parse_args()
    n = args.top if args.top > 0 else 300

    print(f"获取沪深300 (前{n})...")
    codes = get_hs300_codes(n)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df
    print(f"可用数据 {len(datasets)} 只")

    print("\n提取A方案(V17退出)持仓段...")
    segs_a = {}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        segs_a[code] = extract_segments(df, 'v17')
        if (i+1) % 50 == 0: print(f"  ...{i+1}/{len(datasets)}")

    print("提取B方案(ATR k=2.5退出)持仓段...")
    segs_b = {}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        segs_b[code] = extract_segments(df, 'atr')
        if (i+1) % 50 == 0: print(f"  ...{i+1}/{len(datasets)}")

    prices_by_code = {code: dict(zip(df.index.strftime('%Y%m%d'), df['close']))
                      for code, df in datasets.items()}
    calendar = sorted(set(d for df in datasets.values() for d in df.index.strftime('%Y%m%d')))

    print("\n组合层回测...")
    res_a = portfolio_simulate(segs_a, prices_by_code, calendar, args.cash)
    res_b = portfolio_simulate(segs_b, prices_by_code, calendar, args.cash)

    print(f"\n{'='*58}")
    print(f"{'指标':<16}{'V17退出+组合':>18}{'ATR2.5退出+组合':>20}")
    for k in ['total_return', 'n_trades', 'win_rate', 'max_drawdown']:
        fmt = '.1f' if k == 'n_trades' else '.2f'
        print(f"{k:<16}{res_a[k]:>18{fmt}}{res_b[k]:>20{fmt}}")
    ra = res_a['total_return']/res_a['max_drawdown'] if res_a['max_drawdown'] else 0
    rb = res_b['total_return']/res_b['max_drawdown'] if res_b['max_drawdown'] else 0
    print(f"{'收益/回撤比':<15}{ra:>18.2f}{rb:>20.2f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'joint_validation_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['scheme'] + list(res_a.keys()))
        w.writerow(['A_V17退出+组合'] + list(res_a.values()))
        w.writerow(['B_ATR2.5退出+组合'] + list(res_b.values()))
    print(f"\n结果: {out}")


if __name__ == '__main__':
    main()
