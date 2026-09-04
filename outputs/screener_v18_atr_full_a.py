#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""135战法 V18-ATR - 全A股盘中扫描器 (本地 DuckDB 离线版 + 腾讯实时快照校准)

扫描范围: 全市场A股, 硬过滤掉 科创板(688/689) / 北交所(BJ) / ST / 停牌
输出: 触发V18-ATR买入信号的候选, 按信号强度排序, 取前若干只推荐

数据源:
  - 日K骨架: hithink-finance 本地 DuckDB (--source local)
    默认路径: ~/.local/share/hithink-finance/market.duckdb
    (无需 API key; 若需最新数据先 `hithink-finance data sync`)
  - 盘中实时校准 (--realtime): 主源 mootdx 通达信批量快照(含昨收, 更准)
    -> 备源 腾讯 qt.gtimg.cn 快照(mootdx 取不到时兜底)
    仅覆盖最后一根 bar 的 OHLCV, 让均线/ATR 基于当天盘中最新价重新计算
    mootdx 昨收(last_close)用于按板块规则判涨停(主板10%/创业板科创板20%/ST主板5%)

分池输出:
  - 推荐(可买入): 剔除涨停+亏损后, 按量比降序取前 --top(默认10)
  - 涨停: 不可买入(尾盘无法成交), 单独列出
  - 业绩亏损: 最新季报归母净利润<=0, 暂不可买入, 单独列出
    (hithink-finance financials income, 只对命中信号的股票调用, 不拖慢全市场扫描)

硬过滤规则:
  1. 科创板: exchange=SH 且 thscode 以 688/689 开头  -> 排除
  2. 北交所: exchange=BJ                            -> 排除
  3. ST:     thscode 命中 ST代码黑名单 (ST_BLACKLIST)
             + 名称含 ST/退 (若本地库 name 非空则追加判断)
  4. 停牌:   最新K线日期 < 全市场最新交易日            -> 排除(无最新成交)

V18-ATR 信号 (与 config_v18_atr.yaml + stock_screener.py 一致):
  前置过滤: 非下降趋势 / 收盘>MA55 / MA55五日跌幅<=5%
  买入① 红杏出墙: MA13连2日向上 + 站上MA13 + 多头排列 + 阳线 + 量>5日均量
  买入② 一阳穿三线: 单日阳线穿越三线 + 量能>2倍
  买入③ 揭竿而起: 三线黏合<=1.5% + 5日均黏合<2% + 量能>2倍 + 突破站上三线
  止损:   ATR(14) 吊灯止损 stop = 近N日最高价 - 2.5×ATR(14)

用法:
  python3 screener_v18_atr_full_a.py            # 扫描全A, 输出Top10(按量比)
  python3 screener_v18_atr_full_a.py --top 8    # 输出Top8
  python3 screener_v18_atr_full_a.py --json-out /tmp/x.json
  python3 screener_v18_atr_full_a.py --realtime # 盘中模式: mootdx主/腾讯备 校准最后一根bar
