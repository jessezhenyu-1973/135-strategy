#!/usr/bin/env python3
"""
135战法 — 任务8: DMI趋势过滤器对接
在 V17 基础上加入 DMI 入场过滤，全池对比验证（吸取任务7b教训：必须过样本外验证）。

对比方案:
  A. V17基准        — 无DMI过滤
  B. V17+DMI严格    — 仅DMI多头趋势(ADX>20且PDI>MDI+2)允许买入
  C. V17+ADX分档仓位 — B基础上按ADX强度调整试仓比例

用法:
    python3 run_dmi_fusion.py            # 全池265只
    python3 run_dmi_fusion.py --top 30   # 前30只快速验证
"""

import os
import sys
import csv
import tempfile
import argparse
import statistics as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history, df_to_csv

import backtrader as bt


class Strategy135DMI(bt.Strategy):
    """
    V17 信号体系 + 可选 DMI 趋势过滤。
    dmi_mode: 'off' = V17基准 | 'strict' = 多头趋势才买 | 'weighted' = strict + ADX分档试仓
    """
    params = (
        ('dmi_mode', 'off'),
        ('min_adx', 20),
        ('di_gap', 2.0),
        ('stop_loss_pct', 0.08),
        ('cool_down_bars', 10),
    )

    def __init__(self):
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)
        self.dmi = bt.ind.DMI(self.data, period=14)
        self.highest_price = 0.0
        self.buy_bar = -1
        self.current_shares = 0
        self.trade_log = []
        self.last_sell_signal = None
        self.blocked_by_dmi = 0   # 统计: 被DMI过滤掉的买入信号数

    # ---------- V17 原版信号逻辑 ----------
    def _is_downtrend(self):
        m = lambda i: (self.ma13[i], self.ma34[i], self.ma55[i])
        m13_0, m34_0, m55_0 = m(0)
        m13_1, m34_1, m55_1 = m(-1)
        m13_2, m34_2, m55_2 = m(-2)
        if not (m13_0 < m34_0 < m55_0):
            return False
        return (m13_0 < m13_1 < m13_2 and m34_0 < m34_1 < m34_2
                and m55_0 < m55_1 < m55_2)

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

        # 红杏出墙
        if (m13p2 <= m13p and m13 > m13p and c > m13 and c > o and
                v > vm * 1.0 and m13 > m34 > m55):
            return '红杏出墙'
        # 一阳穿三线
        if (c > o and o < m55 and o < m34 and o < m13 and
                c > m55 and c > m34 and c > m13 and v > vm * 2.0):
            return '一阳穿三线'
        # 揭竿而起
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
            avg_spread /= cnt
            if (spread < 0.015 and avg_spread < 0.02 and v > vm * 2.0 and
                    c > o and c > m13 and c > m34 and c > m55):
                return '揭竿而起'
        return None

    def _check_sell_signals(self):
        c, o = self.data.close[0], self.data.open[0]
        m13, m13p = self.ma13[0], self.ma13[-1]
        v, vm = self.data.volume[0], self.vol_ma[0]
        if v > vm * 1.5 and c < o and c < m13 and m13 < m13p:
            return '一箭穿心'
        return None

    # ---------- DMI 过滤 ----------
    def _dmi_up_trend(self):
        adx = self.dmi.adx[0]
        pdi, mdi = self.dmi.plusDI[0], self.dmi.minusDI[0]
        return (adx > self.p.min_adx and pdi > mdi + self.p.di_gap)

    def _adx_position_ratio(self):
        """ADX 分档试仓比例"""
        adx = self.dmi.adx[0]
        if adx > 40:
            return 1.0
        if adx > 30:
            return 0.8
        return 0.5  # min_adx~30

    # ---------- 主循环 ----------
    def next(self):
        if len(self.data) < 60:
            return
        price = self.data.close[0]

        if self.position:
            sig = self._check_sell_signals()
            if sig:
                self.last_sell_signal = '135卖出:' + sig
                self._sell()
                return
            if self.highest_price > 0:
                dd = (self.highest_price - price) / self.highest_price
                if dd >= self.p.stop_loss_pct:
                    self.last_sell_signal = '移动止损'
                    self._sell()
                    return
            else:
                self.highest_price = price
            return

        if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
            return

        buy_sig = self._check_buy_signals()
        if not buy_sig:
            return

        # === DMI 过滤层 ===
        if self.p.dmi_mode != 'off':
            if not self._dmi_up_trend():
                self.blocked_by_dmi += 1
                return

        cash = self.broker.getcash()
        frac = 0.10
        if self.p.dmi_mode == 'weighted':
            frac *= self._adx_position_ratio()
        n = int(cash * frac / price)
        if n >= 10:
            self.buy(size=n)
            self.buy_bar = len(self.data) - 1
            self.highest_price = price
            self.current_shares = n

    def _sell(self):
        self._exit_price = self.data.close[0]
        self.close()
        self.highest_price = 0
        self.current_shares = 0
        self.buy_bar = -1

    def notify_order(self, order):
        if order.status == order.Completed and order.isbuy():
            self._entry_price = order.executed.price
            self._entry_size = order.executed.size

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnlcomm
            ep = getattr(self, '_entry_price', trade.price)
            es = max(1, getattr(self, '_entry_size', abs(trade.size)) or abs(trade.size))
            ret = round(pnl / (ep * es) * 100, 3) if ep > 0 else 0
            self.trade_log.append({'pnl': pnl, 'return_pct': ret,
                                   'exit': self.last_sell_signal or '?'})


