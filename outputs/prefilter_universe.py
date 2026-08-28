#!/usr/bin/env python3
"""
135战法预筛模块 —— 在拉K线之前，用批量数据源砍掉:
  1) 次新股: 上市未满 MIN_LISTED_YEARS 年
  2) 大市值: 总市值 >= MAX_MARKET_CAP_YI 亿元
返回通过预筛的 thscode 列表 (如 600000.SH / 000001.SZ)

数据源(均为实测稳定可用):
  - 上市日期: 【主】tushare stock_basic (一次全市场, ts_code 即 thscode 格式)
               【兜底】akshare stock_info_sh/sz_name_code (沪/深交易所官方信息表)
  - 总市值  : 腾讯行情 qt.gtimg.cn 批量接口 (字段[45]=总市值, 亿元)
              (tushare daily_basic 限频 1次/分, 不适合批量市值, 故市值只走腾讯)
"""
import os
import json
import subprocess
import time
import datetime

# ============ 可调参数 ============
MAX_MARKET_CAP_YI = 200.0      # 总市值上限(亿元)，仅扫描 < 此值的股票
MIN_LISTED_YEARS = 1.0         # 次新股判定：上市未满 N 年视为次新，跳过
LISTDATE_CACHE_DAYS = 7        # 上市日期本地缓存有效期(天)，到期用 tushare 刷新
# ==================================

TOKEN_FILE = os.path.expanduser("~/.tushare_token")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".listdate_cache.json")
TS_TOKEN = None
if os.path.exists(TOKEN_FILE):
    try:
        TS_TOKEN = open(TOKEN_FILE).read().strip()
    except Exception:
        TS_TOKEN = None

TX_UA = "Mozilla/5.0"
TX_REF = "https://gu.qq.com/"


def _norm_date(s):
    """把 '20200101' / '2020-01-01' 归一化到 YYYY-MM-DD。"""
    if not s or s in ("None", "nan", "0", 0):
        return None
    s = str(s)[:10]
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _curl(url, timeout=20, retries=4):
    """curl 子进程取数（本环境 urllib 直连常被重置，统一走 curl）。返回 bytes。"""
    for _ in range(retries):
        try:
            out = subprocess.run(
                ["curl", "-s", "--max-time", str(timeout), "-A", TX_UA,
                 "-e", TX_REF, url],
                capture_output=True)
            if out.returncode == 0 and out.stdout:
                return out.stdout
        except Exception:
            pass
        time.sleep(1.0)
    return b""


def _cache_valid():
    if not os.path.exists(CACHE_FILE):
        return False
    try:
        with open(CACHE_FILE) as f:
            d = json.load(f)
        ts = d.get("_cached_at")
        if not ts:
            return False
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(ts)).days
        return age < LISTDATE_CACHE_DAYS
    except Exception:
        return False


def _read_cache():
    try:
        with open(CACHE_FILE) as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k != "_cached_at"}
    except Exception:
        return {}


def _write_cache(data):
    try:
        d = dict(data)
        d["_cached_at"] = datetime.datetime.now().isoformat()
        with open(CACHE_FILE, "w") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        print(f"  [prefilter] 写上市日缓存失败: {e}")


def _from_tushare():
    """tushare stock_basic 一次全市场(限频1次/小时, 故走缓存)。返回 {thscode:date}。"""
    if not TS_TOKEN:
        return None
    try:
        import tushare as ts
        ts.set_token(TS_TOKEN)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange="", list_status="L",
                             fields="ts_code,list_date")
        out = {}
        for _, r in df.iterrows():
            code = str(r["ts_code"]).strip()
            if code:
                out[code] = _norm_date(r["list_date"])
        print(f"  [prefilter] tushare 上市日: {len(out)} 只")
        return out
    except Exception as e:
        print(f"  [prefilter] tushare 上市日失败(可能限频): {e}")
        return None


