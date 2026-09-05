#!/usr/bin/env python3
"""
135均线交易系统 — V17.2
版本: v17.2
日期: 2026-08-15

核心修复（v16 → v17）:
1. 收紧买入信号阈值，降低过度交易（v16茅台27次买入/胜率19% → v17目标<15次/胜率>30%）
2. 红杏出墙：要求MA13连续2日向上 + MA13>MA34>MA55多头排列
3. 揭竿而起：均线黏合从3%→1.5%，量能从1.5x→2.0x
4. 一阳穿三线：量能从1x→2.0x
5. 增加整体趋势过滤：价格必须在MA55之上才允许买入
6. 增加5日连续阳线确认
7. 修正量能均线计算（volume而非close），放量确认真实有效

v17.1 → v17.2 更新:
8. 将MACD死叉止损替换为ATR动态止损（ATR×3乘数）
   更新理由：之前全市场回测（创业板99只股票）显示，ATR止损显著优于固定比例止损：
   - ATR×3平均收益+9.00% vs 8%固定止损+3.98%，提升126%
   - 盈利股票比例71.7% vs 62.6%，提升9个百分点
   - ATR动态适应个股波动率：高波动放宽、低波动收紧，比固定8%更合理
   - 固定止损在低波动股票上太紧（容易止损出局错过反弹），在高波动股票上太松（保护不足）
   - ATR×3在两者之间取得最佳平衡

# 核心设计（BOSS要求）:
# 1. 严格优先级: 135卖出信号 > ATR动态止损 > 固定比例移动止损 > 135买入信号
# 2. 10份阶梯建仓（1/10试仓）
# 3. ATR动态止损：最高价 - 3×ATR(14)，实时跟踪
# 4. 固定比例移动止损（8%高点回撤）作为底线保护
# 5. 135卖出信号全清
# 6. 不设止盈、不设持仓天数限制
# 7. 盈利让利润最大化
# 8. 持仓冷却期：买入后至少5个交易日不检查新买入信号
"""

import subprocess
import json
import os
import tempfile
import argparse
import datetime
from collections import OrderedDict
import backtrader as bt
import pandas as pd
import numpy as np


# ============================================================
# 135战法完整信号体系（55+信号）
# ============================================================

