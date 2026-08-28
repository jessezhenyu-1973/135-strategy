#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
135战法 V18-ATR — 全A股代码->名称 缓存构建器

本地 DuckDB 的 v_symbol.name 为空, 远程 symbol list 能拉到真实名称。
本脚本拉取全A股(SH/SZ/BJ)名称, 落盘 symbol_names.json 供扫描器/卡片补全名称。

前置: 已配置 hithink-finance API key (hithink-finance auth login)
用法: python3 build_symbol_names.py
"""
import os
import sys
import json
import subprocess

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'symbol_names.json')


def main():
    names = {}
    for exch in ['SH', 'SZ', 'BJ']:
        try:
            r = subprocess.run(
                ['hithink-finance', 'symbol', 'list',
                 '--exchange', exch, '--asset-type', 'a-share',
                 '--limit', '10000', '--format', 'json'],
                capture_output=True, text=True, timeout=180)
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
            code = it.get('thscode')
            name = it.get('name')
            if code and name:
                names[code] = name
    with open(OUT, 'w') as f:
        json.dump(names, f, ensure_ascii=False, indent=2)
    print(f"已写入 {len(names)} 只代码名称 -> {OUT}")


if __name__ == '__main__':
    main()
