#!/usr/bin/env python3
"""
135战法 — 方案E验证: 领先性龙头过滤
定义: 某板块内第一只触发135买入信号的股票 = 该板块本轮的"龙头信号"
      其后 N 日内同板块其他股票触发的同类信号 = "跟随信号"（质量更高, 允许买入）
      无龙头在先的孤立信号 = 板块未启动, 过滤掉

无未来函数: 判定只用当日及之前的数据。

对比:
  A. V17基准（全池, 无过滤）
  E. 领先龙头过滤 — 仅当该股所属板块在 lookback 日内已有其他股票触发过135信号时才允许买入

用法:
    python3 run_leadership_filter.py            # 全池
    python3 run_leadership_filter.py --top 30
"""

import os
import sys
import csv
import json
import argparse
import datetime
import statistics as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history, df_to_csv
from run_sector_momentum import get_industry_indexes, get_constituents
from run_dmi_fusion import Strategy135DMI  # 复用V17信号策略(dmi_mode='off')

import backtrader as bt


# ============================================================
# 第一遍: 扫描所有股票的全部135买入信号日期（用V17逻辑离线重放）
# ============================================================

def scan_buy_signals(df):
    """离线重放V17买入信号检测，返回 {date_str: signal_name}"""
    import backtrader as bt_
    tmp = '/tmp/_scan_tmp.csv'
    df_to_csv(df, tmp)
    cerebro = bt_.Cerebro()
    cerebro.adddata(bt_.feeds.GenericCSVData(
        dataname=tmp, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))

    signals = {}

    class Scanner(bt_.Strategy):
        params = (('stop_loss_pct', 0.08), ('cool_down_bars', 10))

        def __init__(self):
            self.ma13 = bt_.ind.SMA(self.data.close, period=13)
            self.ma34 = bt_.ind.SMA(self.data.close, period=34)
            self.ma55 = bt_.ind.SMA(self.data.close, period=55)
            self.vol_ma = bt_.ind.SMA(self.data.volume, period=5)
            self.buy_bar = -1
            self.highest = 0.0

        def _is_downtrend(self):
            a = lambda i: (self.ma13[i], self.ma34[i], self.ma55[i])
            m0, m1, m2 = a(0), a(-1), a(-2)
            if not (m0[0] < m0[1] < m0[2]):
                return False
            return m0[0] < m1[0] < m2[0] and m0[1] < m1[1] < m2[1] and m0[2] < m1[2] < m2[2]

        def _buy_signal(self):
            c, o = self.data.close[0], self.data.open[0]
            m13, m34, m55 = self.ma13[0], self.ma34[0], self.ma55[0]
            m13p, m13p2 = self.ma13[-1], self.ma13[-2]
            v, vm = self.data.volume[0], self.vol_ma[0]
            if self._is_downtrend() or c < m55:
                return None
            m55_5 = self.ma55[-5]
            if m55_5 > 0 and (m55_5 - m55) / m55_5 > 0.05:
                return None
            if (m13p2 <= m13p and m13 > m13p and c > m13 and c > o and
                    v > vm and m13 > m34 > m55):
                return '红杏出墙'
            if (c > o and o < m55 and o < m34 and o < m13 and
                    c > m55 and c > m34 and c > m13 and v > vm * 2.0):
                return '一阳穿三线'
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

        def next(self):
            if len(self.data) < 60:
                return
            price = self.data.close[0]
            if self.position:
                if self.highest > 0:
                    dd = (self.highest - price) / self.highest
                    if dd >= self.p.stop_loss_pct:
                        self.highest = 0
                        self.buy_bar = len(self.data) - 1  # 卖出即冷却
                        return
                else:
                    self.highest = price
                return
            if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
                return
            sig = self._buy_signal()
            if sig:
                d = str(self.data.datetime.date(0)).replace('-', '')
                signals[d] = sig
                # 模拟试仓进入冷却（与真实回测一致）
                n = int(self.broker.getcash() * 0.10 / price)
                if n >= 10:
                    self.buy(size=n)
                    self.highest = price

        def notify_trade(self, trade):
            if trade.isclosed:
                pass

    cerebro.addstrategy(Scanner)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.run()
    os.unlink(tmp)
    return signals