"""
import os
import sys
import json
import math
import time
import argparse
import datetime
import concurrent.futures as cf

import duckdb
import pandas as pd

DB_PATH = os.path.expanduser("~/.local/share/hithink-finance/market.duckdb")

# A股ST/退市的常见代码黑名单 (维护说明见文件底部注释)
# 刷新方法: 配好 API key 后运行 `python3 build_st_blacklist.py`
#   脚本会远程拉全A名称, 筛含 ST/退, 落盘 st_blacklist.json 供本脚本读取
#   本地 DuckDB 的 name 字段为空, 故无法靠名称过滤, 必须依赖此名单
ST_BLACKLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'st_blacklist.json')
SYMBOL_NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'symbol_names.json')
MARKET_CAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'market_cap.json')

# 小盘股阈值 (总市值, 亿元): < 此值视为小盘, 排序加权优先
SMALL_CAP_THRESHOLD = 200.0
# 次新股排除: 上市 < 此天数 直接剔除 (默认 365 天 = 1年)
NEW_STOCK_DAYS = 365
# 并发扫描 worker 数
CONCURRENCY = 16


def load_st_blacklist():
    bl = {}
    if os.path.exists(ST_BLACKLIST_FILE):
        try:
            with open(ST_BLACKLIST_FILE) as f:
                extra = json.load(f)
            if isinstance(extra, list):
                bl.update({c: 'remote' for c in extra})
            elif isinstance(extra, dict):
                bl.update(extra)
        except Exception:
            pass
    return bl


ST_BLACKLIST = load_st_blacklist()


def load_symbol_names():
    if os.path.exists(SYMBOL_NAMES_FILE):
        try:
            with open(SYMBOL_NAMES_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


SYMBOL_NAMES = load_symbol_names()


def load_market_cap():
    """加载实时市值缓存 {thscode: {price, total_cap, float_cap}} (来自 fetch_market_cap.py)"""
    if os.path.exists(MARKET_CAP_FILE):
        try:
            with open(MARKET_CAP_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


MARKET_CAP = load_market_cap()


def fetch_realtime_snapshot(thscodes):
    """从腾讯 qt.gtimg.cn 抓取实时快照, 返回 {thscode: {open, high, low, close, volume}}.
    失败/超时返回空 dict, 不影响离线扫描.
    """
    try:
        import httpx
    except Exception:
        return {}
    qcodes = []
    mapping = {}
    for thscode in thscodes:
        try:
            ticker, exch = thscode.split('.')
        except ValueError:
            continue
        qcode = f"{exch.lower()}{ticker}"
        qcodes.append(qcode)
        mapping[qcode] = thscode
    if not qcodes:
        return {}
    result = {}
    for i in range(0, len(qcodes), 100):
        batch = qcodes[i:i + 100]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            r = httpx.get(url, timeout=10)
            r.encoding = "gbk"
            text = r.text
        except Exception:
            continue
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith("v_"):
                continue
            try:
                eq = line.index('="') + 2
                qcode = line[2:eq - 2]
                payload = line[eq:line.rindex('"')]
                f = payload.split("~")
                if len(f) < 35:
                    continue
                thscode = mapping.get(qcode)
                if not thscode:
                    continue
                close = float(f[3]) if f[3] else 0.0
                last_close = float(f[4]) if f[4] else 0.0
                change_pct = ((close - last_close) / last_close * 100) if last_close > 0 else None
                result[thscode] = {
                    "open": float(f[5]) if f[5] else 0.0,
                    "high": float(f[33]) if f[33] else 0.0,
                    "low": float(f[34]) if f[34] else 0.0,
                    "close": close,
                    "volume": (float(f[6]) if f[6] else 0.0) * 100,  # 手 -> 股
                    "last_close": last_close,
                    "change_pct": change_pct,
                }
            except Exception:
                continue
    return result


def get_listing_date(con, thscode):
    """本地库每只股票最早 K 线日 ≈ 上市日 (库含10年日线)"""
    d = con.execute("SELECT MIN(date) FROM v_daily WHERE thscode=?", [thscode]).fetchone()[0]
    return d  # date 对象或 None

# ATR 参数 (来自 config_v18_atr.yaml)
ATR_PERIOD = 14
ATR_MULT = 2.5


def get_universe(con):
    """返回候选股票池 (已排除科创板/北交所) 及全市场最新交易日"""
    latest = con.execute("SELECT MAX(date) FROM v_daily").fetchone()[0]
    rows = con.execute("""
        SELECT thscode, exchange, name
        FROM v_symbol
        WHERE exchange IN ('SH','SZ','BJ') AND asset_type='a-share'
    """).fetchall()
    uni = []
    for thscode, exch, name in rows:
        # 排除北交所
        if exch == 'BJ':
            continue
        # 排除科创板 (688/689 开头, 仅沪市)
        if exch == 'SH' and (thscode.startswith('688') or thscode.startswith('689')):
            continue
        uni.append((thscode, name))
    return uni, latest


def is_st(thscode, name):
    if thscode in ST_BLACKLIST:
        return True
    if name and ('ST' in name or '退' in name):
        return True
    return False


def is_limit_up_by_code(code, change_pct, name=''):
    """按板块规则判涨停(用实时涨跌幅, 比阈值略松以吸收四舍五入)。
    主板(60/00) 10% -> 9.8; 创业板(30)/科创板(688) 20% -> 19.8; ST主板 5% -> 4.8。
    change_pct 为 None(无昨收) 时返回 False。
    """
    if change_pct is None:
        return False
    if is_st(code, name):
        return change_pct >= 4.8
    if code.startswith(('300', '301', '688', '689')):
        return change_pct >= 19.8
    return change_pct >= 9.8


def is_loss_stock(code):
    """业绩亏损判断: 最新季报归母净利润是否为负 (hithink-finance financials income)。
    取不到数据时保守保留(返回 False, 不误杀)。只对命中的少数几只调用, 不拖慢全市场扫描。
    """
    try:
        import subprocess
        result = subprocess.run(
            ['hithink-finance', 'financials', 'income',
             '--thscode', code, '--period', 'quarterly',
             '--limit', '1', '--format', 'json'],
            capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        items = data.get('data', {}).get('item', [])
        if not items:
            return False
        profit = items[0].get('parent_holder_net_profit')
        if profit is None:
            return False
        return float(profit) <= 0
    except Exception:
        return False


def load_history(con, thscode, bars=120):
    df = con.execute("""
        SELECT date, open, high, low, close, volume, amount
        FROM v_daily
        WHERE thscode = ?
        ORDER BY date DESC
        LIMIT ?
    """, [thscode, bars]).fetchdf()
    if df is None or len(df) < 60:
        return None
    df = df.sort_values('date').reset_index(drop=True)
    return df


def load_all_history(con, days=220):
    """一次性把全市场近 days 天日K读进内存(单连接), 返回 (alldf, latest)。
    之后 scan 阶段零 DuckDB IO, 仅按 thscode 切片。约0.5s。
    """
    latest = con.execute("SELECT MAX(date) FROM v_daily").fetchone()[0]
    cut = latest - datetime.timedelta(days=days)
    alldf = con.execute("""
        SELECT thscode, date, open, high, low, close, volume, amount
        FROM v_daily
        WHERE date >= ?
        ORDER BY thscode, date
    """, [cut]).fetchdf()
    return alldf, latest


def load_history_mem(memdict, thscode, bars=120):
    """从预建分组字典 {thscode: subdf} 取该股票数据(微秒级 O(1))。"""
    sub = memdict.get(thscode)
    if sub is None or len(sub) < 60:
        return None
    sub = sub.sort_values('date').reset_index(drop=True)
    return sub.tail(bars) if len(sub) > bars else sub


def check_signals(df):
    """返回 (信号名|None, 详情dict) - 与 stock_screener.check_signals 逻辑一致"""
    c = df['close']; o = df['open']; v = df['volume']
    ma13 = c.rolling(13).mean(); ma34 = c.rolling(34).mean(); ma55 = c.rolling(55).mean()
    vol_ma = v.rolling(5).mean()

    i = len(df) - 1
    cl, op = c.iloc[i], o.iloc[i]
    m13, m34, m55 = ma13.iloc[i], ma34.iloc[i], ma55.iloc[i]
    m13p = ma13.iloc[i - 1]; m13p2 = ma13.iloc[i - 2]
    vol, vm = v.iloc[i], vol_ma.iloc[i]

    detail = {
        'close': round(float(cl), 2), 'ma13': round(float(m13), 2),
        'ma55': round(float(m55), 2),
        'vol_ratio': round(float(vol / vm), 2) if vm and vm > 0 else 0.0,
    }

    # 前置过滤: 下降趋势
    if (m13 < m34 < m55 and m13 < m13p < m13p2 and
            ma34.iloc[i] < ma34.iloc[i - 1] < ma34.iloc[i - 2] and
            m55 < ma55.iloc[i - 1] < ma55.iloc[i - 2]):
        return None, detail
    if cl < m55:
        return None, detail
    m55_5 = ma55.iloc[i - 5]
    if m55_5 and m55_5 > 0 and (m55_5 - m55) / m55_5 > 0.05:
        return None, detail

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
    if vm and vm > 0:
        spread = (max(m13, m34, m55) - min(m13, m34, m55)) / max(m13, m34, m55)
        avg_spread = 0.0
        for k in range(5):
            a13 = m13 if k == 0 else ma13.iloc[i - k]
            a34 = m34 if k == 0 else ma34.iloc[i - k]
            a55 = m55 if k == 0 else ma55.iloc[i - k]
            ms = max(a13, a34, a55); mn = min(a13, a34, a55)
            avg_spread += (ms - mn) / ms if ms > 0 else 0
        avg_spread /= 5
        if (spread < 0.015 and avg_spread < 0.02 and vol > vm * 2.0 and
                cl > op and cl > m13 and cl > m34 and cl > m55):
            signals.append('揭竿而起')

    if not signals:
        return None, detail
    return '+'.join(signals), detail


def atr_stop_level(df, period=ATR_PERIOD, mult=ATR_MULT):
    h = df['high'].tail(20).max()
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift()).abs()
    tr3 = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.tail(period).mean()
    if atr and atr > 0:
        return round(float(h - mult * atr), 2)
    return None


def score_signal(sig_name):
    """信号强度打分 (用于排序)"""
    pts = 0
    if '红杏出墙' in sig_name:
        pts += 2
    if '一阳穿三线' in sig_name:
        pts += 3
    if '揭竿而起' in sig_name:
        pts += 2
    return pts


def get_listing_map(con):
    """批量获取全市场每只股票最早K线日(≈上市日), 一条SQL返回 {thscode: date}"""
    rows = con.execute(
        "SELECT thscode, MIN(date) FROM v_daily GROUP BY thscode"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _norm_date_obj(v):
    """把 'YYYY-MM-DD' 字符串或 date/datetime 归一化为 datetime.date。"""
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ('%Y-%m-%d', '%Y%m%d'):
            try:
                return datetime.datetime.strptime(v[:10], fmt).date()
            except Exception:
                continue
    return None


def load_listing_dates_smart(con, latest):
    """多源冗余上市日: 优先 prefilter_universe (tushare主源 + akshare兜底 + 7天本地缓存),
    失败/无源/未配置时自动回退本地 DuckDB MIN(date)。

    返回 (map, src):
      map  : {thscode: datetime.date}  统一为 date 对象
      src  : 来源描述字符串(用于日志/审计)
    """
    src, mmap = 'duckdb', None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import prefilter_universe as pf
        raw = pf.load_listing_dates()   # 多源: 7天缓存 > tushare > akshare
        if raw:
            norm = {}
            for k, v in raw.items():
                d = _norm_date_obj(v)
                if d:
                    norm[k] = d
            if norm:
                mmap, src = norm, 'multisource(tushare/akshare+缓存)'
    except Exception as e:
        print(f"  [warn] 多源上市日加载失败: {e}")
    if mmap is None:
        mmap = get_listing_map(con)     # DuckDB MIN(date) 回退
    return mmap, src


def scan_one(args_tuple):
    """单只股票扫描 worker (内存模式: 从 alldf 切片, 零 DuckDB IO).

    返回 dict (命中) 或 None. 已做 ST/次新/停牌 硬过滤.
    支持可选 realtime 覆盖最后一根 bar 的 OHLCV, 用于盘中实时校准.
    """
    code, name, alldf, latest, new_stock_cutoff, small_cap_thr, listing_map, main_fund_map, realtime = args_tuple
    # ST 过滤
    if is_st(code, name):
        return None
    # 上市日 -> 次新股排除
    listing = listing_map.get(code)
    if listing is not None and listing >= new_stock_cutoff:
        return None
    try:
        df = load_history_mem(alldf, code)
    except Exception:
        return None
    if df is None:
        return None
    # 停牌过滤
    if df['date'].iloc[-1].date() < latest:
        return None
    # 实时快照覆盖最后一根 bar (盘中校准) - 仅更新 OHLC, 保留历史成交量用于量比计算
    rt_applied = False
    is_limit_up = False
    change_pct = None
    if realtime and code in realtime:
        rt = realtime[code]
        if rt.get('close') is not None and rt.get('close') > 0:
            df = df.copy()
            idx = df.index[-1]
            for k in ['open', 'high', 'low', 'close']:
                v = rt.get(k)
                if v is not None and isinstance(v, (int, float)):
                    df.loc[idx, k] = v
            rt_applied = True
            change_pct = rt.get('change_pct')
            is_limit_up = is_limit_up_by_code(code, change_pct, name)
    sig, detail = check_signals(df)
    if not sig:
        return None
    stop = atr_stop_level(df)
    entry = detail['close']
    # 市值维度 (腾讯 -> 东财 冗余合并, 见 main)
    capinfo = MARKET_CAP.get(code)
    total_cap = capinfo['total_cap'] if capinfo else None
    is_small = (total_cap is not None and total_cap < small_cap_thr)
    # 主力资金维度 (东财全市场主力净流入映射, 正加负减; None=无数据)
    main_fund = main_fund_map.get(code[:6]) if main_fund_map else None
    return {
        'code': code,
        'name': SYMBOL_NAMES.get(code, name or ''),
        'signal': sig,
        'score': score_signal(sig),
        'close': entry, 'ma13': detail['ma13'], 'ma55': detail['ma55'],
        'vol_ratio': detail['vol_ratio'],
        'atr_stop': stop,
        'stop_pct': round((stop / entry - 1) * 100, 2) if stop else None,
        'date': str(df['date'].iloc[-1]),
        'total_cap': total_cap,
        'is_small_cap': is_small,
        'main_fund': main_fund,
        'realtime': rt_applied,
        'limit_up': is_limit_up,
        'change_pct': round(change_pct, 2) if change_pct is not None else None,
        'loss': is_loss_stock(code),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--json-out', type=str, default=None)
    ap.add_argument('--db', type=str, default=DB_PATH)
    ap.add_argument('--concurrency', type=int, default=CONCURRENCY)
    ap.add_argument('--small-cap-thr', type=float, default=SMALL_CAP_THRESHOLD)
    ap.add_argument('--new-stock-days', type=int, default=NEW_STOCK_DAYS)
    ap.add_argument('--main-fund-top', type=int, default=100,
                    help='东财主力净流入榜TopN作为排序加分(0=关闭)')
    ap.add_argument('--realtime', action='store_true', default=False,
                    help='盘中模式: 用腾讯实时快照校准最后一根bar的OHLCV')
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    universe, latest = get_universe(con)
    # 多源冗余上市日: 优先 tushare/akshare(7天缓存) -> 失败回退本地 DuckDB MIN(date)
    listing_map, listing_src = load_listing_dates_smart(con, latest)
    # 一次性把全市场近220天日K读进内存(单连接, ~0.5s), 之后扫描零 DuckDB IO
    t_load = time.time()
    alldf, _ = load_all_history(con, days=220)
    # 预建 {thscode: subdf} 分组字典(O(1)取数, 避免逐股布尔索引全表扫描)
    memdict = {k: v for k, v in alldf.groupby('thscode', sort=False)}
    con.close()
    load_secs = time.time() - t_load
    print(f"[扫描] 全市场最新交易日: {latest}  候选池(剔除科创/北交): {len(universe)} 只")
    print(f"[上市日源] {listing_src} ({len(listing_map)} 只)")
    print(f"[内存] 全市场日K载入+分组: {len(alldf)} 行 / {len(memdict)} 只, 耗时{load_secs:.1f}s")
    print(f"[过滤] 排除上市<{args.new_stock_days}天次新股; 小盘阈值=总市值<{args.small_cap_thr}亿; 并发={args.concurrency}")

    new_stock_cutoff = latest - datetime.timedelta(days=args.new_stock_days)

    # ---- 实时快照校准 (仅最后一根bar) ----
    # 主源: mootdx 通达信批量快照(含昨收, 更准); 备源: 腾讯 HTTP 快照(mootdx 取不到时兜底)
    realtime_map = {}
    realtime_src = 'none'
    if args.realtime:
        all_codes = [c for c, _ in universe]
        t0 = time.time()
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from mootdx_live import get_live_snapshot
            realtime_map = get_live_snapshot(all_codes)
            if realtime_map:
                realtime_src = 'mootdx'
        except Exception as e:
            print(f"  [warn] mootdx 批量快照失败: {e}")
        if not realtime_map:
            print("[实时] mootdx 无数据, 回退腾讯快照...")
            realtime_map = fetch_realtime_snapshot(all_codes)
            realtime_src = 'tencent' if realtime_map else 'none'
        print(f"[实时] 源={realtime_src} 返回 {len(realtime_map)} 只, 耗时{time.time()-t0:.1f}s")

    # ---- 市值多源冗余: 主源=腾讯(fetch_market_cap已落盘 MARKET_CAP) -> 回退东财批量 ----
    all_codes = [c for c, _ in universe]
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import eastmoney_source as em
        merged = em.load_market_caps_redundant(all_codes, MARKET_CAP)
        # 把合并结果写回全局 MARKET_CAP, scan_one 直接读
        MARKET_CAP.clear()
        MARKET_CAP.update(merged)
        em_cnt = sum(1 for v in merged.values() if v.get('total_cap'))
        print(f"[市值源] 腾讯+东财冗余合并完成: {em_cnt} 只有市值")
    except Exception as e:
        print(f"  [warn] 东财市值冗余失败(仅用腾讯): {e}")

    # ---- 主力资金维度: 东财全市场主力净流入映射 {code: 净流入亿元} (正加负减, 不否决信号) ----
    main_fund_map = {}
    if args.main_fund_top > 0:
        try:
            import eastmoney_source as em
            main_fund_map = em.main_fund_map_full(market='all')
            print(f"[资金流] 东财全市场主力净流入映射: {len(main_fund_map)} 只 (正加负减)")
        except Exception as e:
            print(f"  [warn] 主力资金榜加载失败(跳过加权): {e}")

    tasks = [(code, name, memdict, latest, new_stock_cutoff, args.small_cap_thr,
              listing_map, main_fund_map, realtime_map) for code, name in universe]

    hits = []
    scanned = 0
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(scan_one, t): t for t in tasks}
        for fut in cf.as_completed(futs):
            r = fut.result()
            done += 1
            if r is not None:
                hits.append(r)
            if done % 1000 == 0 or done == len(tasks):
                print(f"  ...已扫描 {done}/{len(tasks)}, 命中 {len(hits)}")

    # ---- 分池: 涨停(不可买) / 亏损(暂不可买) / 可买入 ----
    limit_up_list = [h for h in hits if h.get('limit_up')]
    loss_list = [h for h in hits if (not h.get('limit_up')) and h.get('loss')]
    tradable = [h for h in hits if (not h.get('limit_up')) and (not h.get('loss'))]

    # 推荐池: 可买入股按量比降序(主), 次信号强度, 次小盘优先, 取前 args.top(默认10)
    tradable.sort(key=lambda x: (-x['vol_ratio'], -x['score'], not x['is_small_cap']))
    top = tradable[:args.top]

    print(f"\n{'='*64}")
    small_cnt = sum(1 for h in hits if h['is_small_cap'])
    rt_cnt = sum(1 for h in hits if h.get('realtime'))
    mf_pos = sum(1 for h in hits if (h.get('main_fund') or 0) > 0)
    mf_neg = sum(1 for h in hits if (h.get('main_fund') or 0) < 0)
    print(f"触发 V18-ATR 信号: 共 {len(hits)} 只 (小盘<{args.small_cap_thr}亿 {small_cnt} 只, "
          f"主力净流入+ {mf_pos} / - {mf_neg} 只, 实时校准 {rt_cnt} 只)")
    print(f"涨停 {len(limit_up_list)} | 亏损 {len(loss_list)} | 可买入 {len(tradable)} | 推荐 Top{args.top}(按量比):\n")

    def _capstr(h):
        return f"总市值{h['total_cap']}亿" if h['total_cap'] is not None else "总市值N/A"

    def _tags(h):
        tag = " [小盘]" if h['is_small_cap'] else ""
        mf = h.get('main_fund')
        if mf is not None:
            tag += f" [主力{'+' if mf >= 0 else ''}{mf:.1f}亿]"
        if h.get('realtime'):
            tag += " [实时]"
        return tag

    print("【推荐 / 可买入】(按量比降序)")
    for i, h in enumerate(top, 1):
        print(f"{i}. {h['code']} {h['name']}{_tags(h)} | {h['signal']} | "
              f"收盘{h['close']} 量比{h['vol_ratio']}x | {_capstr(h)} | "
              f"ATR止损{h['atr_stop']} ({h['stop_pct']}%)")

    if limit_up_list:
        print(f"\n【涨停 / 不可买入】({len(limit_up_list)} 只)")
        for i, h in enumerate(limit_up_list[:args.top], 1):
            print(f"{i}. {h['code']} {h['name']} | {h['signal']} | "
                  f"收盘{h['close']} 量比{h['vol_ratio']}x | {_capstr(h)} | 涨停")

    if loss_list:
        print(f"\n【业绩亏损 / 暂不可买入】({len(loss_list)} 只)")
        for i, h in enumerate(loss_list[:args.top], 1):
            print(f"{i}. {h['code']} {h['name']} | {h['signal']} | "
                  f"收盘{h['close']} 量比{h['vol_ratio']}x | {_capstr(h)} | 亏损")

    out = args.json_out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'screener_full_a_today.json')
    with open(out, 'w') as f:
        json.dump({'date': str(latest), 'scanned': len(tasks),
                   'total_hits': len(hits), 'small_cap_hits': small_cnt,
                   'main_fund_pos': mf_pos, 'main_fund_neg': mf_neg,
                   'realtime_hits': rt_cnt, 'realtime_src': realtime_src,
                   'limit_up_count': len(limit_up_list),
                   'loss_count': len(loss_list),
                   'tradable_count': len(tradable), 'top': top,
                   'limit_up': limit_up_list, 'loss': loss_list}, f,
                 ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out}")


if __name__ == '__main__':
    main()
