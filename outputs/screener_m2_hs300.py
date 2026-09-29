#!/usr/bin/env python3
"""
M2 威科夫三大定律选股 (HS300 试点) — 复用 135 盘中日线数据管道

设计: 不重复造数据层。135 的 screener_v18_atr_full_a.py 已把盘中数据整套做好:
  - load_all_history 一次把全市场日线载入内存 (v_daily, ~0.5s)
  - mootdx/腾讯批量实时快照, 仅覆盖最后一根 bar 的 OHLC (保留历史成交量)
本脚本只做两件事:
  1. 取 HS300 池 (本地缓存优先, 无 hithink key 也能跑; 对齐回测口径 剔科创/北交)
  2. 在同一份内存数据上, 对 HS300 池分池跑 M2 信号层 (wyckoff/laws.py):
     入场 = 多头regime(close>MA20且MA20重心向上) AND 第三定律净需求(vol_state=+1)
            AND 近3日无"上方滞涨"(第二定律 effort>1.8x均量且涨幅<0.3%)
     止损 = ATR14 x 2.5 吊灯 (锚定最新收盘), 对应 M2 回测的离场规则

依据 (~/wyckoff-quant/research/m2_fullA_report.md 终版, 含单边10bp成本):
  M2 30seed均值/3年: HS300 +19.0% (>0占比100%, P10>=0) 最优, 深主板+14.2, 全A+5.8,
  创业板+1.2。单票占优最高56%<60%落地线 → 仅 HS300 池小仓位试点, 单笔<=5%。

用法 (必须用带 duckdb/pandas/numpy 的 venv):
  /home/jesse/wyckoff-quant/.venv/bin/python screener_m2_hs300.py [--realtime] [--top N]
"""
import os, sys, json, time, argparse, datetime
import concurrent.futures as cf

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, '/home/jesse/wyckoff-quant')

import pandas as pd  # noqa: E402
import screener_v18_atr_full_a as v18  # 数据管道复用 (load_all_history/load_history_mem/实时快照/ST过滤)
from wyckoff.laws import LawParams, bull_regime, wyckoff_volume_state  # noqa: E402

HS300_CACHE = '/home/jesse/wyckoff-quant/hs300_universe.json'  # 单源缓存(研究侧用key刷新, 生产侧只读)
HS300_MAX_AGE_DAYS = 30
HITHINK = '/home/jesse/.npm-global/bin/hithink-finance'