MODES = {'A_V17基准': 'off', 'B_DMI严格': 'strict', 'C_ADX分档': 'weighted'}


def run_one(df, mode):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))
    cerebro.addstrategy(Strategy135DMI, dmi_mode=mode)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    s = cerebro.run()[0]
    final = cerebro.broker.getvalue()
    tl = s.trade_log
    n = len(tl)
    wins = sum(1 for t in tl if t['pnl'] > 0)
    r = {
        'total_return': (final - 1000000) / 1000000 * 100,
        'n_trades': n,
        'win_rate': wins / n * 100 if n else 0,
        'avg_ret_per_trade': sum(t['return_pct'] for t in tl) / n if n else 0,
        'blocked': s.blocked_by_dmi,
    }
    os.unlink(tmp.name)
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    args = parser.parse_args()
    n = args.top if args.top > 0 else 300

    print(f"获取沪深300成分股 (前{n})...")
    codes = get_hs300_codes(n)
    datasets = {}
    for code in codes:
        df = get_stock_history(code)
        if df is not None:
            datasets[code] = df
    print(f"可用数据 {len(datasets)} 只\n开始...\n")

    agg = {m: {'total_return': [], 'n_trades': [], 'win_rate': [],
               'avg_ret_per_trade': []} for m in MODES}
    win_counts = {m: 0 for m in MODES}

    rows = []
    for i, (code, df) in enumerate(datasets.items()):
        res = {m: run_one(df, mode) for m, mode in MODES.items()}
        base_score = res['A_V17基准']['avg_ret_per_trade'] * (1 + res['A_V17基准']['win_rate'] / 100)
        line = f"[{i+1}/{len(datasets)}] {code}: "
        for m in MODES:
            r = res[m]
            for k in agg[m]:
                agg[m][k].append(r[k])
            sc = r['avg_ret_per_trade'] * (1 + r['win_rate'] / 100)
            if sc > base_score and m != 'A_V17基准':
                win_counts[m] += 1
            line += f"{r['avg_ret_per_trade']:+.1f}%/{r['win_rate']:.0f}%  "
        rows.append({'code': code, **{f'{k}_{m}': round(v, 3)
                     for m in MODES for k, v in res[m].items()}})
        print(line)

    n_all = len(datasets)
    print(f"\n{'='*66}\n全池汇总 ({n_all} 只)\n{'='*66}")
    print(f"{'指标':<18}" + "".join(f"{m:>16}" for m in MODES))
    for k in ['total_return', 'n_trades', 'win_rate', 'avg_ret_per_trade']:
        vals = [st.mean(agg[m][k]) for m in MODES]
        fmt = '.2f' if k != 'n_trades' else '.1f'
        print(f"{k:<18}" + "".join(f"{v:>16{fmt}}" for v in vals))
    print(f"{'得分占优股票数':<14}" + "".join(
        f"{('—' if m=='A_V17基准' else f'{win_counts[m]}/{n_all}') :>16}"
        for m in MODES))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dmi_fusion_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n明细已保存: {out}")


if __name__ == '__main__':
    main()
