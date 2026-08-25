#!/usr/bin/env python3
"""
135均线交易系统 — 任务7: 参数敏感性分析
基于 V17 (run_135_position_backtest_v17.py)，对核心信号参数做网格扫描。

方法:
- 股票池: 沪深300前30只成分股（与 V17 验证集一致），20230101–20260813
- 每组参数在全部股票上回测，汇总 平均收益/平均夏普/平均胜率/交易数
- 输出: outputs/param_sensitivity_results.csv + 报告 md

用法:
    python3 run_param_sensitivity.py            # 全网格
    python3 run_param_sensitivity.py --quick    # 快速模式（前10只）
"""

import subprocess
import json
import os
import tempfile
import argparse
import datetime
import itertools
import csv
import backtrader as bt
import pandas as pd

# ============================================================
# 数据获取（复用 V17 逻辑）
# ============================================================

def get_hs300_codes(top_n=30):
    result = subprocess.run([
        'hithink-finance', 'index', 'constituents',
        '--thscode', '000300.SH', '--format', 'json'
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    items = data.get('data', {}).get('item', [])
    codes = [i.get('thscode', '') for i in items if i.get('thscode')]
    # 过滤掉北交所/非6、0开头，保证流动性
    codes = [c for c in codes if c.startswith(('6', '0'))]
    return codes[:top_n]


def get_stock_history(thscode, start_date='20230101', end_date='20260813'):
    start_ms = int(datetime.datetime.strptime(start_date, '%Y%m%d').timestamp() * 1000)
    end_ms = int(datetime.datetime.strptime(end_date, '%Y%m%d').timestamp() * 1000)
    cache = f'/tmp/_ths_cache_{thscode.replace(".", "_")}.json'
    result = subprocess.run([
        'hithink-finance', 'market', 'history',
        '--thscode', thscode,
        '--start-ms', str(start_ms), '--end-ms', str(end_ms),
        '--adjust', 'forward', '--output', cache
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        with open(cache) as f:
            data = json.load(f)
    except Exception:
        return None
    items = data.get('data', {}).get('item', [])
    if not items:
        return None
    df = pd.DataFrame(items)
    df['date'] = pd.to_datetime(df['date_ms'], unit='ms')
    df.set_index('date', inplace=True)
    df.sort_index(inplace=True)
    df.rename(columns={'open_price': 'open', 'high_price': 'high',
                       'low_price': 'low', 'close_price': 'close'}, inplace=True)
    df = df[(df['close'] > 0) & (df['volume'] >= 0)]
    return df if len(df) >= 60 else None


def df_to_csv(df, path):
    r = df.reset_index()
    r['date'] = r['date'].dt.strftime('%Y%m%d')
    cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    r[cols].to_csv(path, index=False, float_format='%.4f')


# ============================================================
# 参数化策略 — 从 V17 策略参数化而来
# ============================================================

class Strategy135Tuned(bt.Strategy):
    """
    V17 的参数化版本。所有可调参数集中在 params 中，
    默认值 = V17 基准。
    params:
      hx_vol_mult      红杏出墙量能倍数      (V17: 1.0)
      yycs_vol_mult    一阳穿三线量能倍数    (V17: 2.0)
      jzjq_spread      揭竿而起当日黏合阈值   (V17: 0.015)
      jzjq_avg_spread  揭竿而起5日均黏合     (V17: 0.02)
      jzjq_vol_mult    揭竿而起量能倍数      (V17: 2.0)
      sell_vol_mult    一箭穿心(卖)量能倍数  (V17: 1.5)
      stop_loss_pct    移动止损              (V17: 0.08)
      cool_down_bars   冷却期                (V17: 10)
    """
    params = (
        ('hx_vol_mult', 1.0),
        ('yycs_vol_mult', 2.0),
        ('jzjq_spread', 0.015),
        ('jzjq_avg_spread', 0.02),
        ('jzjq_vol_mult', 2.0),
        ('sell_vol_mult', 1.5),
        ('stop_loss_pct', 0.08),
        ('cool_down_bars', 10),
        ('commission', 0.001),
    )

    def __init__(self):
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)
        self.stage = 0
        self.hold_start_bar = -1
        self.highest_price = 0.0
        self.current_shares = 0
        self.buy_bar = -1
        self.signals_log = []
        self.trade_log = []
        self.last_sell_signal = None

    def _is_downtrend(self):
        m13_0, m34_0, m55_0 = self.ma13[0], self.ma34[0], self.ma55[0]
        m13_1, m34_1, m55_1 = self.ma13[-1], self.ma34[-1], self.ma55[-1]
        m13_2, m34_2, m55_2 = self.ma13[-2], self.ma34[-2], self.ma55[-2]
        if not (m13_0 < m34_0 < m55_0):
            return False
        if not (m13_0 < m13_1 < m13_2):
            return False
        if not (m34_0 < m34_1 < m34_2):
            return False
        if not (m55_0 < m55_1 < m55_2):
            return False
        return True

    def _check_buy_signals(self):
        c, o = self.data.close[0], self.data.open[0]
        m13, m34, m55 = self.ma13[0], self.ma34[0], self.ma55[0]
        m13p, m13p2 = self.ma13[-1], self.ma13[-2]
        v, vm = self.data.volume[0], self.vol_ma[0]

        if self._is_downtrend():
            return None
        if c < m55:
            return None
        m55_5 = self.ma55[-5]
        if m55_5 > 0 and (m55_5 - m55) / m55_5 > 0.05:
            return None

        # 1. 红杏出墙 (量能倍数可调)
        if (m13p2 <= m13p and m13 > m13p and c > m13 and c > o and
                v > vm * self.p.hx_vol_mult and m13 > m34 > m55):
            return '红杏出墙'

        # 2. 一阳穿三线 (量能倍数可调)
        if (c > o and o < m55 and o < m34 and o < m13 and
                c > m55 and c > m34 and c > m13 and v > vm * self.p.yycs_vol_mult):
            return '一阳穿三线'

        # 3. 揭竿而起 (黏合阈值+5日均黏合+量能倍数可调)
        if vm > 0:
            spread = (max(m13, m34, m55) - min(m13, m34, m55)) / max(m13, m34, m55)
            avg_spread, cnt = 0.0, 0
            for i in range(5):
                a13 = m13 if i == 0 else self.ma13[-i]
                a34 = m34 if i == 0 else self.ma34[-i]
                a55 = m55 if i == 0 else self.ma55[-i]
                ms, mn = max(a13, a34, a55), min(a13, a34, a55)
                avg_spread += (ms - mn) / ms if ms > 0 else 0
                cnt += 1
            avg_spread /= max(cnt, 1)
            if (spread < self.p.jzjq_spread and avg_spread < self.p.jzjq_avg_spread and
                    v > vm * self.p.jzjq_vol_mult and c > o and
                    c > m13 and c > m34 and c > m55):
                return '揭竿而起'
        return None

    def _check_sell_signals(self):
        c, o = self.data.close[0], self.data.open[0]
        m13, m13p = self.ma13[0], self.ma13[-1]
        v, vm = self.data.volume[0], self.vol_ma[0]
        if (v > vm * self.p.sell_vol_mult and c < o and c < m13 and m13 < m13p):
            return '一箭穿心'
        return None

    def next(self):
        if len(self.data) < 60:
            return
        price = self.data.close[0]

        if self.position:
            sig = self._check_sell_signals()
            if sig:
                self._sell('135卖出: ' + sig)
                return
            if self.highest_price > 0:
                dd = (self.highest_price - price) / self.highest_price
                if dd >= self.p.stop_loss_pct:
                    self._sell(f'移动止损')
                    return
            else:
                self.highest_price = price

        if not self.position:
            if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
                return
            buy_sig = self._check_buy_signals()
            if buy_sig:
                cash = self.broker.getcash()
                n = int(cash * 0.10 / price)
                if n >= 10:
                    self.buy(size=n)
                    self.buy_bar = len(self.data) - 1
                    self.highest_price = price
                    self.current_shares = n
                    self.total_buy_count = getattr(self, 'total_buy_count', 0) + 1
                    self.signals_log.append({'type': 'BUY', 'signal': buy_sig})

    def _sell(self, reason):
        if self.position:
            self.last_sell_signal = reason
            self._exit_price = self.data.close[0]
            self._exit_date = str(self.data.datetime.date(0))
            self.close()
            self.stage = 0
            self.highest_price = 0
            self.current_shares = 0
            self.buy_bar = -1

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnlcomm
            ep = getattr(self, '_entry_price', trade.price)
            es = max(1, abs(trade.size)) if not hasattr(self, '_entry_shares') else self._entry_shares
            ret = round(pnl / (ep * es) * 100, 2) if ep > 0 else 0
            self.trade_log.append({
                'pnl': pnl, 'return_pct': ret,
                'exit_signal': self.last_sell_signal or '未知',
            })
            self.last_sell_signal = None

    def notify_order(self, order):
        if order.status == order.Completed and order.isbuy():
            self._entry_price = order.executed.price
            self._entry_shares = order.executed.size
            self._entry_date = str(self.data.datetime.date(0))


# ============================================================
# 单次回测
# ============================================================

def run_one(df, params, initial_cash=1000000):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))
    cerebro.addstrategy(Strategy135Tuned, **params)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=params.get('commission', 0.001))
    strat = cerebro.run()[0]
    final = cerebro.broker.getvalue()
    trades = strat.trade_log
    n = len(trades)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    ret = (final - initial_cash) / initial_cash * 100
    os.unlink(tmp.name)
    return {
        'total_return': ret,
        'n_trades': n,
        'win_rate': wins / n * 100 if n else 0,
        'avg_ret_per_trade': sum(t['return_pct'] for t in trades) / n if n else 0,
    }