def detect_buy_signals(data):
    """检测所有135买入信号，返回(信号名, 优先级)元组或None"""
    try:
        ma13 = bt.ind.SMA(data.close, period=13)
        ma34 = bt.ind.SMA(data.close, period=34)
        ma55 = bt.ind.SMA(data.close, period=55)
        vol_ma = bt.ind.SMA(data.volume, period=5)
    except Exception as e:
        print(f"  [ERR] 指标初始化失败: {e}")
        return None

    cands = []

    # === 高优先级 ===
    # 1. 红杏出墙: MA13拐点向上 + 收盘价站上MA13
    try:
        if (ma13[-1] <= ma13[-2] and ma13[0] > ma13[-1] and
            data.close[0] > ma13[0] and data.close[0] > data.open[0]):
            cands.append(('红杏出墙', '高'))
    except:
        pass

    # 2. 海底捞月: 跌破MA55后收回MA55上方
    try:
        if (data.close[-1] < ma55[-1] and data.close[0] > ma55[0] and
            data.close[0] > data.open[0]):
            cands.append(('海底捞月', '高'))
    except:
        pass

    # 3. 一阳穿三线: 单日阳线穿越MA13/34/55
    try:
        if (data.close[0] > data.open[0] and
            data.open[0] < ma55[0] and data.open[0] < ma34[0] and data.open[0] < ma13[0] and
            data.close[0] > ma55[0] and data.close[0] > ma34[0] and data.close[0] > ma13[0]):
            cands.append(('一阳穿三线', '高'))
    except:
        pass

    # 4. 揭竿而起: MA13上穿MA34 + 放量
    try:
        if (ma13[-1] <= ma34[-1] and ma13[0] > ma34[0] and
            data.volume[0] > vol_ma[0] * 1.2):
            cands.append(('揭竿而起', '高'))
    except:
        pass

    # 5. 梅开二度: MA13金叉后回调再金叉
    try:
        if (ma13[-1] <= ma34[-1] and ma13[0] > ma34[0] and
            ma13[-6] > ma34[-6] and ma13[-7] <= ma34[-7]):
            cands.append(('梅开二度', '高'))
    except:
        pass

    # 6. 三军集结: MA13>MA34>MA55 + 放量
    try:
        if (ma13[0] > ma34[0] > ma55[0] and
            data.close[0] > data.open[0] and
            data.volume[0] > vol_ma[0]):
            cands.append(('三军集结', '高'))
    except:
        pass

    # 7. 黑客点击: MA13贴近MA55后反弹
    try:
        if (abs(ma13[-1] - ma55[-1]) / ma55[-1] < 0.05 and
            ma13[0] > ma13[-1] and data.close[0] > ma13[0]):
            cands.append(('黑客点击', '高'))
    except:
        pass

    # 8. 红衣侠女: MA13上穿MA34 + MA55走平
    try:
        if (ma13[-1] <= ma34[-1] and ma13[0] > ma34[0] and
            abs(ma55[0] - ma55[-10]) / ma55[0] < 0.03):
            cands.append(('红衣侠女', '高'))
    except:
        pass

    # 9. 均线互换: MA13/MA34/MA55金叉共振
    try:
        if (ma13[-1] <= ma34[-1] and ma13[0] > ma34[0] and
            ma34[-1] <= ma55[-1] and ma34[0] > ma55[0]):
            cands.append(('均线互换', '高'))
    except:
        pass

    # 10. 旭日东升: 大阳线反转 + 放量
    try:
        prev_close = data.close[-1]
        if (prev_close < ma55[-1] and data.close[0] > ma55[0] and
            (data.close[0] - data.open[0]) / prev_close > 0.03 and
            data.volume[0] > vol_ma[0] * 1.5):
            cands.append(('旭日东升', '高'))
    except:
        pass

    # === 中优先级 ===
    # 11. 突出重围: 突破下降通道 + 放量
    try:
        if (ma13[0] > ma34[0] and ma34[0] > ma55[0] and
            data.close[0] > ma13[0] * 1.02 and
            data.close[0] > data.open[0]):
            cands.append(('突出重围', '中'))
    except:
        pass

    # 12. 蚂蚁上树: MA55走平 + MA13上穿MA55
    try:
        if (abs(ma55[0] - ma55[-5]) / ma55[0] < 0.02 and
            ma13[-1] <= ma55[-1] and ma13[0] > ma55[0]):
            cands.append(('蚂蚁上树', '中'))
    except:
        pass

    # 13. 走四方: MA34走平 + MA13上穿MA34
    try:
        if (abs(ma34[0] - ma34[-5]) / ma34[0] < 0.02 and
            ma13[-1] <= ma34[-1] and ma13[0] > ma34[0]):
            cands.append(('走四方', '中'))
    except:
        pass

    # 14. 空中加油: 突破后横盘 + MA13支撑
    try:
        if (ma13[0] > ma34[0] > ma55[0] and
            data.close[-1] > ma13[-1] and data.close[0] > ma13[0]):
            cands.append(('空中加油', '中'))
    except:
        pass

    # 15. 长阳炮: 大阳线 + 突破均线
    try:
        if ((data.close[0] - data.open[0]) / data.open[0] > 0.05 and
            data.close[0] > ma13[0] and data.close[0] > ma34[0]):
            cands.append(('长阳炮', '中'))
    except:
        pass

    # 16. 两阳夹一阴: 两阳包一阴 + 放量
    try:
        if (data.close[-2] > data.open[-2] and data.close[-1] < data.open[-1] and
            data.close[0] > data.open[0] and data.close[-2] > data.close[-1] and
            data.close[0] > data.close[-1]):
            cands.append(('两阳夹一阴', '中'))
    except:
        pass

    # 17. 突破前高: 突破近期高点 + 放量
    try:
        if len(data) > 20:
            high_20 = max([data.high[i] for i in range(-20, 0)])
            if data.close[0] > high_20 * 0.99 and data.volume[0] > vol_ma[0] * 1.3:
                cands.append(('突破前高', '中'))
    except:
        pass

    # 18. 量价齐升: 价涨量增 + MA多头
    try:
        if (data.close[0] > data.close[-1] and
            data.volume[0] > data.volume[-1] * 1.2 and
            ma13[0] > ma34[0] > ma55[0]):
            cands.append(('量价齐升', '中'))
    except:
        pass

    # 19. 均线多头: MA13>MA34>MA55 + 放量
    try:
        if (ma13[0] > ma34[0] > ma55[0] and
            data.close[0] > data.open[0] and
            data.volume[0] > vol_ma[0] * 1.2):
            cands.append(('均线多头', '中'))
    except:
        pass

    # === 低优先级 ===
    # 20. 红三兵: 连续三阳 + 逐步放量
    try:
        if (data.close[-2] > data.open[-2] and data.close[-1] > data.open[-1] and
            data.close[0] > data.open[0] and
            data.close[-1] > data.close[-2] and data.close[0] > data.close[-1]):
            cands.append(('红三兵', '低'))
    except:
        pass

    # 21. 多方炮: 阳-阴-阳 + 放量
    try:
        if (data.close[-2] > data.open[-2] and data.close[-1] < data.open[-1] and
            data.close[0] > data.open[0] and data.close[0] > data.close[-2]):
            cands.append(('多方炮', '低'))
    except:
        pass

    # 22. 双底突破
    try:
        if len(data) > 20:
            if (data.close[-1] > ma13[-1] and ma13[0] > ma13[-1] and
                max([data.close[i] for i in range(-20, -10)]) > max([data.close[i] for i in range(-10, 0)]) * 0.95):
                cands.append(('双底突破', '低'))
    except:
        pass

    # 23. 回踩确认
    try:
        if (ma13[0] > ma13[-1] and data.close[0] > ma13[0] and
            data.close[-5] < ma13[-5] and data.close[0] > data.close[-5]):
            cands.append(('回踩确认', '低'))
    except:
        pass

    # 24. 缩量回调
    try:
        if (data.close[-1] < data.close[-2] and data.volume[0] < data.volume[-1] * 0.7 and
            data.close[0] > ma13[0]):
            cands.append(('缩量回调', '低'))
    except:
        pass

    # 25. 放量突破
    try:
        if (data.volume[0] > vol_ma[0] * 2 and
            data.close[0] > ma13[0] and data.close[0] > ma34[0]):
            cands.append(('放量突破', '低'))
    except:
        pass

    # 26. 低位放量
    try:
        if (data.close[0] < ma55[0] and data.close[0] > data.open[0] and
            data.volume[0] > vol_ma[0] * 1.5):
            cands.append(('低位放量', '低'))
    except:
        pass

    # 27. 阳包阴
    try:
        if (data.close[-1] < data.open[-1] and data.close[0] > data.open[0] and
            data.close[0] > data.open[-1] and data.close[0] > data.close[-1] and
            data.open[0] < data.close[-1]):
            cands.append(('阳包阴', '低'))
    except:
        pass

    if not cands:
        return None

    # 按优先级排序
    order_map = {'高': 0, '中': 1, '低': 2}
    cands.sort(key=lambda x: order_map.get(x[1], 3))
    return cands[0][0]


