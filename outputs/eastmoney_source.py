#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富数据源层 (基于 mcp-eastmoney 项目底层公开接口, 免 API Key, 延时约15分钟)

数据源: push2delay.eastmoney.com / push2his.eastmoney.com (东财公开延时行情)
用途: 作为「市值」维度的冗余源(主源=腾讯行情), 以及「主力资金/板块资金流」增强维度。

注意: 本文件不启动 MCP server, 直接复用其底层 HTTP 接口, 便于批量/同步调用。
接口与字段定义取自 https://github.com/27dream/mcp-eastmoney (MIT)。

安全/稳定性约定:
  - 免 Key, 但请控制请求频率(东财公开接口)
  - 所有函数异常均返回空/降级结果, 绝不抛出中断主流程
"""
import sys
import json
import time
import datetime
import concurrent.futures as cf

try:
    import httpx
except ImportError:
    httpx = None

QUOTE_HOST = "https://push2delay.eastmoney.com"
KLINE_HOST = "https://push2his.eastmoney.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _get(url, timeout=15, retries=3):
    """同步 GET, 返回 dict; 失败返回 None。"""
    if httpx is None:
        return None
    for _ in range(retries):
        try:
            with httpx.Client(timeout=timeout, headers=HEADERS) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.json()
        except Exception:
            time.sleep(1.0)
    return None


def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if f != f else f  # NaN -> default
    except (TypeError, ValueError):
        return default


def market_prefix(code):
    """6位代码 -> 东财 secid 前缀 (1=沪, 0=深)。"""
    code = str(code).strip()
    if code.startswith(("60", "68", "11", "13", "5")):
        return "1"
    return "0"


def load_market_caps_em(thscodes):
    """批量总市值(亿元) + 流通市值(亿元)。

    thscodes: list of '600000.SH' / '000001.SZ'
    返回 {thscode: {'total_cap': float亿元, 'float_cap': float亿元}}
    底层: /api/qt/clist/get fs=全市场, fields f20=总市值(元) f21=流通市值(元)
    """
    if not thscodes:
        return {}
    fs = "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:8"  # 沪深京全市场
    pz = min(len(thscodes) * 3 + 50, 6000)
    url = (f"{QUOTE_HOST}/api/qt/clist/get?pn=1&pz={pz}&po=1&np=1&fltt=2&invt=2"
           f"&fid=f20&fs={fs}&fields=f12,f13,f20,f21")
    d = _get(url)
    caps = {}
    if not d:
        return caps
    diff = (d.get("data") or {}).get("diff") or []
    emap = {}
    for r in diff:
        code = str(r.get("f12", "")).strip()
        mkt = str(r.get("f13", "")).strip()  # 1=沪 0=深
        if not code:
            continue
        emap[code] = r  # 先按6位代码存
    # 建立 6位代码 -> thscode 映射
    for ts in thscodes:
        short = ts[:6]
        r = emap.get(short)
        if not r:
            continue
        total = _safe(r.get("f20")) / 1e8   # 元 -> 亿元
        fl = _safe(r.get("f21")) / 1e8
        caps[ts] = {"total_cap": round(total, 2) if total else 0.0,
                    "float_cap": round(fl, 2) if fl else 0.0}
    return caps


def main_fund_rank(limit=50, market="all", full=False):
    """主力资金净流入排行。返回 list[{code, name, main_net_inflow(亿元), main_net_pct}]。

    market: all/sh/sz/cyb/kcb
    full:  True 时拉全市场(分页合并, 用于连续加权, 不受 limit 限制)
    底层: /api/qt/clist/get fid=f62(主力净流入) po=1降序
    """
    fs_map = {
        "all": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:8",
        "sh": "m:0+t:6,m:0+t:13,m:0+t:80",
        "sz": "m:1+t:2,m:1+t:23,m:1+t:8",
        "cyb": "m:0+t:80",
        "kcb": "m:1+t:23",
    }
    fs = fs_map.get(market, fs_map["all"])
    out = []
    if full:
        # 分页拉全市场 (东财单次上限约5000, 全A约5500只, 拆2页)
        for pn in (1, 2):
            url = (f"{QUOTE_HOST}/api/qt/clist/get?pn={pn}&pz=5000&po=1&np=1&fltt=2&invt=2"
                   f"&fid=f62&fs={fs}&fields=f12,f14,f62,f184")
            d = _get(url)
            if not d:
                break
            diff = (d.get("data") or {}).get("diff") or []
            if not diff:
                break
            for r in diff:
                code = str(r.get("f12", "")).strip()
                if not code:
                    continue
                net = _safe(r.get("f62")) / 1e8
                out.append({"code": code, "name": r.get("f14", ""),
                            "main_net_inflow": round(net, 2),
                            "main_net_pct": round(_safe(r.get("f184")), 2)})
            total = (d.get("data") or {}).get("total", 0)
            if total and len(out) >= total:
                break
        return out
    url = (f"{QUOTE_HOST}/api/qt/clist/get?pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2"
           f"&fid=f62&fs={fs}&fields=f12,f14,f62,f184")
    d = _get(url)
    if not d:
        return out
    diff = (d.get("data") or {}).get("diff") or []
    for r in diff:
        code = str(r.get("f12", "")).strip()
        name = r.get("f14", "")
        net = _safe(r.get("f62")) / 1e8  # 元 -> 亿元
        pct = _safe(r.get("f184"))
        out.append({"code": code, "name": name,
                    "main_net_inflow": round(net, 2),
                    "main_net_pct": round(pct, 2)})
    return out


def main_fund_map_full(market="all"):
    """全市场主力净流入映射 {6位code: 净流入亿元(可正可负)}。用于连续加权(正加负减)。"""
    try:
        rows = main_fund_rank(full=True, market=market)
        return {r["code"]: r["main_net_inflow"] for r in rows if r.get("code")}
    except Exception:
        return {}


def sector_fund_flow(kind="industry", limit=20):
    """板块资金流排行。kind: industry/concept。返回 list[{code,name,change_pct,main_net_inflow(亿元),leading_stock,leading_change_pct}]。"""
    fs = "m:90+t:2" if kind == "industry" else "m:90+t:3"
    url = (f"{QUOTE_HOST}/api/qt/clist/get?pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2"
           f"&fid=f62&fs={fs}&fields=f12,f14,f3,f62,f184,f128,f136")
    d = _get(url)
    out = []
    if not d:
        return out
    diff = (d.get("data") or {}).get("diff") or []
    for r in diff:
        out.append({
            "code": str(r.get("f12", "")).strip(),
            "name": r.get("f14", ""),
            "change_pct": _safe(r.get("f3")),
            "main_net_inflow": round(_safe(r.get("f62")) / 1e8, 2),
            "leading_stock": r.get("f128") or "-",
            "leading_change_pct": _safe(r.get("f136")),
        })
    return out


def load_market_caps_redundant(thscodes, caps_tencent=None):
    """市值多源冗余: 主源=腾讯(传入 caps_tencent), 缺失项回退东财批量。

    caps_tencent: {thscode: {price,total_cap,float_cap}} (来自 fetch_market_cap.py)
    返回合并后的 {thscode: {price, total_cap, float_cap}}
    """
    merged = {}
    if caps_tencent:
        merged.update(caps_tencent)
    missing = [c for c in thscodes if c not in merged or not merged[c].get("total_cap")]
    if not missing:
        return merged
    em = load_market_caps_em(missing)
    for c in missing:
        if c in em:
            merged.setdefault(c, {})["total_cap"] = em[c]["total_cap"]
            merged.setdefault(c, {})["float_cap"] = em[c]["float_cap"]
    return merged


if __name__ == "__main__":
    # 自测: 取几只市值 + 主力资金榜
    test = ["600000.SH", "000001.SZ", "300750.SZ"]
    print("东财批量市值:", load_market_caps_redundant(test))
    print("主力资金Top5:", main_fund_rank(5))
    print("行业板块Top5:", sector_fund_flow("industry", 5))
