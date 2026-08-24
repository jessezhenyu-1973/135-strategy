#!/usr/bin/env python3
"""
135战法 — 任务10前置: 板块动量 + 龙头过滤验证
结构性市场假设下: 仅在强势板块中用V17选股, 是否优于全池选股?

设计(防未来函数):
- 板块动量: 每月末计算各行业指数过去20日涨幅, 取前20%为"强板块"
- 个股归属板块: 用同花顺行业指数成分查询
- 龙头定义: 强板块内, 过去60日个股涨幅排名板块内前30%
- 回测时点t只使用t之前的数据判定强板块/龙头

用法:
    python3 run_sector_momentum.py            # 全池
    python3 run_sector_momentum.py --top 100
"""

import os
import sys
import json
import csv
import subprocess
import tempfile
import datetime
import argparse
import statistics as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history, df_to_csv

import backtrader as bt
import pandas as pd

CACHE = '/tmp/sector_cache'
os.makedirs(CACHE, exist_ok=True)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


# ============================================================
# 行业指数日线 + 成分
# ============================================================

def get_industry_indexes():
    out = sh(['hithink-finance', 'index', 'catalog', '--tag', 'industry', '--format', 'json'])
    if not out:
        return []
    items = json.loads(out)['data']['item']
    # 只取一级行业 (881xxx.TI), 数量约90个
    return [(i['thscode'], i['name']) for i in items if i['thscode'].startswith('881')]


def get_index_history(code, start='20221001', end='20260813'):
    f = f'{CACHE}/idx_{code.split(".")[0]}.json'
    if os.path.exists(f):
        with open(f) as fh:
            return json.load(fh)
    s = int(datetime.datetime.strptime(start, '%Y%m%d').timestamp() * 1000)
    e = int(datetime.datetime.strptime(end, '%Y%m%d').timestamp() * 1000)
    out = sh(['hithink-finance', 'index', 'history', '--thscode', code,
              '--start-ms', str(s), '--end-ms', str(e), '--format', 'json'])
    if not out:
        return None
    try:
        data = json.loads(out)['data']['item']
    except Exception:
        return None
    if not data:
        return None
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date_ms'], unit='ms')
    res = {'date': list(df['date'].dt.strftime('%Y%m%d')), 'close': list(df['close_price'])}
    with open(f, 'w') as fh:
        json.dump(res, fh)
    return res


def get_constituents(code):
    f = f'{CACHE}/cons_{code.split(".")[0]}.json'
    if os.path.exists(f):
        with open(f) as fh:
            return json.load(fh)
    out = sh(['hithink-finance', 'index', 'constituents', '--thscode', code,
              '--format', 'json'])
    if not out:
        return []
    try:
        items = json.loads(out)['data']['item']
        codes = [i['thscode'] for i in items if i.get('thscode')]
    except Exception:
        codes = []
    with open(f, 'w') as fh:
        json.dump(codes, fh)
    return codes


def month_end_momentum(idx_hist, lookback=20):
    """返回 {月末日期: {板块code: 20日涨幅}}，只用截至当日的数据"""
    dates, closes = idx_hist['date'], idx_hist['close']
    ser = dict(zip(dates, closes))
    dts = sorted(ser.keys())
    result = {}
    seen_months = set()
    for i, d in enumerate(dts):
        ym = d[:6]
        if ym in seen_months:
            continue
        # 月末最后一个交易日附近: 下一个月的第一天出现时回填
        nxt_month = None
        prev_d = dts[i - lookback] if i >= lookback else None
        if prev_d:
            # 判断是否跨月（简化：每月第一个交易日触发，用前一日数据）
            if i > 0 and dts[i - 1][:6] != ym or i == 0:
                pass
        seen_months.add(ym)
    return result


def build_strong_sectors(indexes, top_pct=0.2, lookback=20):
    """
    返回 {月末交易日: set(强板块code)}
    规则: 每月最后一个交易日, 计算各板块lookback日动量, 排名前top_pct为强板块
    该集合从下一交易日起生效（无未来函数）
    """
    hist = {}
    common_dates = None
    for code, name in indexes:
        h = get_index_history(code)
        if not h or len(h['date']) < lookback + 5:
            continue
        hist[code] = dict(zip(h['date'], h['close']))
        ds = set(h['date'])
        common_dates = ds if common_dates is None else (common_dates & ds)
    all_dates = sorted(common_dates) if common_dates else []

    strong_by_date = {}   # 生效起始日 -> 强板块set
    last_month = None
    for i, d in enumerate(all_dates):
        ym = d[:6]
        if last_month is not None and ym != last_month and i >= lookback:
            # d是新月第一天: 用截至前一交易日的数据算上月末动量
            prev_i = i - 1
            mom = {}
            for code, m in hist.items():
                c_now = m.get(all_dates[prev_i])
                c_past = m.get(all_dates[prev_i - lookback]) if prev_i >= lookback else None
                if c_now and c_past and c_past > 0:
                    mom[code] = c_now / c_past - 1
            ranked = sorted(mom.items(), key=lambda x: -x[1])
            k = max(1, int(len(ranked) * top_pct))
            strong_by_date[d] = set(c for c, _ in ranked[:k])
        last_month = ym
    return strong_by_date


