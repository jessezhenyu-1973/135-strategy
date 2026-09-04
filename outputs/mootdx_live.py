#!/usr/bin/env python3
"""
mootdx 实时价源 — 135战法选股流程的「今日实时 bar」提供者

主源: 通达信 mootdx `quotes` 实时快照 (TCP 7709, 免 key, 不封 IP,
      含五档盘口, 现价/开高低/量, 比腾讯 HTTP 快照更准、更低延迟)
备源: 腾讯 qt.gtimg.cn (HTTP, mootdx 取不到时兜底, 见 run_param_sensitivity._tencent_live_bar)

设计要点
--------
- 进程内单例 client: 创建加锁(一次性), 8 线程并发 quotes 实测无错,
  仅 1 条 TCP 连接, 比每线程各建连接更省。
- 服务器自适应: 不同网络(本机/远端NAS)能连通的通达信服务器不同, mootdx 默认
  bestip 探测可能选到不通的。三级策略: ①读缓存的可用服务器 → ②默认 factory →
  ③逐个探测 config 里的候选服务器, 取第一个能拉到代表股日K的, 并写缓存。
  缓存文件: ~/.mootdx_live_server.json。
- 快照日期守卫: mootdx `quotes` 的 servertime 只有 HH:MM:SS 无日期,
  用代表股(000001)最后一根日K的日期判定「今日是否已出行情」。
  非交易日/未开市 → 返回 None, 调用方自动回退历史序列(保持原行为)。
- 今日 bar 单位: mootdx vol 单位是「手」, ×100 → 股, 与 hithink 历史序列对齐。
- 字段映射(quotes 单行): price=现价(收), open/high/low 直接, vol=量(手)。

用法
----
    from mootdx_live import get_live_bar
    bar = get_live_bar('600519.SH')   # -> 1 行 DataFrame(open/high/low/close/volume,股)
    # 索引为今日 16:00; 今日无实时行情时返回 None
"""
import datetime
import json
import os
import socket
import threading

import pandas as pd

_client = None
_client_lock = threading.Lock()
_snapshot_date = None
_snapshot_date_lock = threading.Lock()

try:
    from mootdx.quotes import Quotes
    _MOOTDX_OK = True
except Exception:  # mootdx 未安装/导入失败 → 整个模块降级为「取不到」, 由调用方走腾讯兜底
    Quotes = None
    _MOOTDX_OK = False

# 代表股: 用于判定「今日快照日期」+ 探测服务器连通性。选 000001(平安银行), 高流动性、几乎不停牌。
_REPRESENTATIVE = '000001'
# 可用服务器缓存(跨进程复用, 避免每次重探)
_SERVER_CACHE = os.path.expanduser('~/.mootdx_live_server.json')
# 额外已知可用服务器(不在 mootdx 默认 config 候选里, 但实测能返回数据)。
# 不同网络出口 IP 下, config 里能 TCP 通的服务器业务层可能全返回 EMPTY(通达信对部分
# 出口 IP 只建连不给数据), 而这些额外服务器反而可用。探测池 = config 候选 + 本列表。
_EXTRA_SERVERS = [
    ('115.238.56.198', 7709),
]


def _candidate_servers():
    """探测池 = _EXTRA_SERVERS(已知可用, 优先) + mootdx 配置文件里的候选 HQ 服务器(去重)。
    额外服务器放最前, 让已知可用的网络环境秒中, 不必扫完整 config。
    """
    out = list(_EXTRA_SERVERS)
    try:
        cfg = os.path.expanduser('~/.mootdx/config.json')
        if os.path.exists(cfg):
            with open(cfg) as f:
                d = json.load(f)
            hq = d.get('SERVER', {}).get('HQ', [])
            for s in hq:
                if isinstance(s, (list, tuple)) and len(s) >= 3:
                    srv = (s[1], int(s[2]))
                    if srv not in out:
                        out.append(srv)
    except Exception:
        pass
    return out


def _load_cached_server():
    """读缓存的可用服务器 (ip, port) 或 None。"""
    try:
        if os.path.exists(_SERVER_CACHE):
            with open(_SERVER_CACHE) as f:
                d = json.load(f)
            ip, port = d.get('ip'), d.get('port')
            if ip:
                return (ip, int(port))
    except Exception:
        pass
    return None


def _save_cached_server(server):
    """把可用服务器写缓存(跨进程复用)。"""
    try:
        with open(_SERVER_CACHE, 'w') as f:
            json.dump({'ip': server[0], 'port': int(server[1])}, f)
    except Exception:
        pass


