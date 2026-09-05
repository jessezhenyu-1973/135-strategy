#!/usr/bin/env python3
"""
135战法 V18-ATR — 实盘选股器 (内存扫描版, 2026-09-05 重写数据层)

扫描全市场(或指定池), 输出当日触发买入信号的股票 + 现有持仓的ATR止损位。

数据层(与旧版的关键区别):
  旧版: 每只股票 shell 调 `hithink-finance market history` CLI, 8 线程并发 →
        CLI 各自打开 market.duckdb 加锁, 实测 87% 请求报 "Could not set lock",
        3721 只扫描 >16 分钟, cron 300s 超时必挂。
  新版: 进程内 duckdb 只读连接, 一条 SQL 把候选池全部历史K线批量拉进内存
        (470 万行, 秒级), 信号判定全内存并行; 仅"今日实时 bar"走网络:
        mootdx 批量快照(主) → 腾讯快照(备)。全程不再 shell 调 CLI, 无锁冲突。

用法:
    python3 stock_screener.py                    # 全市场预筛池(默认, 市值<200亿+非次新)
    python3 stock_screener.py --pool all --no-prefilter   # 全主板+创业板(慢, 兜底)
    python3 stock_screener.py --pool hs300       # 沪深300
    python3 stock_screener.py --watch 600519.SH,000858.SZ   # 监控持仓止损位
    python3 stock_screener.py --no-live          # 跳过实时bar(纯本地库, 离线验证用)
"""
import os
import sys
import json
import subprocess
import argparse
import datetime
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_param_sensitivity import (get_hs300_codes, get_stock_history,
                                  get_stock_history_with_today,
                                  _tencent_live_bar)

DB_PATH = os.path.expanduser('~/.local/share/hithink-finance/market.duckdb')
HIST_START = '2023-01-01'


