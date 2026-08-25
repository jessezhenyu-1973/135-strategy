#!/usr/bin/env python3
"""
135战法 — 组合层验证: 多票并行 + 资金管理
对比三种组合管理方式（信号层全部使用V17原版，不再改动）:

  A. 基准:      每票独立回测取平均（= 此前所有报告的口径, 无资金约束）
  B. 组合-均分:  组合账户100万, 每笔买入用当前总资产的1/10, 最多同时持有5只
                （总敞口≤50%, 留一半现金应对回撤）
  C. 组合-动态:  同B, 但同时持仓上限按已实现盈亏动态调整:
                连亏2笔 → 持仓上限降为3只; 盈利恢复 → 升回5只

实现方式: 自建事件驱动组合模拟器（不用backtrader多data, 逻辑更可控）
信号生成: 复用V17离线信号扫描（run_leadership_filter.scan_buy_signals）

用法:
    python3 run_portfolio_backtest.py            # 全池
    python3 run_portfolio_backtest.py --top 50
"""

import os
import sys
import csv
import argparse
import statistics as st
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history
from run_leadership_filter import scan_buy_signals


def load_trades_from_scan(df, code=None):
    """
    用V17逻辑做单票完整回测, 返回每笔交易的 (entry_date, exit_date, entry_price, exit_price, return_pct)
    直接复用backtrader策略的trade_log + 日期。这里用简化重放: 与scan一致但记录交易明细。
    """
    import backtrader as bt
    import tempfile
    from run_param_sensitivity import df_to_csv
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))

    trades = []
    code_ref = {'v': code}

    class T(bt.Strategy):
        params = (('stop_loss_pct', 0.08), ('cool_down_bars', 10))
        def __init__(self):
            self.ma13 = bt.ind.SMA(self.data.close, period=13)
            self.ma34 = bt.ind.SMA(self.data.close, period=34)
            self.ma55 = bt.ind.SMA(self.data.close, period=55)
            self.vol_ma = bt.ind.SMA(self.data.volume, period=5)
            self.buy_bar = -1; self.highest = 0.0; self.ep = None
            self.pending = None  # (entry_date, entry_price)

        def _dt(self):
            return str(self.data.datetime.date(0)).replace('-', '')

        def _is_downtrend(self):
            a = lambda i: (self.ma13[i], self.ma34[i], self.ma55[i])
            m0, m1, m2 = a(0), a(-1), a(-2)
            if not (m0[0] < m0[1] < m0[2]):
                return False
            return all(m0[j] < m1[j] < m2[j] for j in range(3))

        def _buy_sig(self):
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

        def _sell_sig(self):
            c, o = self.data.close[0], self.data.open[0]
            m13, m13p = self.ma13[0], self.ma13[-1]
            v, vm = self.data.volume[0], self.vol_ma[0]
            return v > vm * 1.5 and c < o and c < m13 and m13 < m13p

        def next(self):
            if len(self.data) < 60:
                return
            price = self.data.close[0]; d = self._dt()
            if self.position:
                if self.highest == 0:
                    self.highest = price
                exit_now = False
                if self._sell_sig():
                    exit_now = True
                elif (self.highest - price) / self.highest >= self.p.stop_loss_pct:
                    exit_now = True
                if exit_now and self.pending:
                    ed, ep = self.pending
                    trades.append({'code': code_ref['v'], 'entry_date': ed, 'exit_date': d,
                                   'return_pct': round((price - ep) / ep * 100, 3)})
                    self.pending = None
                    self.highest = 0; self.buy_bar = len(self.data) - 1
                return
            if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
                return
            if self._buy_sig():
                n = int(1e6 * 0.10 / price)
                if n >= 10:
                    self.buy(size=n)
                    self.pending = (d, price)
                    self.highest = price

        def notify_order(self, order):
            if order.status == order.Completed and order.isbuy():
                self.pending = (self._dt(), order.executed.price)

    cerebro.addstrategy(T)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    # 注入code
    orig_add = cerebro.addstrategy
    cerebro.run()
    os.unlink(tmp.name)
    return trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    parser.add_argument('--cash', type=float, default=1e6)
    parser.add_argument('--max-pos', type=int, default=5)
    args = parser.parse_args()

    n = args.top if args.top > 0 else 300
    print(f"获取沪深300 (前{n})...")
    codes = get_hs300_codes(n)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df

    print("提取各股交易序列...")
    all_trades = []
    for i, (code, df) in enumerate(sorted(datasets.items())):
        ts = load_trades_from_scan(df, code)
        for t in ts:
            t['code'] = code
        all_trades.extend(ts)
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(datasets)}")
    all_trades.sort(key=lambda t: t['entry_date'])
    print(f"共 {len(all_trades)} 笔候选交易")

    CASH = args.cash

    def simulate(max_pos_rule):
        """max_pos_rule(state) -> 当前允许的最大同时持仓数"""
        cash = CASH
        holdings = {}   # code -> {'entry_price','shares'}
        equity_curve = []   # (date, total_equity)
        realized = []       # pnl list
        pending_buys = defaultdict(list)  # date -> list of trades to buy next day
        # 简化: 交易在entry_date以entry_price成交, exit_date以exit价退出
        # 构建时间轴
        events = defaultdict(list)
        for t in all_trades:
            events[t['exit_date']].append(('sell', t))
            events[t['entry_date']].append(('buy', t))
        dates = sorted(events.keys())
        # 需要每日估值 → 用第一只股票的日历近似（交易日历一致）
        cal = sorted(set(d for df in datasets.values() for d in df.index.strftime('%Y%m%d')))
        prices = {}
        for code, df in datasets.items():
            prices[code] = dict(zip(df.index.strftime('%Y%m%d'), df['close']))
        state_consecutive_loss = 0

        for d in cal:
            # 1. 处理卖出
            for typ, t in events.get(d, []):
                if typ == 'sell' and t['code'] in holdings:
                    h = holdings.pop(t['code'])
                    pnl = h['shares'] * (t['exit_price'] if 'exit_price' in t else 0)
                    # 用 return_pct 计算: shares*entry*(ret/100)
                    pnl = h['shares'] * h['entry_price'] * t['return_pct'] / 100
                    cash += h['shares'] * h['entry_price'] + pnl
                    realized.append(pnl)
                    state_consecutive_loss = state_consecutive_loss + 1 if pnl < 0 else 0
            # 2. 处理买入
            max_pos = max_pos_rule(len(holdings), state_consecutive_loss)
            for typ, t in events.get(d, []):
                if typ != 'buy' or t['code'] in holdings:
                    continue
                if len(holdings) >= max_pos:
                    continue
                price = prices[t['code']].get(d)
                if not price:
                    continue
                alloc = cash * 0.10
                if alloc < price * 10:
                    continue
                shares = int(alloc / price)
                cost = shares * price
                cash -= cost
                holdings[t['code']] = {'entry_price': price, 'shares': shares}
            # 3. 每日估值
            eq = cash
            for code, h in holdings.items():
                p = prices[code].get(d, h['entry_price'])
                eq += h['shares'] * p
            equity_curve.append((d, eq))

        final = equity_curve[-1][1] if equity_curve else CASH
        # 回撤
        peak, maxdd = -1e18, 0
        for _, eq in equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak
            maxdd = max(maxdd, dd)
        n_tr = len(realized)
        wins = sum(1 for p in realized if p > 0)
        return {
            'final': round(final, 0),
            'total_return': round((final - CASH) / CASH * 100, 2),
            'n_trades': n_tr,
            'win_rate': round(wins / n_tr * 100, 1) if n_tr else 0,
            'avg_pnl': round(st.mean(realized), 0) if n_tr else 0,
            'max_drawdown': round(maxdd * 100, 2),
        }

    results = {}
    print("\n回测 A: 单票基准(等权平均)")
    # A口径: 所有交易等权单笔收益
    rets = [t['return_pct'] for t in all_trades]
    wins = sum(1 for r in rets if r > 0)
    results['A_独立单票'] = {
        'total_return': round(sum(rets) / len(rets), 2),   # 平均单票收益
        'n_trades': len(rets),
        'win_rate': round(wins / len(rets) * 100, 1),
        'avg_pnl': 0, 'max_drawdown': 0}

    print("回测 B: 组合-固定上限5只")
    results['B_组合固定5'] = simulate(lambda held, loss: min(args.max_pos, 5))

    print("回测 C: 组合-连亏降仓")
    def dyn(held, consec_loss):
        return 3 if consec_loss >= 2 else args.max_pos
    results['C_组合动态'] = simulate(dyn)

    print(f"\n{'='*66}")
    print(f"{'方案':<16}{'总收益%':>10}{'交易数':>8}{'胜率%':>8}{'最大回撤%':>10}")
    for k, v in results.items():
        print(f"{k:<16}{v['total_return']:>10.2f}{v['n_trades']:>8}"
              f"{v['win_rate']:>8.1f}{v['max_drawdown']:>10.2f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portfolio_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['scheme', 'total_return', 'n_trades', 'win_rate', 'avg_pnl', 'max_drawdown'])
        for k, v in results.items():
            w.writerow([k, v['total_return'], v['n_trades'], v['win_rate'], v['avg_pnl'], v['max_drawdown']])
    print(f"\n结果: {out}")


if __name__ == '__main__':
    main()