def main():
    def f(r, k):
        return float(r[k])

    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    parser.add_argument('--leader-window', type=int, default=10,
                        help='龙头信号后N日内的跟随信号有效')
    args = parser.parse_args()
    W = args.leader_window

    print("构建板块->成分股映射...")
    indexes = get_industry_indexes()
    sector_of_stock = {}
    for code, name in indexes:
        for sc in get_constituents(code):
            sector_of_stock.setdefault(sc, []).append(code)

    n = args.top if args.top > 0 else 300
    print(f"获取沪深300 (前{n})...")
    codes = get_hs300_codes(n)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df
    print(f"可用数据 {len(datasets)} 只")

    # ---- 第一遍: 扫描每只股票的信号日 ----
    print("扫描全部股票的135信号日期...")
    stock_signals = {}   # code -> {date: signal}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        try:
            stock_signals[code] = scan_buy_signals(df)
        except Exception as e:
            print(f"  scan err {code}: {e}")
            stock_signals[code] = {}
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(datasets)}")
    total_sigs = sum(len(s) for s in stock_signals.values())
    print(f"共扫描到 {total_sigs} 个买入信号时点")

    # ---- 构建每个板块每个交易日的"龙头已启动"状态 ----
    # leader_active[sector][date] = 该板块近W日内是否有股票触发过信号(不含自己判定时点之后的数据)
    print("构建板块龙头激活时间线...")
    from collections import defaultdict
    sector_sig_dates = defaultdict(list)   # sector -> sorted [date_str]
    for code, sigs in stock_signals.items():
        for d in sigs:
            for sec in sector_of_stock.get(code, []):
                sector_sig_dates[sec].append(d)
    for sec in sector_sig_dates:
        sector_sig_dates[sec] = sorted(set(sector_sig_dates[sec]))

    def date_diff_days(d1, d2):
        """近似交易日差: 用自然日/1.4估算, 足够用于窗口判断"""
        dt1 = datetime.datetime.strptime(d1, '%Y%m%d')
        dt2 = datetime.datetime.strptime(d2, '%Y%m%d')
        return abs((dt2 - dt1).days) / 1.4

    def sector_has_recent_leader(code, d):
        """code所属任一板块在d之前W交易日内有其他股票发过信号?"""
        for sec in sector_of_stock.get(code, []):
            ds = sector_sig_dates.get(sec, [])
            lo, hi = 0, len(ds)
            while lo < hi:
                mid = (lo + hi) // 2
                if ds[mid] < d:
                    lo = mid + 1
                else:
                    hi = mid
            # ds[lo-1] 是最近的过去信号日
            if lo > 0:
                dd = date_diff_days(ds[lo - 1], d)
                if dd <= W + 2:
                    return True
        return False

    # ---- 第二遍: 带过滤回测 ----
    def make_allow_fn(code):
        def allow(d):
            # 自己的信号日如果就是板块内最早的那个 → 是龙头本身, 允许买(龙头也要买!)
            own = stock_signals.get(code, {}).get(d)
            if own:
                # 是否为板块内近W日第一个信号?
                for sec in sector_of_stock.get(code, []):
                    ds = [x for x in sector_sig_dates.get(sec, [])]
                    past = [x for x in ds if x <= d and date_diff_days(x, d) <= W + 2]
                    if past and min(past) == d:
                        return 'ok'   # 我是龙头, 直接买
            if sector_has_recent_leader(code, d):
                return 'ok'
            return 'no'
        return allow

    print("分组回测 (A基准 vs E领先龙头)...")
    agg = {'A': [], 'E': []}
    rows = []
    for i, (code, df) in enumerate(sorted(datasets.items())):
        r_a = backtest_plain(df)
        r_e = backtest_with_allow(df, make_allow_fn(code))
        agg['A'].append(r_a)
        agg['E'].append(r_e)
        rows.append({'code': code,
                     **{f'{k}_a': round(v, 3) for k, v in r_a.items()},
                     **{f'{k}_e': round(v, 3) for k, v in r_e.items()}})
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(datasets)}")

    n_all = len(datasets)
    e_better = sum(1 for r in rows
                   if f(r,'avg_ret_per_trade_e')*(1+f(r,'win_rate_e')/100) >
                      f(r,'avg_ret_per_trade_a')*(1+f(r,'win_rate_a')/100))
    print(f"\n{'='*60}\n全池汇总 ({n_all} 只)\n{'='*60}")
    print(f"{'指标':<18}{'A_V17基准':>14}{'E_领先龙头':>14}")
    for k in ['total_return', 'n_trades', 'win_rate', 'avg_ret_per_trade']:
        ma = st.mean(x[k] for x in agg['A'])
        me = st.mean(x[k] for x in agg['E'])
        print(f"{k:<18}{ma:>14.2f}{me:>14.2f}")
    print(f"\nE得分占优: {e_better}/{n_all} ({e_better/n_all*100:.0f}%)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leadership_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"明细: {out}")


def f(r, k):
    return float(r[k])


def backtest_plain(df):
    return run_strategy(df, None)


def backtest_with_allow(df, allow_fn):
    return run_strategy(df, allow_fn)


def run_strategy(df, allow_fn):
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))

    class Wrapped(Strategy135DMI):
        pass

    # 注入allow_fn: 通过params传递给Strategy135DMI不支持, 在此包装next
    cerebro.addstrategy(Wrapped, dmi_mode='off')

    # 简化实现: 若提供allow_fn, 用自定义子类拦截
    if allow_fn is not None:
        cerebro = bt.Cerebro()
        cerebro.adddata(bt.feeds.GenericCSVData(
            dataname=tmp.name, dtformat='%Y%m%d',
            datetime=0, open=1, high=2, low=3, close=4, volume=5,
            openinterest=-1, headers=True))

        class WithAllow(Strategy135DMI):
            p_allow = staticmethod(allow_fn)
            params = (('stop_loss_pct', 0.08), ('cool_down_bars', 10),
                      ('dmi_mode', 'off'), ('min_adx', 20), ('di_gap', 2.0))

            def __init__(self):
                super().__init__()
                self._orig_execute = None

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
                d = str(self.data.datetime.date(0)).replace('-', '')
                if self.p_allow(d) == 'no':
                    self.blocked_by_dmi += 1
                    return
                cash = self.broker.getcash()
                nn = int(cash * 0.10 / price)
                if nn >= 10:
                    self.buy(size=nn)
                    self.buy_bar = len(self.data) - 1
                    self.highest_price = price

        cerebro.addstrategy(WithAllow)

    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    s = cerebro.run()[0]
    final = cerebro.broker.getvalue()
    tl = s.trade_log
    ntr = len(tl)
    wins = sum(1 for t in tl if t['pnl'] > 0)
    os.unlink(tmp.name)
    return {
        'total_return': (final - 1e6) / 1e6 * 100,
        'n_trades': ntr,
        'win_rate': wins / ntr * 100 if ntr else 0,
        'avg_ret_per_trade': sum(t['return_pct'] for t in tl) / ntr if ntr else 0,
    }


if __name__ == '__main__':
    main()