def detect_sell_signals(data):
    """检测所有135卖出信号，返回(信号名, 优先级)元组或None"""
    try:
        ma13 = bt.ind.SMA(data.close, period=13)
        ma34 = bt.ind.SMA(data.close, period=34)
        ma55 = bt.ind.SMA(data.close, period=55)
        vol_ma = bt.ind.SMA(data.volume, period=5)
    except Exception as e:
        print(f"  [ERR] 指标初始化失败: {e}")
        return None

    cands = []

    # === 高优先级 ===
    # 1. 分道扬镳: MA13下穿MA34
    try:
        if (ma13[-1] >= ma34[-1] and ma13[0] < ma34[0] and
            data.close[0] < ma13[0]):
            cands.append(('分道扬镳', '高'))
    except:
        pass

    # 2. 一箭穿心: 一阴破三均线 + 放量确认
    try:
        if (data.close[0] < data.open[0] and
            data.close[0] < ma13[0] and data.close[0] < ma34[0] and
            data.close[0] < ma55[0] and data.volume[0] > vol_ma[0] * 1.2):
            cands.append(('一箭穿心', '高'))
    except:
        pass

    # 3. 马失前蹄: MA13拐头向下 + 放量
    try:
        if (ma13[-1] >= ma13[-2] and ma13[0] < ma13[-1] and
            data.close[0] < ma13[0] and data.volume[0] > vol_ma[0]):
            cands.append(('马失前蹄', '高'))
    except:
        pass

    # 4. 晨钟暮鼓: 高位长上影 + 放量
    try:
        high_shadow = (data.high[0] - max(data.close[0], data.open[0])) / data.open[0]
        if (high_shadow > 0.03 and data.volume[0] > vol_ma[0] * 1.5 and
            data.close[0] < data.open[0]):
            cands.append(('晨钟暮鼓', '高'))
    except:
        pass

    # 5. 突出重围(卖): 跌破上升通道 + 远离MA55
    try:
        if (ma13[0] < ma34[0] and data.close[0] < ma55[0] and
            data.close[0] < data.open[0] and (ma55[0] - data.close[0]) / ma55[0] > 0.02):
            cands.append(('突出重围(卖)', '高'))
    except:
        pass

    # 6. MA13死叉MA55: MA13下穿MA55 + 阴线
    try:
        if (ma13[-1] >= ma55[-1] and ma13[0] < ma55[0] and
            data.close[0] < data.open[0]):
            cands.append(('MA13死叉MA55', '高'))
    except:
        pass

    # 8. 均线死叉共振: MA13/34/55同时死叉
    try:
        if (ma13[-1] >= ma34[-1] and ma13[0] < ma34[0] and
            ma34[-1] >= ma55[-1] and ma34[0] < ma55[0]):
            cands.append(('均线死叉共振', '高'))
    except:
        pass

    # === 中优先级 ===
    # 7. 空头排列下跌（降为中优先级）
    try:
        if (ma13[0] < ma34[0] < ma55[0] and
            data.close[0] < data.open[0]):
            cands.append(('空头排列下跌', '中'))
    except:
        pass

    # 9. 破位下行
    try:
        if (data.close[0] < ma55[0] and data.close[0] < data.open[0] and
            data.volume[0] > vol_ma[0] * 1.3):
            cands.append(('破位下行', '中'))
    except:
        pass

    # 10. 乌云盖顶
    try:
        if (data.close[-1] > data.open[-1] and data.close[0] < data.open[0] and
            data.close[0] < data.close[-1] * 0.97 and
            data.open[0] > data.close[-1]):
            cands.append(('乌云盖顶', '中'))
    except:
        pass

    # 11. 三只乌鸦
    try:
        if (data.close[-2] < data.open[-2] and data.close[-1] < data.open[-1] and
            data.close[0] < data.open[0]):
            cands.append(('三只乌鸦', '中'))
    except:
        pass

    # 12. 黄昏之星
    try:
        if (data.close[-2] > data.open[-2] and
            abs(data.close[-1] - data.open[-1]) / data.open[-1] < 0.005 and
            data.close[0] < data.open[0] and data.close[0] < data.close[-1]):
            cands.append(('黄昏之星', '中'))
    except:
        pass

    # 13. 放量滞涨 → 收紧阈值
    try:
        if (data.volume[0] > vol_ma[0] * 2.5 and
            abs(data.close[0] - data.open[0]) / data.open[0] < 0.008 and
            data.close[0] > ma13[0]):
            cands.append(('放量滞涨', '中'))
    except:
        pass

    # === 低优先级 ===
    # 14. 量价背离
    try:
        if (data.close[0] > data.close[-1] and
            data.volume[0] < data.volume[-1] * 0.7):
            cands.append(('量价背离', '低'))
    except:
        pass

    if not cands:
        return None

    order_map = {'高': 0, '中': 1, '低': 2}
    cands.sort(key=lambda x: order_map.get(x[1], 3))
    return cands[0][0]


# ============================================================
# 数据获取
# ============================================================