# ============================================================
# V17 策略（复用）+ 板块/龙头过滤
# ============================================================

class Strategy135Sector(bt.Strategy):
    """V17信号 + 日期感知的板块/龙头过滤层。
    allow_fn(date_str) -> 'no' | 'sector' | 'leader'，由批量层注入。
    """
    params = (('stop_loss_pct', 0.08), ('cool_down_bars', 10),
              ('allow_fn', None), ('mode', 'full'))

    def __init__(self):
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)
        self.highest_price = 0.0
        self.buy_bar = -1
        self.trade_log = []
        self.last_sell_signal = None

    def _is_downtrend(self):
        a = lambda idx: (self.ma13[idx], self.ma34[idx], self.ma55[idx])
        m13_0, m34_0, m55_0 = a(0); m13_1, m34_1, m55_1 = a(-1); m13_2, m34_2, m55_2 = a(-2)
        if not (m13_0 < m34_0 < m55_0):
            return False
        return m13_0 < m13_1 < m13_2 and m34_0 < m34_1 < m34_2 and m55_0 < m55_1 < m55_2

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
        if (m13p2 <= m13p and m13 > m13p and c > m13 and c > o and v > vm and m13 > m34 > m55):
            return '红杏出墙'
        if (c > o and o < m55 and o < m34 and o < m13 and c > m55 and c > m34 and c > m13 and v > vm * 2.0):
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
            if spread < 0.015 and avg_spread < 0.02 and v > vm * 2.0 and c > o and c > m13 and c > m34 and c > m55:
                return '揭竿而起'
        return None

    def _sell_signal(self):
        c, o = self.data.close[0], self.data.open[0]
        m13, m13p = self.ma13[0], self.ma13[-1]
        v, vm = self.data.volume[0], self.vol_ma[0]
        if v > vm * 1.5 and c < o and c < m13 and m13 < m13p:
            return '一箭穿心'
        return None

    def next(self):
        if len(self.data) < 60:
            return
        price = self.data.close[0]
        if self.position:
            sig = self._sell_signal()
            if sig:
                self.last_sell_signal = sig
                self._exit_price = price
                self.close()
                self.highest_price = 0
                self.buy_bar = -1
                return
            dd = (self.highest_price - price) / self.highest_price if self.highest_price > 0 else 0
            if dd >= self.p.stop_loss_pct:
                self.last_sell_signal = '移动止损'
                self._exit_price = price
                self.close()
                self.highest_price = 0
                self.buy_bar = -1
            elif self.highest_price == 0:
                self.highest_price = price
            return

        if self.buy_bar >= 0 and len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars:
            return
        if not self._buy_signal():
            return
        # === 板块/龙头过滤（日期感知，无未来函数） ===
        if self.p.allow_fn is not None:
            d = str(self.data.datetime.date(0)).replace('-', '')
            level = self.p.allow_fn(d)
            if level == 'no':
                return
            if self.p.mode == 'leader' and level != 'leader':
                return
        cash = self.broker.getcash()
        n = int(cash * 0.10 / price)
        if n >= 10:
            self.buy(size=n)
            self.buy_bar = len(self.data) - 1
            self.highest_price = price

    def notify_order(self, order):
        if order.status == order.Completed and order.isbuy():
            self._entry_price = order.executed.price
            self._entry_size = order.executed.size

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnlcomm
            ep = getattr(self, '_entry_price', trade.price)
            es = max(1, getattr(self, '_entry_size', abs(trade.size)) or abs(trade.size))
            self.trade_log.append({
                'pnl': pnl,
                'return_pct': round(pnl / (ep * es) * 100, 3) if ep > 0 else 0,
                'exit': self.last_sell_signal or '?'})


def backtest_df(df, allow_fn=None, mode='full'):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    df_to_csv(df, tmp.name)
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=tmp.name, dtformat='%Y%m%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True))
    cerebro.addstrategy(Strategy135Sector, allow_fn=allow_fn, mode=mode)
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    s = cerebro.run()[0]
    final = cerebro.broker.getvalue()
    tl = s.trade_log
    n = len(tl)
    wins = sum(1 for t in tl if t['pnl'] > 0)
    os.unlink(tmp.name)
    return {
        'total_return': (final - 1e6) / 1e6 * 100,
        'n_trades': n,
        'win_rate': wins / n * 100 if n else 0,
        'avg_ret_per_trade': sum(t['return_pct'] for t in tl) / n if n else 0,
    }