# ============================================================
# 网格定义
# ============================================================

GRID = {
    'hx_vol_mult':     [0.8, 1.0, 1.2, 1.5],
    'yycs_vol_mult':   [1.5, 2.0, 2.5],
    'jzjq_spread':     [0.01, 0.015, 0.02],
    'jzjq_vol_mult':   [1.5, 2.0, 2.5],
    'stop_loss_pct':   [0.06, 0.08, 0.10],
}
# 卖出量能与冷却期单独扫（二阶维度），避免组合爆炸
SELL_GRID = [1.2, 1.5, 2.0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='前10只股票快速模式')
    parser.add_argument('--top', type=int, default=30)
    args = parser.parse_args()
    top_n = 10 if args.quick else args.top

    print("获取股票池与K线数据...")
    codes = get_hs300_codes(top_n)
    datasets = {}
    for code in codes:
        df = get_stock_history(code)
        if df is not None:
            datasets[code] = df
    print(f"可用数据: {len(datasets)} 只")

    combos = list(itertools.product(*GRID.values()))
    print(f"网格规模: {len(combos)} 组 x {len(datasets)} 只 = {len(combos)*len(datasets)} 次回测")
    print("开始扫描...\n")

    rows = []
    best = None
    for gi, combo in enumerate(combos):
        params = dict(zip(GRID.keys(), combo))
        agg = {'total_return': 0, 'n_trades': 0, 'win_rate': 0, 'avg_ret_per_trade': 0}
        for code, df in datasets.items():
            r = run_one(df, params)
            for k in agg:
                agg[k] += r[k]
        n = len(datasets)
        avg = {k: v / n for k, v in agg.items()}
        score = avg['avg_ret_per_trade'] * (1 + avg['win_rate'] / 100)  # 综合得分
        row = {**params, **{k: round(v, 3) for k, v in avg.items()}, 'score': round(score, 4)}
        rows.append(row)
        flag = ''
        if best is None or score > best['score']:
            best = row
            flag = ' ★ 当前最优'
        print(f"[{gi+1}/{len(combos)}] {params} -> "
              f"均收益{row['total_return']:+.2f}% 交易{row['n_trades']:.1f} "
              f"胜率{row['win_rate']:.0f}% 单笔{row['avg_ret_per_trade']:+.2f}%{flag}")

    # 第二阶: 在最优买入参数下扫描卖出量能阈值
    print("\n--- 二阶: 扫描卖出信号量能阈值 ---")
    sell_params_base = {k: best[k] for k in GRID.keys()}
    for sv in SELL_GRID:
        p = {**sell_params_base, 'sell_vol_mult': sv}
        agg = {'total_return': 0, 'n_trades': 0, 'win_rate': 0, 'avg_ret_per_trade': 0}
        for code, df in datasets.items():
            r = run_one(df, p)
            for k in agg:
                agg[k] += r[k]
        n = len(datasets)
        avg = {k: v / n for k, v in agg.items()}
        row = {**p, **{k: round(v, 3) for k, v in avg.items()},
               'score': round(avg['avg_ret_per_trade'] * (1 + avg['win_rate'] / 100), 4)}
        rows.append(row)
        print(f"sell_vol_mult={sv}: 均收益{row['total_return']:+.2f}% "
              f"胜率{row['win_rate']:.0f}% 单笔{row['avg_ret_per_trade']:+.2f}%")

    out_csv = os.path.join(os.path.dirname(__file__), 'outputs', 'param_sensitivity_results.csv')
    with open(out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n结果已保存: {out_csv}")
    print(f"最优组合: {best}")


if __name__ == '__main__':
    main()