def _from_akshare():
    """兜底: akshare 沪/深交易所信息表(稳定, 无上市日缓存时启用)。"""
    out = {}
    try:
        import akshare as ak
        try:
            sh = ak.stock_info_sh_name_code()
            for _, r in sh.iterrows():
                code = str(r.get("证券代码", "")).strip()
                if code:
                    out[f"{code}.SH"] = _norm_date(r.get("上市日期"))
        except Exception as e:
            print(f"  [prefilter] 沪市信息表失败: {e}")
        try:
            sz = ak.stock_info_sz_name_code()
            for _, r in sz.iterrows():
                code = str(r.get("A股代码", "")).strip()
                if code:
                    out[f"{code}.SZ"] = _norm_date(r.get("A股上市日期"))
        except Exception as e:
            print(f"  [prefilter] 深市信息表失败: {e}")
    except ImportError:
        pass
    return out


def load_listing_dates():
    """返回 {thscode: 'YYYY-MM-DD'}。优先级: 有效缓存 > tushare > akshare。"""
    if _cache_valid():
        cached = _read_cache()
        print(f"  [prefilter] 上市日缓存命中: {len(cached)} 只 (有效期{LISTDATE_CACHE_DAYS}天)")
        return cached
    # 缓存失效/不存在: 先试 tushare (每日最多1次, 不超频), 失败兜底 akshare
    data = _from_tushare()
    if not data:
        data = _from_akshare()
        print(f"  [prefilter] 上市日来源=akshare: {len(data)} 只")
    if data:
        _write_cache(data)
    return data


def load_market_caps(thscodes):
    """批量取总市值(亿元)。thscodes: list of '600000.SH'/'000001.SZ'。
    返回 {thscode: mv_yi}。数据源: 腾讯行情批量。"""
    caps = {}
    batch = 200
    for i in range(0, len(thscodes), batch):
        chunk = thscodes[i:i + batch]
        tx_codes = []
        for c in chunk:
            pre = "sh" if c.endswith(".SH") else "sz"
            tx_codes.append(pre + c[:6])
        url = "https://qt.gtimg.cn/q=" + ",".join(tx_codes)
        raw = _curl(url)
        if not raw:
            continue
        text = raw.decode("gbk", "ignore")
        for line in text.split(";"):
            line = line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"')
            f = val.split("~")
            tx_key = key.replace("v_", "").lower()   # sh600000
            if len(f) <= 45:
                continue
            try:
                mv = float(f[45])   # 总市值(亿元)
            except (ValueError, IndexError):
                mv = 0.0
            # 还原成 thscode
            pre = "SH" if tx_key.startswith("sh") else "SZ"
            thscode = f"{tx_key[2:]}.{pre}"
            caps[thscode] = mv
        time.sleep(0.3)
    return caps


def prefilter_universe():
    print("预筛: 加载上市日期(主源 tushare / 兜底 akshare)...")
    listing = load_listing_dates()
    print(f"  上市日期记录 {len(listing)} 只")

    # 主板+创业板前缀 (与 get_all_mainboard_codes 对齐, 排除北交所/科创板688)
    prefixes = ('600', '601', '603', '605', '000', '001', '002', '003',
                '300', '301')

    cands = {c: d for c, d in listing.items() if c[:3] in prefixes}

    print(f"预筛: 拉取市值(腾讯行情) {len(cands)} 只...")
    caps = load_market_caps(list(cands.keys()))

    cutoff = datetime.datetime.now() - datetime.timedelta(
        days=int(MIN_LISTED_YEARS * 365))
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    passed = []
    n_ipo = n_cap = 0
    for code, ld in cands.items():
        mv = caps.get(code, 0.0) or 0.0
        # 大市值过滤
        if mv >= MAX_MARKET_CAP_YI:
            n_cap += 1
            continue
        # 次新过滤 (无上市日则保守保留, 不误杀)
        if ld and ld > cutoff_str:
            n_ipo += 1
            continue
        passed.append(code)

    print(f"  预筛结果: 通过 {len(passed)} 只 | 跳过 次新 {n_ipo} / 大市值 {n_cap}")
    return passed


if __name__ == "__main__":
    res = prefilter_universe()
    print("样本前15:", res[:15])