def stock_60d_return(df, date_str, lookback=60):
    """个股截至date_str的lookback日涨幅（龙头判定用，无未来函数）"""
    sub = df[df.index.strftime('%Y%m%d') <= date_str]
    if len(sub) < lookback:
        return None
    c_now = sub['close'].iloc[-1]
    c_past = sub['close'].iloc[-lookback]
    return c_now / c_past - 1 if c_past > 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=300)
    args = parser.parse_args()

    print("构建行业指数动量数据...")
    indexes = get_industry_indexes()
    strong_map = build_strong_sectors(indexes)
    print(f"行业指数 {len(indexes)} 个, 强板块切换点 {len(strong_map)} 个月")

    print("构建板块->成分股映射...")
    sector_of_stock = {}
    for code, name in indexes:
        for sc in get_constituents(code):
            sector_of_stock.setdefault(sc, []).append(code)

    print(f"获取沪深300 (前{args.top})...")
    codes = get_hs300_codes(args.top)
    datasets = {}
    for c in codes:
        df = get_stock_history(c)
        if df is not None:
            datasets[c] = df

    def is_in_strong_sector(code, date_str):
        """该股在date_str当日是否处于强板块（用最近一个生效日的集合）"""
        secs = sector_of_stock.get(code, [])
        applicable = [d for d in sorted(strong_map.keys()) if d <= date_str]
        if not applicable:
            return False   # 数据不足期间不交易（保守）
        strong = strong_map[applicable[-1]]
        return any(s in strong for s in secs)

    # 预计算每只股票每个交易日的板块状态: 'no' | 'sector'
    # 以及龙头判定所需的历史60日动量序列
    print("预计算个股每日板块状态...")
    status_cache = {}   # code -> {date: 'no'|'sector'}
    for i, (code, df) in enumerate(sorted(datasets.items())):
        applicable = sorted(d for d in strong_map.keys())
        st_map = {}
        cur = 'no'
        ai = 0
        for d in df.index.strftime('%Y%m%d'):
            while ai < len(applicable) and applicable[ai] <= d:
                cur = None  # 占位，下面重算
                ai += 1
            if ai > 0:
                strong = strong_map[applicable[ai - 1]]
                secs = sector_of_stock.get(code, [])
                cur = 'sector' if any(s in strong for s in secs) else 'no'
            else:
                cur = 'no'
            st_map[d] = cur
        status_cache[code] = st_map

    groups = {'A_全池': [], 'B_强板块': [], 'C_强板块龙头': []}
    rows = []
    print("分组回测...")
    for i, (code, df) in enumerate(sorted(datasets.items())):
        dates_idx = list(df.index.strftime('%Y%m%d'))
        st_map = status_cache[code]

        def allow_sector(d, _m=st_map):
            return _m.get(d, 'no')

        def allow_leader(d, _df=df, _m=st_map):
            lvl = _m.get(d, 'no')
            if lvl != 'sector':
                return 'no'
            mom = stock_60d_return(_df, d)
            return 'leader' if (mom is not None and mom > 0.10) else 'sector'

        r_full = backtest_df(df)
        r_strong = backtest_df(df, allow_fn=allow_sector, mode='sector')
        r_leader = backtest_df(df, allow_fn=allow_leader, mode='leader')

        groups['A_全池'].append(r_full)
        groups['B_强板块'].append(r_strong)
        groups['C_强板块龙头'].append(r_leader)
        rows.append({'code': code,
                     **{f'{k}_full': round(v, 3) for k, v in r_full.items()},
                     **{f'{k}_strong': round(v, 3) for k, v in r_strong.items()},
                     **{f'{k}_leader': round(v, 3) for k, v in r_leader.items()}})
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(datasets)}")

    print(f"\n{'='*70}")
    print(f"{'组别':<14}{'票数':>6}{'均总收益%':>12}{'胜率%':>10}{'单笔收益%':>12}{'交易数':>8}")
    for g, lst in groups.items():
        if not lst:
            continue
        print(f"{g:<14}{len(lst):>6}"
              f"{st.mean(x['total_return'] for x in lst):>12.2f}"
              f"{st.mean(x['win_rate'] for x in lst):>10.1f}"
              f"{st.mean(x['avg_ret_per_trade'] for x in lst):>12.2f}"
              f"{st.mean(x['n_trades'] for x in lst):>8.1f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sector_momentum_results.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\n明细: {out}")


if __name__ == '__main__':
    main()
