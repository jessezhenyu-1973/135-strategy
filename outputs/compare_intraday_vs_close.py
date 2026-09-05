#!/usr/bin/env python3
"""135战法 收盘回测 vs 盘中选股 对比脚本

用途: 收盘数据同步后运行, 验证盘中(14:30)推荐池的信号在收盘数据上是否真实触发,
并找出收盘新增的买入信号。

对比口径:
- 盘中推荐 = screener_full_a_today.json 的 top 池 (14:30 实时价扫描)
- 收盘重扫 = 同一套 V18-ATR 信号逻辑 (复用 screener_v18_atr_full_a.check_signals),
  跑在全市场最新收盘 bar 上
- 确认 = 盘中推荐的代码在收盘重扫中仍有信号
- 消失 = 盘中推荐但收盘重扫无信号 (盘中未定型/尾盘回落)
- 新增 = 收盘有信号但不在盘中推荐池

用法:
  python3 compare_intraday_vs_close.py            # 输出报告文本 (供 cron 投递)
  python3 compare_intraday_vs_close.py --json     # 输出 JSON 明细
"""
import os
import sys
import json
import argparse
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import screener_v18_atr_full_a as S  # noqa: E402

PICKS_FILE = os.path.join(BASE, 'screener_full_a_today.json')
NEW_SIGNAL_TOP_N = 15  # 新增信号最多列出的数量(按量比降序)


def load_picks():
    if not os.path.exists(PICKS_FILE):
        return None
    try:
        with open(PICKS_FILE) as f:
            d = json.load(f)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true', help='输出JSON明细')
    args = ap.parse_args()

    # 1. 盘中推荐
    picks = load_picks()
    if picks is None or not picks.get('top'):
        print("⚠️ 无盘中推荐数据 (screener_full_a_today.json 缺失或为空), 跳过对比。")
        return
    picks_date = str(picks.get('date', ''))[:10]
    top = picks['top']
    pick_by_code = {t['code']: t for t in top}
    limit_up = {t['code'] for t in picks.get('limit_up', [])}
    loss = {t['code'] for t in picks.get('loss', [])}

    # 2. 收盘全市场重扫 (与盘中扫描同一口径: 同信号逻辑 + 同硬过滤)
    con = S.duckdb.connect(S.DB_PATH, read_only=True)
    universe, latest = S.get_universe(con)          # 已排除北交所/科创板688/689
    latest_s = str(latest)[:10]
    listing_map, _ = S.load_listing_dates_smart(con, latest)
    alldf, _ = S.load_all_history(con, days=220)
    con.close()

    # 数据新鲜度守门: 库最新交易日必须不早于盘中推荐日期
    if latest_s < picks_date:
        print(f"⚠️ 本地库最新交易日 {latest_s} 早于盘中推荐日期 {picks_date}, "
              f"收盘数据可能未同步, 本次对比无效。请先运行 hithink-finance data sync。")
        return

    new_stock_cutoff = latest - datetime.timedelta(days=S.NEW_STOCK_DAYS)
    memdict = {code: g for code, g in alldf.groupby('thscode', sort=False)}
    hits = []
    for code, name in universe:
        if S.is_st(code, name):
            continue  # ST/退市
        listing = listing_map.get(code)
        if listing is not None and listing >= new_stock_cutoff:
            continue  # 次新股 (<365天)
        sub = memdict.get(code)
        if sub is None or len(sub) < 60:
            continue
        sub = sub.sort_values('date').reset_index(drop=True)
        if str(sub['date'].iloc[-1])[:10] != latest_s:
            continue  # 停牌/无最新成交
        sig, detail = S.check_signals(sub)
        if sig:
            hits.append({
                'code': code,
                'name': S.SYMBOL_NAMES.get(code, name or ''),
                'signal': sig,
                'close': detail.get('close'),
                'vol_ratio': detail.get('vol_ratio'),
                'atr_stop': S.atr_stop_level(sub),
            })
    hits.sort(key=lambda h: (h.get('vol_ratio') or 0), reverse=True)
    hit_by_code = {h['code']: h for h in hits}

    # 3. 对比
    confirmed, lost = [], []
    for code, p in pick_by_code.items():
        h = hit_by_code.get(code)
        if h:
            confirmed.append({**p, 'close_rescan': h['close'],
                              'vol_ratio_rescan': h['vol_ratio'],
                              'atr_stop_rescan': h['atr_stop'],
                              'signal_rescan': h['signal']})
        else:
            lost.append(p)
    new_signals = [h for h in hits if h['code'] not in pick_by_code][:NEW_SIGNAL_TOP_N]

    # 4. 输出
    if args.json:
        print(json.dumps({
            'picks_date': picks_date, 'close_date': latest_s,
            'picks_count': len(top), 'confirmed': confirmed,
            'lost': lost, 'new_signals': new_signals,
            'total_hits': len(hits),
        }, ensure_ascii=False, indent=1))
        return

    n = len(top)
    print(f"📊 135战法 收盘回测 vs 盘中选股 | {latest_s}")
    print(f"盘中推荐 {n} 只 → 收盘确认 {len(confirmed)} | 信号消失 {len(lost)} | "
          f"收盘新增信号 {len(new_signals)}{'+' if len([h for h in hits if h['code'] not in pick_by_code]) > NEW_SIGNAL_TOP_N else ''}")
    print()

    print(f"✅ 确认信号 {len(confirmed)} 只 (盘中推荐, 收盘数据真实触发):")
    if confirmed:
        for i, c in enumerate(confirmed, 1):
            extra = []
            if c['code'] in limit_up:
                extra.append('盘中涨停')
            if c['code'] in loss:
                extra.append('亏损')
            tag = f" [{', '.join(extra)}]" if extra else ""
            print(f"  {i}. {c['code']} {c.get('name','')} {c['signal']} "
                  f"收盘{c.get('close_rescan')} 量比{c.get('vol_ratio_rescan')} "
                  f"ATR止损{c.get('atr_stop_rescan')}{tag}")
    else:
        print("  (无)")
    print()

    print(f"❌ 信号消失 {len(lost)} 只 (盘中推荐, 收盘未触发):")
    if lost:
        for p in lost:
            print(f"  {p['code']} {p.get('name','')} 盘中信号:{p['signal']} 盘中价:{p.get('close')}")
    else:
        print("  (无)")
    print()

    print(f"🆕 收盘新增信号 (Top{len(new_signals)}, 按量比):")
    if new_signals:
        for i, h in enumerate(new_signals, 1):
            print(f"  {i}. {h['code']} {h['name']} {h['signal']} "
                  f"收盘{h['close']} 量比{h['vol_ratio']} ATR止损{h['atr_stop']}")
    else:
        print("  (无)")
    print()
    print(f"(全市场收盘信号共 {len(hits)} 只; 数据日期 {latest_s}; "
          f"口径: 与盘中扫描同一 V18-ATR 信号逻辑, 收盘bar重算)")


if __name__ == '__main__':
    main()