def _tcp_open(ip, port, timeout=2.0):
    """快速 TCP 连通性预筛(短超时), 避免逐个探测不通服务器时卡死。"""
    try:
        s = socket.create_connection((ip, int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _make_client(server=None):
    """建 client。server=None 走默认 factory; 否则指定 (ip, port)。"""
    try:
        if server is None:
            return Quotes.factory(market='std', quiet=True)
        return Quotes.factory(market='std', quiet=True,
                              server=tuple(server), bestip=False)
    except Exception:
        return None


def _client_works(client):
    """client 能否拉到代表股日K(连通性+数据有效性探测)。"""
    if client is None:
        return False
    try:
        b = client.bars(symbol=_REPRESENTATIVE, frequency=9, offset=1)
        return b is not None and len(b) > 0
    except Exception:
        return False


def _get_client():
    """进程内单例 mootdx client(懒加载, 线程安全), 带服务器自适应。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if not _MOOTDX_OK:
                    return None
                # ① 缓存的可用服务器
                cached = _load_cached_server()
                if cached is not None:
                    c = _make_client(cached)
                    if _client_works(c):
                        _client = c
                        return _client
                # ② 默认 factory
                c = _make_client(None)
                if _client_works(c):
                    _client = c
                    _save_cached_server(('default', 0))
                    return _client
                # ③ 逐个探测候选服务器(先 socket 短超时预筛, 不通的 2s 跳过, 不卡死)
                for srv in _candidate_servers():
                    if not _tcp_open(srv[0], srv[1]):
                        continue
                    c = _make_client(srv)
                    if _client_works(c):
                        _client = c
                        _save_cached_server(srv)
                        return _client
    return _client


def _symbol(thscode):
    """'600519.SH' -> '600519'"""
    return thscode.split('.')[0]


def snapshot_date():
    """今日快照日期(代表股最后一根日K的日期, date)。

    进程内缓存。取不到返回 None。
    判定逻辑: 通达信最后一根日K的日期 == 今天 → 说明今日已出行情(盘中为当日未完成bar,
    收盘后为当日最终bar); 不等于今天(周末/节假日/开盘前) → 快照非今日, 调用方应回退历史。
    """
    global _snapshot_date
    if _snapshot_date is not None:
        return _snapshot_date
    with _snapshot_date_lock:
        if _snapshot_date is not None:
            return _snapshot_date
        c = _get_client()
        if c is None:
            return None
        try:
            b = c.bars(symbol=_REPRESENTATIVE, frequency=9, offset=1)  # 9=日K
            if b is None or len(b) == 0:
                return None
            _snapshot_date = b.index[-1].date()
        except Exception:
            return None
    return _snapshot_date


def get_live_bar(thscode, _today=None):
    """返回今日 mootdx 实时行情的 1 行 DataFrame(open/high/low/close/volume, 单位:股),
    索引为今日 16:00; 今日无实时行情(非交易日/未开市/取数失败)返回 None。

    与 run_param_sensitivity._tencent_live_bar 返回结构完全一致, 可直接互换。
    """
    c = _get_client()
    if c is None:
        return None
    if _today is None:
        _today = datetime.datetime.now().date()
    # 快照日期守卫: 今日未出行情则不拼 bar(避免把昨日收盘当今日)
    sd = snapshot_date()
    if sd is None or sd != _today:
        return None
    try:
        df = c.quotes(symbol=[_symbol(thscode)])
        if df is None or len(df) == 0:
            return None
        r = df.iloc[0]
        close = float(r['price'])
        openp = float(r['open'])
        high = float(r['high'])
        low = float(r['low'])
        vol_shares = float(r['vol']) * 100  # 手 -> 股, 与 hithink 对齐
        if close <= 0 or vol_shares <= 0:
            return None
        idx = pd.Timestamp(datetime.datetime.now().replace(
            hour=16, minute=0, second=0, microsecond=0))
        return pd.DataFrame(
            [{'open': openp, 'high': high, 'low': low,
              'close': close, 'volume': vol_shares}],
            index=[idx])
    except Exception:
        return None


def get_live_snapshot(thscodes, _today=None):
    """批量实时快照: 一次 quotes 拉多只, 返回 {thscode: {open,high,low,close,volume,last_close,change_pct}}.

    用于全市场盘中扫描器(screener_v18_atr_full_a.py)的最后一根 bar 校准, 比腾讯 HTTP
    快照更准(含昨收 last_close, 可算涨跌幅判涨停)。
    - 单位: volume 股(手*100), 与 hithink 历史序列对齐; 其余价格字段为元。
    - 快照日期守卫: 代表股最后一根日K日期 != 今天(非交易日/未开市) -> 返回 {}, 调用方回退腾讯。
    - 分批 80 只/次, 单批失败不影响其它批。
    """
    c = _get_client()
    if c is None:
        return {}
    if _today is None:
        _today = datetime.datetime.now().date()
    sd = snapshot_date()
    if sd is None or sd != _today:
        return {}
    out = {}
    syms = []
    sym2code = {}
    for thscode in thscodes:
        s = _symbol(thscode)
        syms.append(s)
        sym2code[s] = thscode
    for i in range(0, len(syms), 80):
        batch = syms[i:i + 80]
        try:
            df = c.quotes(symbol=batch)
        except Exception:
            continue
        if df is None or len(df) == 0:
            continue
        for _, r in df.iterrows():
            try:
                code = sym2code.get(str(r['code']).zfill(6))
                if not code:
                    continue
                close = float(r['price'])
                last_close = float(r['last_close']) if r.get('last_close') else 0.0
                vol_shares = float(r['vol']) * 100  # 手 -> 股
                if close <= 0:
                    continue
                change_pct = ((close - last_close) / last_close * 100) if last_close > 0 else None
                out[code] = {
                    'open': float(r['open']) if r.get('open') else 0.0,
                    'high': float(r['high']) if r.get('high') else 0.0,
                    'low': float(r['low']) if r.get('low') else 0.0,
                    'close': close,
                    'volume': vol_shares,
                    'last_close': last_close,
                    'change_pct': change_pct,
                }
            except Exception:
                continue
    return out


if __name__ == '__main__':
    # 自检: 打印代表股快照日期 + 几只样股的今日实时 bar
    print(f"mootdx 可用: {_MOOTDX_OK}")
    c = _get_client()
    print(f"client: {type(c).__name__ if c else None}  缓存服务器: {_load_cached_server()}")
    print(f"今日快照日期: {snapshot_date()}  (今天 {datetime.datetime.now().date()})")
    for code in ['600519.SH', '000001.SZ', '600300.SH']:
        bar = get_live_bar(code)
        if bar is None:
            print(f"{code}: 无今日实时行情(回退历史)")
        else:
            b = bar.iloc[0]
            print(f"{code}: 开{b['open']:.2f} 高{b['high']:.2f} "
                  f"低{b['low']:.2f} 收{b['close']:.2f} 量{b['volume']:.0f}股")
