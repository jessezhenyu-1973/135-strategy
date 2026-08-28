#!/usr/bin/env python3
"""
135战法预筛模块 —— 在拉K线之前，用批量数据源砍掉:
  1) 次新股: 上市未满 MIN_LISTED_YEARS 年
  2) 大市值: 总市值 >= MAX_MARKET_CAP_YI 亿元
返回通过预筛的 thscode 列表 (如 600000.SH / 000001.SZ)

========================================================================
多数据源冗余架构 (三源互备, 多数决裁决)
------------------------------------------------------------------------
上市日期(3源):  东财push2delay【主/缓存】 → tushare stock_basic【兜底】 → akshare 沪/深信息表【兜底】
总市值(2源):    东财push2delay【主/缓存】 → 腾讯行情 qt.gtimg.cn【兜底】

裁决规则(多源冗余核心):
  - 次新: 3源中 >=2 源判定为次新 → 跳过 (多数决); 源缺失按"非次新"计(保守保留)
  - 大市值: 2源中 >=1 源判定为大市值 → 跳过 (因仅2源, 任一源告警即保守跳过)
  - 拿不到任何市值/上市日 → 保守保留(不误杀)

缓存策略: 东财push2delay 结果(市值+上市日)落本地 .prefilter_cache.json,
          有效期 CACHE_DAYS 天; 过期才重拉东财; 兜底源(tushare/akshare/腾讯)实时查。
          东财push2delay 为延时接口(~15min), 对市值/上市日预筛无影响。
========================================================================
"""
import os
import json
import subprocess
import time
import datetime

# ============ 可调参数 ============
MAX_MARKET_CAP_YI = 200.0      # 总市值上限(亿元)，仅扫描 < 此值的股票
MIN_LISTED_YEARS = 1.0         # 次新股判定：上市未满 N 年视为次新，跳过
CACHE_DAYS = 7                 # 东财主源缓存有效期(天)，到期重拉
PROXY = "socks5h://127.0.0.1:10808"   # 本机 v2rayN(xray) 代理；直连东财偶发重置
# ==================================

TOKEN_FILE = os.path.expanduser("~/.tushare_token")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".prefilter_cache.json")

TS_TOKEN = None
if os.path.exists(TOKEN_FILE):
    try:
        TS_TOKEN = open(TOKEN_FILE).read().strip()
    except Exception:
        TS_TOKEN = None

EM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TX_UA = "Mozilla/5.0"
TX_REF = "https://gu.qq.com/"
EM_DELAY = "https://push2delay.eastmoney.com/api/qt/clist/get"
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"   # 沪深主板+创业板+科创/北交筛选在下游做


def _norm_date(s):
    """把 '20200101' / '2020-01-01' 归一化到 YYYY-MM-DD。"""
    if not s or s in ("None", "nan", "0", 0, "-"):
        return None
    s = str(s)[:10]
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _curl(url, timeout=25, retries=6, proxy=None, ua=TX_UA, ref=TX_REF):
    """curl 子进程取数（本环境 urllib 直连常被重置，统一走 curl + 代理）。
    返回 bytes；失败返回 b''。"""
    for _ in range(retries):
        try:
            cmd = ["curl", "-s", "--max-time", str(timeout)]
            if proxy:
                cmd += ["-x", proxy]
            cmd += ["-A", ua, "-e", ref, url]
            out = subprocess.run(cmd, capture_output=True)
            if out.returncode == 0 and out.stdout:
                return out.stdout
        except Exception:
            pass
        time.sleep(1.5)
    return b""


# ===================== 缓存层 =====================
def _cache_valid():
    if not os.path.exists(CACHE_FILE):
        return False
    try:
        d = json.load(open(CACHE_FILE))
        ts = d.get("_cached_at")
        if not ts:
            return False
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(ts)).days
        return age < CACHE_DAYS
    except Exception:
        return False


def _read_cache():
    try:
        d = json.load(open(CACHE_FILE))
        return {k: v for k, v in d.items() if k != "_cached_at"}
    except Exception:
        return {}


def _write_cache(data):
    try:
        d = dict(data)
        d["_cached_at"] = datetime.datetime.now().isoformat()
        json.dump(d, open(CACHE_FILE, "w"), ensure_ascii=False)
    except Exception as e:
        print(f"  [prefilter] 写东财缓存失败: {e}")


# ===================== 源1: 东方财富 push2delay (主) =====================
def _from_eastmoney():
    """东财 push2delay 批量接口。一次分页拉全市场, 含 f20(总市值/元) + f26(上市日)。
    返回 {thscode: {'mv_yi': float, 'list_date': 'YYYY-MM-DD'}}。"""
    out = {}
    pn, pz = 1, 100
    while True:
        qs = "&".join([f"pn={pn}", f"pz={pz}", "po=1", "np=1", "fltt=2",
                       "invt=2", f"fs={FS}", "fields=f12,f14,f20,f26"])
        raw = _curl(f"{EM_DELAY}?{qs}", proxy=PROXY, ua=EM_UA,
                    ref="https://quote.eastmoney.com/")
        if not raw:
            break
        try:
            d = json.loads(raw)
        except Exception:
            break
        data = d.get("data") or {}
        diff = data.get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff
        if not items:
            break
        for v in items:
            code = (v.get("f12") or "").strip()
            if not code:
                continue
            try:
                mv = float(v.get("f20") or 0) / 1e8   # 元→亿元
            except (ValueError, TypeError):
                mv = 0.0
            ld = _norm_date(v.get("f26"))
            ex = "SH" if code.startswith(("60", "68", "9")) else "SZ"
            out[f"{code}.{ex}"] = {"mv_yi": mv, "list_date": ld}
        total = data.get("total", 0)
        if pn * pz >= total:
            break
        pn += 1
    print(f"  [prefilter] 东财push2delay: {len(out)} 只")
    return out