def get_all_mainboard_codes():
    """全市场沪深A股(主板+创业板): 排除北交所、科创板(688)、ST/退市股"""
    result = subprocess.run([
        'hithink-finance', 'symbol', 'list',
        '--limit', '10000', '--format', 'json'
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    inner = data.get('data') if isinstance(data, dict) else data
    if isinstance(inner, dict):
        items = inner.get('item', [])
    elif isinstance(inner, list):
        items = inner
    else:
        items = []
    prefixes = ('600', '601', '603', '605', '000', '001', '002', '003',
                '300', '301')  # 主板 + 创业板
    codes = [i['thscode'] for i in items
             if i.get('thscode', '').startswith(prefixes)
             and 'ST' not in i.get('name', '') and '退' not in i.get('name', '')]
    return codes


def load_names():
    """{thscode: 名称}, 来自 hithink-finance symbol list(一次调用, 失败返回{})"""
    try:
        result = subprocess.run([
            'hithink-finance', 'symbol', 'list',
            '--limit', '10000', '--format', 'json'
        ], capture_output=True, text=True)
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        inner = data.get('data') if isinstance(data, dict) else data
        if isinstance(inner, dict):
            items = inner.get('item', [])
        elif isinstance(inner, list):
            items = inner
        else:
            items = []
        return {i['thscode']: i.get('name', '') for i in items if i.get('thscode')}
    except Exception:
        return {}


def load_bulk_history(codes):
    """进程内 duckdb 批量拉取候选池全部历史K线(2023起), 返回 {thscode: DataFrame}。

    只读连接, 不产生写锁; 单次 SQL, 无并发锁冲突。
    """
    import duckdb
    import pandas as pd
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        ph = ','.join(['?'] * len(codes))
        df = con.execute(
            f"SELECT thscode, date, open, high, low, close, volume "
            f"FROM v_daily WHERE thscode IN ({ph}) AND date >= ? "
            f"ORDER BY thscode, date",
            list(codes) + [HIST_START]).df()
    finally:
        con.close()
    if df.empty:
        return {}
    df = df[(df['close'] > 0) & (df['volume'] >= 0)]
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return {code: g for code, g in df.groupby('thscode', sort=False)}


def fetch_live_bars(codes, today_str):
    """批量今日实时 bar: mootdx 批量快照(主) → 腾讯逐只(备, 只补漏)。
    返回 {thscode: 1行DataFrame(open/high/low/close/volume, 单位股, 索引今日16:00)}。
    非交易日/未开市返回 {} (调用方保持纯历史序列)。"""
    out = {}
    try:
        from mootdx_live import get_live_snapshot
        snap = get_live_snapshot(codes)
        import pandas as pd
        for code, r in snap.items():
            if r.get('close', 0) <= 0 or r.get('volume', 0) <= 0:
                continue
            idx = pd.Timestamp(datetime.datetime.now().replace(
                hour=16, minute=0, second=0, microsecond=0))
            out[code] = pd.DataFrame(
                [{'open': r['open'], 'high': r['high'], 'low': r['low'],
                  'close': r['close'], 'volume': r['volume']}], index=[idx])
    except Exception:
        pass
    # 腾讯兜底: 只补缺失的, 逐只 curl(仅少量, 不会拖慢)
    # 代表股日期守卫: 先查 1 只(000001), 若腾讯快照也不是今日(非交易日/未开市),
    # 直接跳过全部逐只 curl, 避免非交易日白拉 3000+ 次 HTTP
    missing = [c for c in codes if c not in out]
    if missing:
        probe = _tencent_live_bar('000001.SZ')
        if probe is None:
            return out  # 腾讯今日也无行情, 无需逐只拉
        for c in missing:
            try:
                bar = _tencent_live_bar(c)
            except Exception:
                bar = None
            if bar is not None and bar['close'].iloc[0] > 0 and bar['volume'].iloc[0] > 0:
                out[c] = bar
    return out


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

    detail = {'close': round(float(cl), 2), 'ma13': round(float(m13), 2),
              'ma55': round(float(m55), 2),
              'vol_ratio': round(float(vol / vm), 2) if vm > 0 else 0}

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
    return round(float(h - mult * atr), 2)


def append_live(df, live):
    """把今日实时 bar 拼到历史序列末尾(去重+排序), 逻辑与旧版一致。"""
    if live is None:
        return df
    last_date = df.index[-1].date()
    if last_date >= live.index[0].date():
        return df  # 本地库已含今日, 无需重复
    combined = pd.concat([df, live])
    combined = combined[~combined.index.duplicated(keep='last')]
    combined.sort_index(inplace=True)
    return combined


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pool', choices=['hs300', 'all'], default='all')
    parser.add_argument('--watch', type=str, help='逗号分隔的持仓代码, 输出ATR止损位')
    parser.add_argument('--no-prefilter', action='store_true',
                        help='跳过市值/次新预筛, 扫描全部主板+创业板(慢, 兜底用)')
    parser.add_argument('--workers', type=int, default=8,
                        help='信号判定并行线程数(默认8; 数据已批量入内存, 无锁冲突)')
    parser.add_argument('--no-live', action='store_true',
                        help='跳过实时bar, 纯本地库(离线验证/非交易日调试)')
    args = parser.parse_args()

    today = datetime.datetime.now().strftime('%Y%m%d')

    if args.watch:
        print(f"=== 持仓ATR止损监控 ===")
        watch_codes = [c.strip() for c in args.watch.split(',')]
        hist = load_bulk_history(watch_codes)
        live = {} if args.no_live else fetch_live_bars(watch_codes, today)
        for code in watch_codes:
            df = hist.get(code)
            if df is None or len(df) == 0:
                # 兜底: 本地库缺该股时走原 CLI 路径
                df = get_stock_history_with_today(code, end_date=today)
            if df is None:
                print(f"{code}: 数据获取失败")
                continue
            df = append_live(df, live.get(code))
            stop = atr_stop_level(df)
            cur = df['close'].iloc[-1]
            status = '⚠️ 已跌破止损位!' if cur <= stop else '✓ 持有'
            print(f"{code}: 现价{cur:.2f} | 止损位{stop:.2f} | {status}")
        return

    if args.pool == 'all':
        if args.no_prefilter:
            print("获取全市场沪深A股(主板+创业板, 排除北交所/科创板/ST)...")
            codes = get_all_mainboard_codes()
        else:
            print("预筛: 排除次新股(上市<1年)与总市值>=200亿的股票...")
            from prefilter_universe import prefilter_universe
            codes = prefilter_universe()
            print(f"预筛后候选 {len(codes)} 只")
    else:
        print("获取沪深300成分股...")
        codes = get_hs300_codes(300)
    if not codes:
        print("错误: 候选池为空, 退出")
        return
    print(f"共{len(codes)}只, 批量加载本地DuckDB历史K线(内存扫描)...")

    hist = load_bulk_history(codes)
    print(f"本地库加载完成: {len(hist)} 只有历史数据")

    latest = None
    try:
        import duckdb as _duckdb
        _con = _duckdb.connect(DB_PATH, read_only=True)
        latest = _con.execute("SELECT MAX(date) FROM v_daily").fetchone()[0]
        _con.close()
    except Exception:
        latest = None

    live = {} if args.no_live else fetch_live_bars(codes, today)
    print(f"今日实时bar: {len(live)} 只 (mootdx主/腾讯备; 0=非交易日或取数失败, 用本地库)")

    names = load_names()

    hits = []
    total = len(codes)
    done = 0
    lock = threading.Lock()

    def worker(code):
        nonlocal done
        df = hist.get(code)
        if df is None or len(df) == 0:
            return None
        df = append_live(df, live.get(code))
        last_date = df.index[-1]
        if isinstance(last_date, tuple):
            return None
        # 停牌过滤: 最新日期早于最新交易日(且实时bar也补不上) → 停牌/无数据
        if latest is not None and live.get(code) is None:
            last_date_val = last_date.to_pydatetime().date() if hasattr(last_date, 'to_pydatetime') else last_date
            latest_date_val = latest.date() if hasattr(latest, 'date') and callable(getattr(latest, 'date')) else latest
            if last_date_val != latest_date_val:
                return None
        if (df['volume'].tail(5) == 0).any():
            return None
        sig, detail = check_signals(df)
        if not sig:
            return None
        stop = atr_stop_level(df)
        # 涨停标记: 创业板(300/301) 20%, 主板 10%
        # 倒数第二根即昨日收盘(无论是否拼了实时bar)
        cl = float(df['close'].iloc[-1])
        prev = float(df['close'].iloc[-2]) if len(df) >= 2 else None
        change_pct = None
        if prev and prev > 0:
            change_pct = round((cl - prev) / prev * 100, 2)
        limit_pct = 20.0 if code.startswith(('300', '301')) else 10.0
        limit_up = bool(change_pct is not None and change_pct >= limit_pct * 0.995)
        return {'code': code, 'name': names.get(code, ''), 'signal': sig,
                **detail, 'atr_stop': stop, 'date': str(df.index[-1].date()),
                'change_pct': change_pct, 'limit_up': limit_up}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(worker, c): c for c in codes}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:
                r = None
                with lock:
                    print(f"  ! {futures[fut]} 异常: {e}")
            if r:
                with lock:
                    hits.append(r)
                    flag = ' [涨停]' if r['limit_up'] else ''
                    print(f"★ {r['code']} {r['name']} [{r['signal']}] 收盘{r['close']} "
                          f"涨{r['change_pct']}% 量比{r['vol_ratio']}x ATR止损位{r['atr_stop']}{flag}")
            done += 1
            if done % 500 == 0:
                print(f"  ...已扫描{done}/{total} (命中{len(hits)})")

    hits.sort(key=lambda x: x['code'])
    print(f"\n{'='*60}")
    print(f"今日触发信号: {len(hits)} 只 (其中涨停 {sum(1 for h in hits if h['limit_up'])} 只)")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screener_today.json')
    with open(out, 'w') as f:
        json.dump(hits, f, ensure_ascii=False, indent=2)
    print(f"结果: {out}")


if __name__ == '__main__':
    main()