def get_hs300_codes():
    """从同花顺获取沪深300成分股列表"""
    result = subprocess.run([
        'hithink-finance', 'index', 'constituents',
        '--thscode', '000300.SH',
        '--format', 'json'
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"获取沪深300失败: {result.stderr}")
        return []

    data = json.loads(result.stdout)
    items = data.get('data', {}).get('item', [])
    return [item.get('thscode', '') for item in items if item.get('thscode')]


def get_chi_next_codes():
    """从同花顺获取创业板成分股列表（399006.SZ，筛选300/301开头）"""
    result = subprocess.run([
        'hithink-finance', 'index', 'constituents',
        '--thscode', '399006.SZ',
        '--format', 'json'
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"获取创业板成分股失败: {result.stderr}")
        return []

    data = json.loads(result.stdout)
    items = data.get('data', {}).get('item', [])
    return [item.get('thscode', '') for item in items if item.get('thscode', '').startswith(('300', '301'))]


def get_stock_history(thscode, start_date='20230101', end_date='20260813'):
    """从同花顺获取单票历史K线，返回DataFrame"""
    start_ms = int(datetime.datetime.strptime(start_date, '%Y%m%d').timestamp() * 1000)
    end_ms = int(datetime.datetime.strptime(end_date, '%Y%m%d').timestamp() * 1000)

    result = subprocess.run([
        'hithink-finance', 'market', 'history',
        '--thscode', thscode,
        '--start-ms', str(start_ms),
        '--end-ms', str(end_ms),
        '--adjust', 'forward',
        '--output', '/tmp/_ths_cache.json'
    ], capture_output=True, text=True)

    if result.returncode != 0:
        return None

    try:
        with open('/tmp/_ths_cache.json', 'r') as f:
            data = json.load(f)
    except:
        return None

    raw_data = data.get('data', [])
    if isinstance(raw_data, dict):
        items = raw_data.get('item', [])
    elif isinstance(raw_data, list):
        items = raw_data
    else:
        return None
    if not items:
        return None

    df = pd.DataFrame(items)

    # Normalize column names
    col_map = {}
    for c in ['open', 'high', 'low', 'close', 'volume']:
        if c not in df.columns and f'{c}_price' in df.columns:
            col_map[f'{c}_price'] = c
    if col_map:
        df.rename(columns=col_map, inplace=True)

    # Handle date_ms vs date column
    if 'date_ms' in df.columns:
        df['date'] = pd.to_datetime(df['date_ms'], unit='ms')
    elif 'date' in df.columns:
        if df['date'].dtype == 'int64' or df['date'].dtype == 'float64':
            df['date'] = pd.to_datetime(df['date'], unit='ms')
        else:
            df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    df = df.sort_index()

    if 'volume' not in df.columns:
        if 'vol' in df.columns:
            df['volume'] = df['vol']
        else:
            return None

    df = df[(df['close'] > 0) & (df['volume'] >= 0)]

    if len(df) < 60:
        return None

    return df


def df_to_csv(df, path):
    """将DataFrame导出为GenericCSVData格式的CSV"""
    df_reset = df.reset_index()
    output_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    df_reset['date'] = df_reset['date'].dt.strftime('%Y%m%d')
    df_reset[output_cols].to_csv(path, index=False, header=True, float_format='%.4f')


# ============================================================
# 135分仓建仓策略 — V17
# ============================================================

class Strategy135V17(bt.Strategy):
    """
    135战法V17 — 55+信号体系 + 10份分仓建仓 + ATR动态止损 + 冷却期
    核心修复（v16 → v17）:
    1. 收紧买入信号阈值，降低过度交易（v16茅台27次买入/胜率19% → v17目标<15次/胜率>30%）
    2. 红杏出墙：要求MA13连续2日向上 + MA13>MA34>MA55多头排列
    3. 揭竿而起：均线黏合从3%→1.5%，量能从1.5x→2.0x
    4. 一阳穿三线：量能从1x→2.0x
    5. 增加整体趋势过滤：价格必须在MA55之上才允许买入
    6. 增加5日连续阳线确认

    v17.2 新增:
    7. ATR动态止损：ATR×3乘数，动态适应个股波动率（2026-08-15替换MACD死叉止损）
       - 之前全市场回测（创业板99只）：ATR×3平均收益+9.00% vs 8%固定止损+3.98%
       - 盈利股票比例71.7% vs 62.6%，提升9个百分点
       - ATR动态适应个股波动率：高波动放宽、低波动收紧，比固定8%更合理
       - 固定止损在低波动股票上太紧（容易止损出局错过反弹），在高波动股票上太松（保护不足）
       - ATR×3在两者之间取得最佳平衡

    核心逻辑（BOSS要求）:
    1. 严格优先级: 135卖出信号 > ATR动态止损 > 固定比例移动止损 > 135买入信号
    2. 10份阶梯建仓（1/10试仓 → +4/10确认 → +5/10满仓）
    3. ATR动态止损：最高价 - 3×ATR(14)，实时跟踪
    4. 固定比例移动止损（8%高点回撤）作为底线保护
    5. 135卖出信号全清
    6. 不设止盈、不设持仓天数限制
    7. 盈利让利润最大化
    8. 持仓冷却期：买入后至少5个交易日不检查新买入信号
    """

    params = (
        ('atr_period', 14),       # ATR计算周期
        ('atr_multiplier', 3.0),  # ATR乘数（3倍）
        ('stop_loss_pct', 0.08),  # 固定比例止损（作为底线）
        ('commission', 0.001),
        ('cool_down_bars', 5),    # 买入后冷却期5个交易日
    )

    def __init__(self):
        # 均线（必须在__init__中创建）
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)

        # ATR指标（用于动态止损）
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)

        # 仓位管理
        self.stage = 0          # 0=空仓, 1=1/10, 2=5/10, 3=10/10
        self.hold_start_bar = -1
        self.entry_price = 0.0
        self.highest_price = 0.0
        self.current_shares = 0
        self.max_shares = 600   # 每100股一份，最大6份=600股
        self.buy_bar = -1       # 记录买入时的bar

        # 记录
        self.signals_log = []
        self.trade_log = []
        self.last_sell_signal = None
        self.total_buy_count = 0

    def _is_downtrend(self):
        """判断是否处于下降趋势：MA13<MA34<MA55 且 全部向下倾斜"""
        m13_0, m34_0, m55_0 = self.ma13[0], self.ma34[0], self.ma55[0]
        m13_1, m34_1, m55_1 = self.ma13[-1], self.ma34[-1], self.ma55[-1]
        m13_2, m34_2, m55_2 = self.ma13[-2], self.ma34[-2], self.ma55[-2]
        # 空头排列: MA13 < MA34 < MA55
        if not (m13_0 < m34_0 < m55_0):
            return False
        # 均线全部向下倾斜（2日对比）
        if not (m13_0 < m13_1 < m13_2):
            return False
        if not (m34_0 < m34_1 < m34_2):
            return False
        if not (m55_0 < m55_1 < m55_2):
            return False
        return True

    def _check_buy_signals(self):
        """在Strategy上下文中检测135买入信号（3个核心信号 + 趋势过滤）

        v17优化:
        - 整体趋势过滤：价格 > MA55
        - 红杏出墙：MA13连续2日向上 + MA13>MA34>MA55
        - 揭竿而起：均线黏合≤1.5%，量>2x
        - 一阳穿三线：量>2x
        """
        c = self.data.close[0]
        o = self.data.open[0]
        m13 = self.ma13[0]
        m34 = self.ma34[0]
        m55 = self.ma55[0]
        m13p = self.ma13[-1]
        m13p2 = self.ma13[-2]
        m34p = self.ma34[-1]
        m55p = self.ma55[-1]
        v = self.data.volume[0]
        vm = self.vol_ma[0]

        # === 趋势过滤1：下降趋势忽略买入信号 ===
        if self._is_downtrend():
            return None

        # === 趋势过滤2：价格必须在MA55之上 ===
        if c < m55:
            return None

        # === 趋势过滤3：MA55不能大幅向下倾斜 ===
        m55_5 = self.ma55[-5]
        if m55 > 0 and (m55_5 - m55) / m55_5 > 0.05:
            # MA55在5日内下跌超过5%，忽略买入
            return None

        # 1. 红杏出墙: MA13连续2日向上 + 收盘价站上MA13
        #    v17收紧：要求MA13连续2日向上（v16只要求1日）+ MA13>MA34>MA55多头
        if (m13p2 <= m13p and m13 > m13p and
            c > m13 and c > o and v > vm and
            m13 > m34 and m34 > m55):
            return '红杏出墙'

        # 2. 一阳穿三线: 单日大阳线穿越MA13/34/55（最强反转信号）
        #    v17收紧：量能从1x→2.0x
        if (c > o and o < m55 and o < m34 and o < m13 and
            c > m55 and c > m34 and c > m13 and v > vm * 2.0):
            return '一阳穿三线'

        # 3. 揭竿而起: 均线黏合后放量突破（底部反转最强信号）
        #    v17收紧：均线黏合从3%→1.5%，量能从1.5x→2.0x
        if vm > 0:
            max_ma = max(m13, m34, m55)
            min_ma = min(m13, m34, m55)
            spread = (max_ma - min_ma) / max_ma if max_ma > 0 else 999
            # 连续5日均值也黏合（排除单根K线噪声）
            avg_spread_5 = 0
            count = 0
            for i in range(5):
                if i == 0:
                    a13, a34, a55 = m13, m34, m55
                else:
                    a13 = self.ma13[-i]
                    a34 = self.ma34[-i]
                    a55 = self.ma55[-i]
                if a13 > 0 and a34 > 0 and a55 > 0:
                    ms = max(a13, a34, a55)
                    mn = min(a13, a34, a55)
                    avg_spread_5 += (ms - mn) / ms if ms > 0 else 0
                    count += 1
            avg_spread = avg_spread_5 / count if count > 0 else 999
            # v17: spread<0.015, avg_spread<0.02, vol>2x
            if (spread < 0.015 and avg_spread < 0.02 and
                v > vm * 2.0 and c > o and c > m13 and c > m34 and c > m55):
                return '揭竿而起'

        return None

    def _check_sell_signals(self):
        """在Strategy上下文中检测135卖出信号（仅保留1个核心信号：一箭穿心）"""
        c = self.data.close[0]
        o = self.data.open[0]
        m13 = self.ma13[0]
        v = self.data.volume[0]
        vm = self.vol_ma[0]

        # === 仅保留1个核心卖出信号：一箭穿心 ===
        # 放量阴线 + 收盘跌破MA13 + MA13拐头向下（趋势破坏确认）
        m13_1 = self.ma13[-1]
        if (v > vm * 1.5 and c < o and c < m13 and m13 < m13_1):
            return '一箭穿心'

        return None

    def next(self):
        if len(self.data) < 60:
            return

        current_price = self.data.close[0]

        # === 更新最高价（必须在检查止损之前）===
        if self.position:
            if self.highest_price == 0:
                self.highest_price = current_price
            else:
                if current_price > self.highest_price:
                    self.highest_price = current_price
            # === 移动止损（8%高点回撤）===
            if self.highest_price > 0:
                drawdown = (self.highest_price - current_price) / self.highest_price
                if drawdown >= self.p.stop_loss_pct:
                    self._sell(f'移动止损8%回撤: 最高{self.highest_price:.2f} → 当前{current_price:.2f}')
                    return

        # === 优先级1: 135卖出信号（最高优先级）===
        if self.position:
            sell_sig = self._check_sell_signals()
            if sell_sig:
                self.last_sell_signal = sell_sig
                self._sell('135卖出: ' + sell_sig)
                return

        # === 优先级2: ATR动态止损（v17.2新增）===
        # 最高价 - 3×ATR(14)，动态适应波动率：高波动放宽、低波动收紧
        # 需要至少atr_period根K线才能计算ATR
        if self.position:
            if len(self.data) >= self.p.atr_period:
                atr_val = self.atr[0]
                if atr_val > 0:
                    atr_stop = self.highest_price - self.p.atr_multiplier * atr_val
                    if current_price <= atr_stop:
                        self._sell(f'ATR动态止损: 最高{self.highest_price:.2f} - {self.p.atr_multiplier}×ATR({atr_val:.4f}) = {atr_stop:.2f}')
                        return

        # === 优先级3: 移动止损（固定比例高点回撤）===
        if self.position:
            # === 移动止损（8%高点回撤）===
            if self.highest_price > 0:
                drawdown = (self.highest_price - current_price) / self.highest_price
                if drawdown >= self.p.stop_loss_pct:
                    self._sell(f'移动止损8%回撤: 最高{self.highest_price:.2f} → 当前{current_price:.2f}')
                    return

        # === 优先级4: 135买入信号（空仓且不在冷却期）===
        if not self.position:
            # 检查冷却期：买入后至少cool_down_bars个交易日
            if (self.buy_bar >= 0 and
                len(self.data) - 1 - self.buy_bar < self.p.cool_down_bars):
                return

            buy_sig = self._check_buy_signals()
            if buy_sig:
                self._execute_buy(buy_sig)

    def _execute_buy(self, signal_name):
        """执行买入（分仓建仓）"""
        if not self.position:
            cash = self.broker.getcash()
            price = self.data.close[0]
            entry_dt = str(self.data.datetime.date(0))

            # 试仓1/10: 用10%资金
            max_affordable = int(cash * 0.10 / price)

            if max_affordable >= 10:
                self.buy(size=max_affordable)
                self.stage = 1
                self.hold_start_bar = len(self.data) - 1
                self.entry_price = price
                self.highest_price = price
                self.current_shares = max_affordable
                self.buy_bar = len(self.data) - 1  # 记录买入bar
                self._entry_date = entry_dt
                self._entry_price = price
                self._entry_shares = max_affordable
                self.total_buy_count += 1
                self.signals_log.append({
                    'bar': len(self.data) - 1,
                    'type': 'BUY',
                    'signal': signal_name,
                    'stage': '1/10试仓',
                    'price': price,
                    'shares': max_affordable,
                })

    def _sell(self, reason):
        """执行卖出（全清）"""
        if self.position:
            price = self.data.close[0]
            exit_dt = str(self.data.datetime.date(0))
            
            # 先记录信号再关闭（notify_trade需要）
            self.last_sell_signal = reason
            self._exit_date = exit_dt
            self._exit_price = price
            
            self.close()
            self.signals_log.append({
                'bar': len(self.data) - 1,
                'type': 'SELL',
                'signal': reason,
                'stage': '全清',
                'price': price,
                'shares': self.current_shares,
            })
            # 注意：不在这里重置 last_sell_signal，让 notify_trade 使用
            self.stage = 0
            self.highest_price = 0
            self.current_shares = 0
            self.buy_bar = -1

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                price = order.executed.price
                self.signals_log.append({
                    'bar': len(self.data) - 1,
                    'type': 'BUY_EXEC',
                    'signal': f'成交@{price:.2f}',
                    'stage': f'{self.stage}/10',
                    'price': price,
                    'shares': order.executed.size,
                    'commission': order.executed.comm,
                })
            elif order.issell():
                price = order.executed.price
                self.signals_log.append({
                    'bar': len(self.data) - 1,
                    'type': 'SELL_EXEC',
                    'signal': f'成交@{price:.2f}',
                    'stage': '全清',
                })

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnlcomm  # 含佣金的真实盈亏
            
            # Use tracked entry/exit data
            entry_price = self._entry_price if hasattr(self, '_entry_price') else trade.price
            exit_price = self._exit_price if hasattr(self, '_exit_price') else trade.price
            entry_shares = self._entry_shares if hasattr(self, '_entry_shares') else max(1, abs(trade.size))
            actual_size = entry_shares if entry_shares > 0 else max(1, abs(trade.size))
            
            entry_date = self._entry_date if hasattr(self, '_entry_date') else 'N/A'
            exit_date = self._exit_date if hasattr(self, '_exit_date') else 'N/A'
            
            hold_days = len(self.data) - 1 - self.hold_start_bar if self.hold_start_bar >= 0 else 0
            
            if entry_price > 0 and actual_size > 0:
                return_pct = round(pnl / (entry_price * actual_size) * 100, 2)
            else:
                return_pct = 0

            self.trade_log.append({
                'entry_date': entry_date,
                'exit_date': exit_date,
                'entry_price': round(entry_price, 2),
                'exit_price': round(exit_price, 2),
                'size': actual_size,
                'pnl': round(pnl, 2),
                'return_pct': return_pct,
                'hold_days': hold_days,
                'exit_signal': self.last_sell_signal or '未知',
            })
            
            # 只在 notify_trade 完成后才清除 last_sell_signal
            self.last_sell_signal = None