# ===================== 源2: tushare (上市日兜底) =====================
def _from_tushare():
    """tushare stock_basic 一次全市场(限频1次/小时)。返回 {thscode: 'YYYY-MM-DD'}。"""
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


# ===================== 源3: akshare 沪/深信息表 (上市日兜底) =====================
def _from_akshare():
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


# ===================== 源4: 腾讯行情 (市值兜底) =====================
def _from_tencent(thscodes):
    """腾讯行情批量, 字段[45]=总市值(亿元)。返回 {thscode: mv_yi}。"""
    caps = {}
    for i in range(0, len(thscodes), 200):
        chunk = thscodes[i:i + 200]
        tx = []
        for c in chunk:
            pre = "sh" if c.endswith(".SH") else "sz"
            tx.append(pre + c[:6])
        raw = _curl("https://qt.gtimg.cn/q=" + ",".join(tx))
        if not raw:
            continue
        text = raw.decode("gbk", "ignore")
        for line in text.split(";"):
            line = line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            f = val.strip().strip('"').split("~")
            tx_key = key.replace("v_", "").lower()
            if len(f) <= 45:
                continue
            try:
                mv = float(f[45])
            except (ValueError, IndexError):
                mv = 0.0
            pre = "SH" if tx_key.startswith("sh") else "SZ"
            caps[f"{tx_key[2:]}.{pre}"] = mv
        time.sleep(0.3)
    return caps


# ===================== 主流程 =====================
def prefilter_universe():
    print("预筛: 拉取多源数据(东财主/缓存 + tushare/akshare/腾讯兜底)...")

    # ---- 东财主源(带缓存) ----
    if _cache_valid():
        em = _read_cache()
        print(f"  [prefilter] 东财缓存命中: {len(em)} 只 (有效期{CACHE_DAYS}天)")
    else:
        em = _from_eastmoney()
        if em:
            _write_cache(em)

    # 候选池: 主板+创业板 (排除北交所/科创板688)
    prefixes = ('600', '601', '603', '605', '000', '001', '002', '003',
                '300', '301')
    cands = {c: v for c, v in em.items() if c[:3] in prefixes} \
        if em else {}

    # 兜底源实时拉取
    ts_dates = _from_tushare() or {}
    ak_dates = _from_akshare()
    # 合并上市日兜底 (东财缺则补 tushare, 再缺补 akshare)
    all_codes = list(cands.keys())
    tx_caps = _from_tencent(all_codes) if all_codes else {}

    cutoff = datetime.datetime.now() - datetime.timedelta(
        days=int(MIN_LISTED_YEARS * 365))
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    passed = []
    n_ipo = n_cap = 0
    for code in all_codes:
        em_v = cands.get(code, {})
        em_mv = em_v.get("mv_yi", 0.0) or 0.0
        em_ld = em_v.get("list_date")

        # ---------- 市值裁决 (2源: 东财 + 腾讯) ----------
        # 多数决: 仅2源 → 任一源判大市值即跳过(保守)
        tx_mv = tx_caps.get(code, 0.0) or 0.0
        big_by_em = em_mv >= MAX_MARKET_CAP_YI
        big_by_tx = tx_mv >= MAX_MARKET_CAP_YI
        # 两源都无市值数据 → 保守保留
        if em_mv == 0.0 and tx_mv == 0.0:
            pass  # 保留
        elif big_by_em or big_by_tx:   # 任一源判大市值 → 跳过(保守多数决)
            n_cap += 1
            continue

        # ---------- 次新裁决 (3源: 东财 + tushare + akshare) ----------
        # 多数决: >=2 源判次新才跳过; 源缺失按"非次新"计
        votes_ipo = 0
        if em_ld and em_ld > cutoff_str:
            votes_ipo += 1
        ts_ld = ts_dates.get(code)
        if ts_ld and ts_ld > cutoff_str:
            votes_ipo += 1
        ak_ld = ak_dates.get(code)
        if ak_ld and ak_ld > cutoff_str:
            votes_ipo += 1
        if votes_ipo >= 2:    # 多数决(3源中>=2)
            n_ipo += 1
            continue

        passed.append(code)

    print(f"  预筛结果: 通过 {len(passed)} 只 | 跳过 次新 {n_ipo} / 大市值 {n_cap}")
    return passed


if __name__ == "__main__":
    res = prefilter_universe()
    print("样本前15:", res[:15])