def get_hs300():
    """HS300 池 (cache-first, 对齐回测口径: 剔 科创688/689 + 北交9/4/8).
    返回 (codes, name_map)。无 hithink key 的 cron 环境靠本地缓存跑通。"""
    import subprocess
    cache, age_days = None, 1e9
    if os.path.exists(HS300_CACHE):
        try:
            c = json.load(open(HS300_CACHE))
            fetched = datetime.datetime.fromisoformat(c['fetched_at'])
            ref = datetime.datetime.now().astimezone() if fetched.tzinfo else datetime.datetime.now()
            cache, age_days = c, (ref - fetched).days
        except Exception:
            pass
    if cache and age_days < HS300_MAX_AGE_DAYS:
        m = cache.get('members', {})
        codes = [c for c in m if c.startswith(('6', '0')) and not c.startswith(('688', '689', '9', '4', '8'))]
        print(f"[HS300] 本地缓存({age_days}天前, {len(codes)}只, 已剔科创), 跳过 hithink (免API key)")
        return codes, {c: m.get(c, '') for c in codes}

    # 缓存缺失/过期: 试 hithink 刷新 (cron 无 key 会失败, 失败则沿用旧缓存)
    try:
        r = subprocess.run([HITHINK, 'index', 'constituents', '--thscode', '000300.SH', '--format', 'json'],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            items = (json.loads(r.stdout).get('data') or {}).get('item') or []
            d = {i['thscode']: i.get('name', '') for i in items if i.get('thscode')}
            codes = [c for c in d if c.startswith(('6', '0')) and not c.startswith(('688', '689', '9', '4', '8'))]
            try:
                json.dump({'fetched_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                           'index': '000300.SH', 'members': {c: d[c] for c in codes}},
                          open(HS300_CACHE, 'w'), ensure_ascii=False, indent=1)
                print(f"[HS300] hithink 刷新缓存 {len(codes)} 只")
            except Exception as e:
                print(f"[HS300] 刷新成功但写缓存失败(不影响本次): {e}")
            return codes, {c: d.get(c, '') for c in codes}
        print(f"[HS300] hithink 刷新失败({r.stderr[:120]}), 沿用旧缓存")
    except Exception as e:
        print(f"[HS300] hithink 不可用({str(e)[:80]}), 沿用旧缓存")
    if cache:
        m = cache.get('members', {})
        codes = [c for c in m if c.startswith(('6', '0')) and not c.startswith(('688', '689', '9', '4', '8'))]
        print(f"[HS300] 沿用 {age_days:.0f} 天前缓存 ({len(codes)} 只)")
        return codes, {c: m.get(c, '') for c in codes}
    raise RuntimeError('HS300 池既无本地缓存也无 hithink key, 无法选股 — 请先在有 key 的环境生成 '
                       f'{HS300_CACHE} (hithink-finance index constituents 000300.SH)')


def m2_check(df, lp):
    """最新一根 bar 的 M2 入场判定 + ATR 吊灯止损。df = 135 管道内存日线 (最后一根可已被实时覆盖)。
    返回 dict(命中) 或 None。"""
    close, vol = df['close'], df['volume']
    bull, _ = bull_regime(df, lp)
    vs = wyckoff_volume_state(df, lp)
    i = len(df) - 1
    bull_today = bool(bull.iloc[i])
    demand_today = int(vs['vol_state'].iloc[i]) == 1
    stalled = bool(vs['upstall_any'].iloc[i])
    if not (bull_today and demand_today and not stalled):
        return None
    trv = pd.concat([df['high'] - df['low'],
                     (df['high'] - close.shift()).abs(),
                     (df['low'] - close.shift()).abs()], axis=1).max(axis=1)
    atr = trv.rolling(lp.ATR_PERIOD, min_periods=7).mean()
    last_close = float(close.iloc[i])
    atrv = float(atr.iloc[i]) if atr.iloc[i] == atr.iloc[i] else 0.0
    stop = last_close - lp.ATR_MULT * atrv
    return {'demand_ratio': round(float(vs['demand_ratio'].iloc[i]), 3),
            'close': round(last_close, 2),
            'atr_stop': round(stop, 2),
            'stop_pct': round((stop - last_close) / last_close * 100, 1) if last_close else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--realtime', action='store_true',
                    help='盘中模式: mootdx主/腾讯备 批量快照覆盖最后一根bar的OHLC (与135 V18同管道同口径)')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--concurrency', type=int, default=16)
    ap.add_argument('--json-out', default=None)
    args = ap.parse_args()

    lp = LawParams()
    import duckdb
    con = duckdb.connect(v18.DB_PATH, read_only=True)
    alldf, latest = v18.load_all_history(con, days=220)
    memdict = {k: v for k, v in alldf.groupby('thscode', sort=False)}
    con.close()

    today_s = datetime.date.today().strftime('%Y-%m-%d')
    print(f"[数据] DuckDB最新交易日 {str(latest)[:10]} | 内存 {len(alldf)} 行 / {len(memdict)} 只 (与V18同源同口径)")
    if str(latest)[:10] < today_s:
        print(f"[数据][warn] 本地数据滞后 (最新 {str(latest)[:10]} != 今天 {today_s}): "
              f"信号基于 {str(latest)[:10]} 骨架(+实时报价覆盖最后一根bar), 建议先跑数据同步 (hithink-finance data sync)")

    codes, name_map = get_hs300()

    rt_map, rt_src = {}, 'none'
    if args.realtime:
        t0 = time.time()
        try:
            from mootdx_live import get_live_snapshot
            rt_map = get_live_snapshot(codes) or {}
            rt_src = 'mootdx' if rt_map else 'none'
        except Exception as e:
            print(f"  [warn] mootdx 批量快照失败: {e}")
        if not rt_map:
            rt_map = v18.fetch_realtime_snapshot(codes)
            rt_src = 'tencent' if rt_map else 'none'
        print(f"[实时] 源={rt_src} 覆盖 {len(rt_map)}/{len(codes)} 只, 耗时{time.time()-t0:.1f}s")

    def worker(code):
        name = name_map.get(code, '')
        if v18.is_st(code, name):
            return None
        df = v18.load_history_mem(memdict, code)
        if df is None:
            return None
        # 停牌过滤 (与 135 scan_one 一致: 最后一根bar日期 < 全市场最新交易日 = 当日无交易)
        if pd.Timestamp(df['date'].iloc[-1]).date() < latest:
            return None
        if code in rt_map:
            rt = rt_map[code]
            if rt.get('close') is not None and rt.get('close') > 0:
                df = df.copy()
                for k in ('open', 'high', 'low', 'close'):
                    v = rt.get(k)
                    if isinstance(v, (int, float)):
                        df.loc[len(df) - 1, k] = v
        r = m2_check(df, lp)
        if r is None:
            return None
        r['code'], r['name'] = code, name
        return r

    hits = []
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for r in ex.map(worker, codes):
            if r is not None:
                hits.append(r)

    hits.sort(key=lambda x: -x['demand_ratio'])
    top = hits[:args.top]

    print(f"\n{'='*64}")
    print(f"M2威科夫(净需求入场+滞涨离场, 不用Spring) | HS300试点 | 扫描 {len(codes)} 只")
    print(f"触发入场信号: {len(hits)} 只 (多头regime AND 第三定律净需求 AND 近3日无滞涨)")
    print(f"\n【M2 HS300 试点推荐】(按需求强度降序) 单笔建议≤5%仓 · ATR吊灯{lp.ATR_MULT}x止损锁利润 · 不主动止盈\n")
    for i, h in enumerate(top, 1):
        print(f"{i}. {h['code']} {h['name']} | 需求比{h['demand_ratio']} | "
              f"收盘{h['close']} | ATR止损{h['atr_stop']} ({h['stop_pct']}%)")
    if not top:
        print('(今日无 M2 入场信号 → 按杰西"没有交易机会就空仓"原则, 当日 M2 不新增)')

    out = args.json_out or os.path.join(_HERE, 'screener_m2_today.json')
    with open(out, 'w') as f:
        json.dump({'date': str(latest)[:10], 'pool': 'HS300(剔科创/北交)', 'n_pool': len(codes),
                   'n_hits': len(hits), 'realtime_src': rt_src, 'top': top, 'params': {
                       'demand_th': lp.DEMAND_TH, 'supply_th': lp.SUPPLY_TH,
                       'effort_vol': lp.EFFORT_VOL, 'result_eps': lp.RESULT_EPS,
                       'atr_mult': lp.ATR_MULT}}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out}")


if __name__ == '__main__':
    main()
