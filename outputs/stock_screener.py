#!/usr/bin/env python3
"""
135战法 V18-ATR — 实盘选股器
扫描全市场(或指定池), 输出当日触发买入信号的股票 + 现有持仓的ATR止损位。

用法:
    python3 stock_screener.py                    # 沪深300
    python3 stock_screener.py --pool all         # 全市场A股(慢)
    python3 stock_screener.py --watch 600519.SH,000858.SZ   # 监控持仓止损位
"""
import os
import sys
import json
import subprocess
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import get_hs300_codes, get_stock_history

def get_all_mainboard_codes():
    """全市场沪深A股(主板+创业板): 排除北交所、科创板(688)、ST/退市股"""
    result = subprocess.run([
        'hithink-finance', 'symbol', 'list',
        '--limit', '10000', '--format', 'json'
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    items = data.get('data', {}).get('item', [])
    prefixes = ('600', '601', '603', '605', '000', '001', '002', '003',
                '300', '301')  # 主板 + 创业板
    codes = [i['thscode'] for i in items
             if i.get('thscode', '').startswith(prefixes)
             and 'ST' not in i.get('name', '') and '退' not in i.get('name', '')]
    return codes


import pandas as pd


def check_signals(df):
    """对单只股票最新交易日检查V18-ATR买入信号, 返回 (信号名|None, 详情)"""
    if len(df) < 60:
        return None, {}
    c = df['close']
    o = df['open']
    v = df['volume']
    ma13 = c.rolling(13).mean()
    ma34 = c.rolling(34).mean()
    ma55 = c.rolling(55).mean()
    vol_ma = v.rolling(5).mean()

    i = -1  # 最新一根
    cl, op = c.iloc[i], o.iloc[i]
    m13, m34, m55 = ma13.iloc[i], ma34.iloc[i], ma55.iloc[i]
    m13p = ma13.iloc[i - 1]
    m13p2 = ma13.iloc[i - 2]
    vol, vm = v.iloc[i], vol_ma.iloc[i]

    detail = {'close': round(cl, 2), 'ma13': round(m13, 2), 'ma55': round(m55, 2),
              'vol_ratio': round(vol / vm, 2) if vm > 0 else 0}

    # 前置过滤
    if m13 < m34 < m55 and \
       ma13.iloc[i] < m13p < m13p2 and \
       ma34.iloc[i] < ma34.iloc[i-1] < ma34.iloc[i-2] and \
       m55 < ma55.iloc[i-1] < ma55.iloc[i-2]:
        return None, detail  # 下降趋势
    if cl < m55:
        return None, detail  # 价格低于MA55
    m55_5 = ma55.iloc[i - 5]
    if m55_5 > 0 and (m55_5 - m55) / m55_5 > 0.05:
        return None, detail  # MA55急跌

    signals = []
    # 红杏出墙
    if (m13p2 <= m13p and m13 > m13p and cl > m13 and cl > op and
            vol > vm and m13 > m34 > m55):
        signals.append('红杏出墙')
    # 一阳穿三线
    if (cl > op and op < m55 and op < m34 and op < m13 and
            cl > m55 and cl > m34 and cl > m13 and vol > vm * 2.0):
        signals.append('一阳穿三线')
    # 揭竿而起
    if vm > 0:
        spread = (max(m13, m34, m55) - min(m13, m34, m55)) / max(m13, m34, m55)
        avg_spread = 0.0
        for k in range(5):
            a13 = m13 if k == 0 else ma13.iloc[i - k]
            a34 = m34 if k == 0 else ma34.iloc[i - k]
            a55 = m55 if k == 0 else ma55.iloc[i - k]
            ms, mn = max(a13, a34, a55), min(a13, a34, a55)
            avg_spread += (ms - mn) / ms if ms > 0 else 0
        avg_spread /= 5
        if spread < 0.015 and avg_spread < 0.02 and vol > vm * 2.0 and cl > op and cl > m13 and cl > m34 and cl > m55:
            signals.append('揭竿而起')

    if not signals:
        return None, detail
    return '+'.join(signals), detail


def atr_stop_level(df, period=14, mult=2.5):
    """计算当前ATR追踪止损位（基于近期持有最高价需人工输入, 此处用近20日最高价代理）"""
    h = df['high'].tail(20).max()
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift()).abs()
    tr3 = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.tail(period).mean()
    return round(h - mult * atr, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pool', choices=['hs300', 'all'], default='all')
    parser.add_argument('--watch', type=str, help='逗号分隔的持仓代码, 输出ATR止损位')
    args = parser.parse_args()

    if args.watch:
        print(f"=== 持仓ATR止损监控 ===")
        for code in args.watch.split(','):
            df = get_stock_history(code.strip())
            if df is None:
                print(f"{code}: 数据获取失败")
                continue
            stop = atr_stop_level(df)
            cur = df['close'].iloc[-1]
            status = '⚠️ 已跌破止损位!' if cur <= stop else '✓ 持有'
            print(f"{code}: 现价{cur:.2f} | 止损位{stop:.2f} | {status}")
        return

    if args.pool == 'all':
        print("获取全市场沪深A股(主板+创业板, 排除北交所/科创板/ST)...")
        codes = get_all_mainboard_codes()
    else:
        print("获取沪深300成分股...")
        codes = get_hs300_codes(300)
    print(f"共{len(codes)}只, 开始扫描...\n")

    hits = []
    today = datetime.datetime.now().strftime('%Y%m%d')
    for i, code in enumerate(codes):
        df = get_stock_history(code, start_date='20230101', end_date=today)
        if df is None:
            continue
        # 排除停牌股: 最新5根K线内有0成交量或最新日期距今超过7天视为停牌/无数据
        last_date = df.index[-1]
        if isinstance(last_date, tuple):
            continue
        days_since = (datetime.datetime.now() - last_date.to_pydatetime()).days
        if days_since > 7:
            continue
        if (df['volume'].tail(5) == 0).any():
            continue
        sig, detail = check_signals(df)
        if sig:
            stop = atr_stop_level(df)
            hits.append({'code': code, 'signal': sig, **detail,
                         'atr_stop': stop, 'date': str(df.index[-1].date())})
            print(f"★ {code} [{sig}] 收盘{detail['close']} "
                  f"量比{detail['vol_ratio']}x ATR止损位{stop}")
        if (i + 1) % 50 == 0:
            print(f"  ...已扫描{i+1}/{len(codes)}")

    print(f"\n{'='*60}")
    print(f"今日触发信号: {len(hits)} 只")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screener_today.json')
    with open(out, 'w') as f:
        json.dump(hits, f, ensure_ascii=False, indent=2)
    print(f"结果: {out}")


if __name__ == '__main__':
    main()
