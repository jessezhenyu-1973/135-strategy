#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
135战法 V18-ATR — 全A股实时市值抓取器 (腾讯行情接口, 16并发)

数据源: 腾讯财经 qt.gtimg.cn 实时行情 (无需 API key, 免费)
  字段解析: 逗号分隔, 段[44]=总市值(亿元), 段[45]=流通市值(亿元), 段[3]=现价
  例: v_sz000021="51~深科技~000021~38.19~...~605.15~605.24~..."
       -> 总市值 605.15亿, 流通市值 605.24亿

用法:
  python3 fetch_market_cap.py                 # 抓取全A -> market_cap.json
  python3 fetch_market_cap.py --limit 50     # 仅前50只(调试)
  python3 fetch_market_cap.py --out /tmp/mc.json

输出 JSON: { "000021.SZ": {"price":38.19,"total_cap":605.15,"float_cap":605.24}, ... }
"""

import os
import sys
import json
import argparse
import subprocess
import concurrent.futures as cf

# 从本地 DuckDB 取全A代码表 (同扫描器口径: 剔除科创/北交由扫描器负责, 这里抓全量再由扫描器过滤)
DB_PATH = os.path.expanduser("~/.local/share/hithink-finance/market.duckdb")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'market_cap.json')

# 并发度
CONCURRENCY = 16
# 每批代码数 (URL 长度限制, 腾讯建议 <= 120)
BATCH = 100
# 单批超时(秒)
TIMEOUT_S = 20


def get_all_codes():
    """从本地 DuckDB 取全A代码 (SH/SZ/BJ a-share), 返回 [(thscode, ticker, exchange)]"""
    import duckdb
    con = duckdb.connect(DB_PATH, read_only=True)
    rows = con.execute("""
        SELECT thscode, ticker, exchange
        FROM v_symbol
        WHERE exchange IN ('SH','SZ','BJ') AND asset_type='a-share'
    """).fetchall()
    con.close()
    return rows


def _ticker_to_qcode(thscode, exchange):
    """thscode '000021.SZ' -> 腾讯 qcode 'sz000021'"""
    t = thscode.split('.')[0]
    pre = 'sh' if exchange == 'SH' else ('sz' if exchange == 'SZ' else 'bj')
    return f"{pre}{t}"


def fetch_batch(qcodes):
    """抓取一批 (最多 BATCH 只) 实时行情, 返回 {thscode: {...}}"""
    if not qcodes:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(qcodes)
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", str(TIMEOUT_S), url],
            capture_output=True, timeout=TIMEOUT_S + 5
        )
        out = proc.stdout.decode("gbk", errors="replace")
    except Exception:
        return {}
    res = {}
    for line in out.split("\n"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        try:
            # v_sz000021="..."
            eq = line.index('="') + 2
            code = line[2:eq-2]          # sz000021
            payload = line[eq:line.rindex('"')]
            f = payload.split("~")
            if len(f) < 46:
                continue
            price = float(f[3]) if f[3] else 0.0
            total_cap = float(f[44]) if f[44] else 0.0   # 亿元
            float_cap = float(f[45]) if f[45] else 0.0   # 亿元
            # 还原 thscode
            exch = code[:2].upper()
            ticker = code[2:]
            thscode = f"{ticker}.{exch}"
            res[thscode] = {
                "price": round(price, 2),
                "total_cap": round(total_cap, 2),
                "float_cap": round(float_cap, 2),
            }
        except Exception:
            continue
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=str, default=OUT)
    ap.add_argument('--limit', type=int, default=0, help='调试用, 限制抓取前N只')
    ap.add_argument('--db', type=str, default=DB_PATH)
    args = ap.parse_args()

    rows = get_all_codes()
    if args.limit:
        rows = rows[:args.limit]
    print(f"[市值] 待抓取代码: {len(rows)} 只, 并发 {CONCURRENCY}, 批大小 {BATCH}")

    # 组装 qcode 批次
    batches = []
    cur = []
    for thscode, ticker, exch in rows:
        cur.append(_ticker_to_qcode(thscode, exch))
        if len(cur) >= BATCH:
            batches.append(cur); cur = []
    if cur:
        batches.append(cur)

    cap_map = {}
    done = 0
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(fetch_batch, b): i for i, b in enumerate(batches)}
        for fut in cf.as_completed(futs):
            try:
                part = fut.result()
                cap_map.update(part)
            except Exception:
                pass
            done += 1
            if done % 10 == 0 or done == len(batches):
                print(f"  ...批次 {done}/{len(batches)}, 已得市值 {len(cap_map)} 只")

    with open(args.out, 'w') as f:
        json.dump(cap_map, f, ensure_ascii=False, indent=2)
    print(f"[市值] 完成: 成功 {len(cap_map)}/{len(rows)} 只 -> {args.out}")


if __name__ == '__main__':
    main()