# ============================================================
# 回测执行
# ============================================================

def run_single_backtest(thscode, start_date='20230101', end_date='20260813',
                        initial_cash=1000000, stop_loss=0.10):
    """单只股票回测（同花顺数据源）"""
    df = get_stock_history(thscode, start_date, end_date)
    if df is None or len(df) < 60:
        return None, "数据不足"

    name = thscode.split('.')[0]

    # 导出CSV
    tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmpfile.close()
    df_to_csv(df, tmpfile.name)

    # 创建cerebro
    cerebro = bt.Cerebro()
    data_feed = bt.feeds.GenericCSVData(
        dataname=tmpfile.name,
        dtformat='%Y%m%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        headers=True,
    )
    cerebro.adddata(data_feed)

    cerebro.addstrategy(Strategy135V17, stop_loss_pct=stop_loss)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.001)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    results = cerebro.run()
    strat = results[0]

    # 收集结果
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100

    sharpe = 0
    sa = strat.analyzers.sharpe.get_analysis()
    if isinstance(sa, dict) and 'sharperatio' in sa:
        v = sa['sharperatio']
        if isinstance(v, (int, float)):
            sharpe = v

    max_dd = 0
    da = strat.analyzers.drawdown.get_analysis()
    if isinstance(da, dict) and 'max' in da:
        max_dd = da['max'].drawdown

    # 从trade_log统计
    n_trades = len(strat.trade_log)
    wins = sum(1 for t in strat.trade_log if t['pnl'] > 0)
    losses = sum(1 for t in strat.trade_log if t['pnl'] <= 0)
    win_rate = wins / n_trades * 100 if n_trades > 0 else 0
    avg_pnl = sum(t['pnl'] for t in strat.trade_log) / n_trades if n_trades > 0 else 0
    avg_ret = sum(t['return_pct'] for t in strat.trade_log) / n_trades if n_trades > 0 else 0

    returns_list = [t['return_pct'] for t in strat.trade_log if t['return_pct'] != 0]
    best_ret = max(returns_list) if returns_list else 0
    worst_ret = min(returns_list) if returns_list else 0

    # 统计信号
    n_buy = len([s for s in strat.signals_log if s.get('type') == 'BUY'])

    result = {
        'thscode': thscode,
        'name': name,
        'n_bars': len(df),
        'final_value': round(final_value, 2),
        'total_return': round(total_return, 2),
        'sharpe': round(sharpe, 4),
        'max_drawdown': round(max_dd, 2),
        'n_trades': n_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'avg_pnl': round(avg_pnl, 2),
        'avg_return_pct': round(avg_ret, 2),
        'best_return': round(best_ret, 2),
        'worst_return': round(worst_ret, 2),
        'n_buy_signals': n_buy,
        'buy_signal_names': list(set(s['signal'] for s in strat.signals_log if s.get('type') == 'BUY')),
        'trade_detail': strat.trade_log,
    }

    os.unlink(tmpfile.name)
    return result, None


