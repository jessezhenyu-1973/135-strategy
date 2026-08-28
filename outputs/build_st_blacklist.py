#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
135战法 V18-ATR — ST/退市 代码黑名单刷新器

原理: hithink-finance 本地 DuckDB 的 v_symbol.name 为空, 无法靠名称过滤 ST。
       本脚本在配好 API key 后, 远程拉取全A股名称, 筛出含 'ST' / '退' 的代码,
       落盘 st_blacklist.json, 供 screener_v18_atr_full_a.py 读取。

前置: hithink-finance auth login --api-key-stdin   (或设 HITHINK_FINANCE_API_KEY)
用法: python3 build_st_blacklist.py
"""
import os
import sys
import json
import subprocess

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'st_blacklist.json')


def main():
    codes = []
    for exch in ['SH', 'SZ', 'BJ']:
        try:
            r = subprocess.run(
                ['hithink-finance', 'symbol', 'list',
                 '--exchange', exch, '--asset-type', 'a-share',
                 '--limit', '10000', '--format', 'json'],
                capture_output=True, text=True, timeout=120)
        except Exception as e:
            print(f"[{exch}] 调用失败: {e}")
            continue
        if r.returncode != 0:
            print(f"[{exch}] 失败: {r.stderr.strip()[:200]}")
            continue
        try:
            data = json.loads(r.stdout)
        except Exception:
            print(f"[{exch}] JSON解析失败")
            continue
        items = data.get('data', {}).get('item', [])
        for it in items:
            name = it.get('name') or ''
            code = it.get('thscode') or ''
            if not code:
                continue
            if 'ST' in name or '退' in name:
                codes.append(code)
    codes = sorted(set(codes))
    with open(OUT, 'w') as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)
    print(f"已写入 {len(codes)} 只 ST/退市 代码 -> {OUT}")


if __name__ == '__main__':
    main()