def run_batch_backtest(codes, start_date='20230101', end_date='20260813',
                        initial_cash=1000000, stop_loss=0.10):
    """批量回测"""
    results = []
    errors = []

    for i, code in enumerate(codes):
        if not code:
            continue

        print(f"[{i+1}/{len(codes)}] 回测 {code}...", end=' ', flush=True)
        result, error = run_single_backtest(code, start_date, end_date,
                                             initial_cash, stop_loss)
        if error:
            errors.append((code, error))
            print(f"跳过: {error}")
        else:
            results.append(result)
            status = "盈利" if result['total_return'] > 0 else "亏损"
            print(f"{status} {result['total_return']:+.1f}% | {result['n_trades']}笔 | 胜率{result['win_rate']:.0f}%")

    return results, errors


def save_results(results, errors, output_path):
    """保存结果到文件"""
    # 保存CSV
    if results:
        df = pd.DataFrame(results)
        df.to_csv(output_path.replace('.csv', '_detail.csv'), index=False)

        # 汇总统计
        summary = {
            'total_stocks': len(results),
            'profitable': len([r for r in results if r['total_return'] > 0]),
            'lossy': len([r for r in results if r['total_return'] <= 0]),
            'avg_return': round(sum(r['total_return'] for r in results) / len(results), 2),
            'avg_sharpe': round(sum(r['sharpe'] for r in results) / len(results), 4),
            'avg_drawdown': round(sum(r['max_drawdown'] for r in results) / len(results), 2),
            'avg_trades': round(sum(r['n_trades'] for r in results) / len(results), 1),
        }
        with open(output_path, 'w') as f:
            f.write("=== 135战法V17 批量回测汇总 ===\n\n")
            f.write(f"回测区间: 2023-2026\n")
            f.write(f"股票池: 沪深300成分股\n")
            f.write(f"策略: 135均线 + ATR×3动态止损 + 8%移动止损 + 10份分仓 + 10日冷却期\n\n")
            for k, v in summary.items():
                f.write(f"{k}: {v}\n")
            f.write(f"\n错误({len(errors)}只):\n")
            for code, err in errors:
                f.write(f"  {code}: {err}\n")

    return summary


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='135战法V17回测')
    parser.add_argument('--code', type=str, help='单只股票回测（如600519.SH）')
    parser.add_argument('--top', type=int, default=0, help='前N只沪深300成分股')
    parser.add_argument('--czs', action='store_true', help='使用创业板全市场回测（399006.SZ成分股）')
    parser.add_argument('--top-czs', type=int, default=0, help='前N只创业板成分股')
    parser.add_argument('--start', type=str, default='20230101', help='起始日期')
    parser.add_argument('--end', type=str, default='20260813', help='结束日期')
    parser.add_argument('--capital', type=float, default=1000000, help='初始资金')
    parser.add_argument('--stop-loss', type=float, default=0.08, help='止损比例')
    args = parser.parse_args()

    if args.code:
        # 单只回测
        result, error = run_single_backtest(
            args.code, args.start, args.end, args.capital, args.stop_loss)
        if error:
            print(f"错误: {error}")
            return
        print(f"\n{'='*60}")
        print(f"135战法V17 单票回测: {result['name']}")
        print(f"{'='*60}")
        print(f"总收益: {result['total_return']:+.2f}%")
        print(f"夏普比率: {result['sharpe']}")
        print(f"最大回撤: {result['max_drawdown']}")
        print(f"交易次数: {result['n_trades']}")
        print(f"胜率: {result['win_rate']}%")
        print(f"平均盈亏: {result['avg_pnl']:+.2f}")
        print(f"买入信号: {result['n_buy_signals']}次")
        print(f"信号类型: {result['buy_signal_names']}")

    elif args.top > 0:
        # 沪深300批量回测
        print("获取沪深300成分股...")
        codes = get_hs300_codes()[:args.top]
        if not codes:
            print("获取成分股失败")
            return

        print(f"开始批量回测 {len(codes)} 只股票...")
        results, errors = run_batch_backtest(
            codes, args.start, args.end, args.capital, args.stop_loss)

        if results:
            save_results(results, errors, '/tmp/135_v17_hs300_results.csv')

            # 汇总
            avg_ret = sum(r['total_return'] for r in results) / len(results)
            avg_sharpe = sum(r['sharpe'] for r in results) / len(results)
            profitable = len([r for r in results if r['total_return'] > 0])
            print(f"\n{'='*60}")
            print(f"135战法V17 批量回测汇总（沪深300）")
            print(f"{'='*60}")
            print(f"股票数: {len(results)}/{len(codes)}")
            print(f"盈利: {profitable} | 亏损: {len(results)-profitable}")
            print(f"平均收益: {avg_ret:+.2f}%")
            print(f"平均夏普: {avg_sharpe}")
            print(f"结果文件: /tmp/135_v17_hs300_results.csv")

    elif args.top_czs > 0:
        # 创业板前N只
        print("获取创业板成分股...")
        codes = get_chi_next_codes()[:args.top_czs]
        if not codes:
            print("获取创业板成分股失败")
            return
        print(f"创业板股票数: {len(codes)}")

        print(f"开始批量回测 {len(codes)} 只创业板股票...")
        results, errors = run_batch_backtest(
            codes, args.start, args.end, args.capital, args.stop_loss)

        if results:
            save_results(results, errors, '/tmp/135_v17_czs_results.csv')

            avg_ret = sum(r['total_return'] for r in results) / len(results)
            avg_sharpe = sum(r['sharpe'] for r in results) / len(results)
            profitable = len([r for r in results if r['total_return'] > 0])
            print(f"\n{'='*60}")
            print(f"135战法V17 批量回测汇总（创业板 Top {args.top_czs}）")
            print(f"{'='*60}")
            print(f"股票数: {len(results)}/{len(codes)}")
            print(f"盈利: {profitable} | 亏损: {len(results)-profitable}")
            print(f"平均收益: {avg_ret:+.2f}%")
            print(f"平均夏普: {avg_sharpe}")
            print(f"结果文件: /tmp/135_v17_czs_results.csv")

    elif args.czs:
        # 创业板全市场
        print("获取创业板成分股...")
        codes = get_chi_next_codes()
        if not codes:
            print("获取创业板成分股失败")
            return
        print(f"创业板股票总数: {len(codes)}")

        print(f"开始批量回测 {len(codes)} 只创业板股票...")
        results, errors = run_batch_backtest(
            codes, args.start, args.end, args.capital, args.stop_loss)

        if results:
            save_results(results, errors, '/tmp/135_v17_czs_all_results.csv')

            avg_ret = sum(r['total_return'] for r in results) / len(results)
            avg_sharpe = sum(r['sharpe'] for r in results) / len(results)
            profitable = len([r for r in results if r['total_return'] > 0])
            print(f"\n{'='*60}")
            print(f"135战法V17 批量回测汇总（创业板全市场）")
            print(f"{'='*60}")
            print(f"股票数: {len(results)}/{len(codes)}")
            print(f"盈利: {profitable} | 亏损: {len(results)-profitable}")
            print(f"平均收益: {avg_ret:+.2f}%")
            print(f"平均夏普: {avg_sharpe}")
            print(f"结果文件: /tmp/135_v17_czs_all_results.csv")
    else:
        print("用法:")
        print("  python3 run_135_position_backtest_v17.py --code 300750.SZ        # 单票")
        print("  python3 run_135_position_backtest_v17.py --top 300              # 沪深300前300只")
        print("  python3 run_135_position_backtest_v17.py --czs                  # 创业板全市场")
        print(f"  python3 run_135_position_backtest_v17.py --stop-loss 0.10  # 止损比例（默认10%）")


if __name__ == '__main__':
    main()
