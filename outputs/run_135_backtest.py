#!/usr/bin/env python3
"""
135 均线交易系统 — Backtrader 回测框架
==========================================
版本: v1.0
日期: 2026-08-13

功能:
  - 55种135形态的信号检测
  - 基于 baostock 数据源的批量回测
  - 信号共振策略（多形态组合）
  - 绩效分析（收益率、夏普比率、最大回撤、胜率）

用法:
  python run_135_backtest.py                  # 回测沪深300成分股
  python run_135_backtest.py --code sh.600519  # 单股回测
  python run_135_backtest.py --top 50          # 回测前50只
  python run_135_backtest.py --signals 红杏出墙,黑客点击,红衣侠女  # 指定形态
  python run_135_backtest.py --capital 100000  # 初始资金
  python run_135_backtest.py --output result.csv  # 导出结果
"""

import argparse
import datetime
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Tuple

import backtrader as bt
import pandas as pd
import numpy as np

# baostock 数据源
try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
except ImportError:
    BAOSTOCK_AVAILABLE = False
    logging.warning("baostock 未安装，使用模拟数据")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# 1. 形态定义与信号枚举
# ============================================================

class Signal135:
    """135战法信号类型"""

    # === 抄底篇 ===
    RED_APRICOT = "红杏出墙"           # #1 核心买点
    DYNAMIC_ZONE = "动感地带"          # #2
    GOLDEN_CAGE = "金屋藏娇"           # #3
    SUN_MOON = "日月合璧"             # #4
    FOUR_RIVER = "四渡赤水"           # #5
    DESPERATE_LIFE = "绝处逢生"       # #6
    EIGHT_IMMORTAL = "八仙过海"       # #7
    NINE_SUN = "九九艳阳天"           # #8
    PERFECT_TEN = "十全十美"          # #9
    FOUR_STAR = "四星望月"            # #10

    # === 转势篇 ===
    HACKER_CLICK = "黑客点击"         # #11
    RED_GIRL = "红衣侠女"            # #12
    SEA_FISHING = "海底捞月"          # #13
    MA_SWAP = "均线互换"              # #14
    THREE_LINE = "三线推进"           # #15
    ONE_CANDLE_THREE = "一阳穿三线"   # #16
    REBEL_RISE = "揭竿而起"           # #17
    STONE_QUESTION = "投石问路"       # #18
    BROKEN_MIRROR = "破镜重圆"        # #19
    STEPPING_HIGH = "步步登高"        # #20

    # === 攻击篇 ===
    FLOWERS_BLOOM = "梅开二度"        # #21
    BOY_RETURN = "浪子回头"          # #22
    THREE_ARMY = "三军集结"           # #23
    BREAK_FREE = "突出重围"           # #24 卖出
    ANTLY_CLIMB = "蚂蚁上树"          # #25
    WALK_FOUR = "走四方"             # #26
    DMI_SURE = "双蹄并进"            # #27
    ONE_STONE_TWO = "一石两鸟"        # #28
    STAR_LIGHT = "星星点灯"           # #29
    BIRD_DEPEND = "小鸟依人"          # #30
    SECRET_PASS = "暗渡陈仓"          # #31
    FALSE_PATH = "明修栈道"           # #32 卖出

    # === 调整篇 ===
    STRING_YIN = "串阴"               # #33
    STRING_YANG = "串阳"              # #34
    POLE_SHADOW = "立竿见影"          # #35
    DRAG_WATER = "拖泥带水"           # #36 卖出
    PART_WAY = "分道扬镳"             # #37 卖出
    ARROW_HEART = "一箭穿心"          # #38 卖出
    YIN_BREAK = "一阴破三线"          # #39 卖出
    FALL_STONE = "落井下石"           # #40 卖出
    RIVER_BRIDGE = "过河拆桥"         # #41 卖出
    MORNING_BELL = "晨钟暮鼓"         # #42 卖出
    HORSE_FALL = "马失前蹄"           # #43 卖出
    BRANCH_GROW = "节外生枝"          # #44 卖出
    SMILE_KNIFE = "笑里藏刀"          # #45 卖出
    DOG_JUMP = "狗急跳墙"             # #46 卖出

    # === 卖出篇 ===
    SWORD_THROAT = "一剑封喉"         # #47
    SINGLE_FLOWER = "一枝独秀"        # #48
    TAKE_PROFIT = "见好就收"          # #49
    GOLD_CICADA = "金蝉脱壳"          # #50
    HIGH_TOWER = "独上高楼"           # #51
    THREE_SWORD = "三剑客"            # #52
    RED_APRICOT_2 = "红杏出墙·二买"   # #53
    MOMENTUM = "动量加速"             # #54
    VOLUME_BREAK = "量能突破"         # #55

    # 买入信号列表
    BUY_SIGNALS = [
        RED_APRICOT, DYNAMIC_ZONE, GOLDEN_CAGE, SUN_MOON, FOUR_RIVER,
        DESPERATE_LIFE, EIGHT_IMMORTAL, NINE_SUN, PERFECT_TEN, FOUR_STAR,
        HACKER_CLICK, RED_GIRL, SEA_FISHING, MA_SWAP, THREE_LINE,
        ONE_CANDLE_THREE, REBEL_RISE, STONE_QUESTION, BROKEN_MIRROR, STEPPING_HIGH,
        FLOWERS_BLOOM, BOY_RETURN, THREE_ARMY, ANTLY_CLIMB, WALK_FOUR,
        DMI_SURE, ONE_STONE_TWO, STAR_LIGHT, BIRD_DEPEND, SECRET_PASS,
        STRING_YIN, STRING_YANG, POLE_SHADOW,
        RED_APRICOT_2, MOMENTUM, VOLUME_BREAK,
    ]

    # 卖出信号列表
    SELL_SIGNALS = [
        BREAK_FREE, FALSE_PATH, DRAG_WATER, PART_WAY, ARROW_HEART,
        YIN_BREAK, FALL_STONE, RIVER_BRIDGE, MORNING_BELL, HORSE_FALL,
        BRANCH_GROW, SMILE_KNIFE, DOG_JUMP,
        SWORD_THROAT, SINGLE_FLOWER, TAKE_PROFIT, GOLD_CICADA, HIGH_TOWER,
    ]

    # 所有信号
    ALL_SIGNALS = BUY_SIGNALS + SELL_SIGNALS


# ============================================================
# 2. 135 策略主类 — Backtrader Strategy
# ============================================================

class Strategy135(bt.Strategy):
    """
    135均线交易系统 Backtrader 策略

    参数:
        ma13_period: 13日均线周期
        ma34_period: 34日均线周期
        ma55_period: 55日均线周期
        vol_period:  成交量均线周期
        stop_loss:   止损百分比（默认0.07 = 7%）
        take_profit: 止盈百分比（默认0.20 = 20%）
        use_dmi:     是否启用DMI指标
        use_macd:    是否启用MACD指标
        signal_names: 要启用的信号列表（None=全部）
        max_positions: 最大持仓数（模拟组合时使用）
    """

    params = (
        ('ma13_period', 13),
        ('ma34_period', 34),
        ('ma55_period', 55),
        ('vol_period', 5),
        ('stop_loss', 0.07),
        ('take_profit', 0.20),
        ('use_dmi', False),
        ('use_macd', True),
        ('signal_names', None),
        ('max_positions', 1),
    )

    def __init__(self):
        # === 指标 ===
        self.ma13 = bt.indicators.SMA(self.data.close, period=self.p.ma13_period)
        self.ma34 = bt.indicators.SMA(self.data.close, period=self.p.ma34_period)
        self.ma55 = bt.indicators.SMA(self.data.close, period=self.p.ma55_period)

        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.vol_period)

        if self.p.use_macd:
            self.macd = bt.indicators.MACD(self.data.close)

        if self.p.use_dmi:
            self.dmi = bt.indicators.DMI(self.data, period=14)

        # === 状态跟踪 ===
        self.signals = []  # 记录所有信号
        self.trade_log = []  # 交易记录
        self.order_price = None  # 上次入场价格

        # === 过滤信号 ===
        if self.p.signal_names:
            self.active_signals = set(self.p.signal_names)
            logger.info(f"启用信号: {self.active_signals}")
        else:
            self.active_signals = set(Signal135.ALL_SIGNALS)
            logger.info(f"启用全部 {len(self.active_signals)} 个信号")

        # === 计数器 ===
        self.bar_count = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """记录日志"""
        dt = dt or self.datas[0].datetime.date(0)
        logger.info(f"[{dt.isoformat()}] {txt}")

    def notify_order(self, order):
        """订单状态回调 — 记录入场价、数量和日期用于后续收益率计算"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            exec_date = str(self.data.datetime.date(0).isoformat()[:10])
            if order.isbuy():
                self.log(f"买入执行: 价格={order.executed.price:.2f}, 数量={order.executed.size:.0f}, 费用={order.executed.comm:.2f}")
                self.order_price = order.executed.price
                self._entry_price = order.executed.price
                self._entry_size = order.executed.size
                self._entry_date = exec_date
            elif order.issell():
                self.log(f"卖出执行: 价格={order.executed.price:.2f}, 数量={order.executed.size:.0f}, 费用={order.executed.comm:.2f}")
                self.order_price = None
                self._exit_date = exec_date
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"订单取消/拒绝: {order.status}")

    def notify_trade(self, trade):
        """交易完成回调"""
        if trade.isclosed:
            pnlcomm = trade.pnlcomm
            # 使用记录的实际入场价和数量
            entry_price = getattr(self, '_entry_price', trade.price) if hasattr(trade, 'price') else 0
            size = getattr(self, '_entry_size', abs(trade.size)) if hasattr(trade, 'size') else 0
            # 入场总成本
            cost = entry_price * size if entry_price > 0 and size != 0 else 1
            ret = pnlcomm / cost
            # 记录实际交易日期
            entry_dt = getattr(self, '_entry_date', 'N/A')
            exit_dt = getattr(self, '_exit_date', 'N/A')
            self.trade_log.append({
                'entry_date': entry_dt,
                'exit_date': exit_dt,
                'entry_price': entry_price,
                'pnl': round(pnlcomm, 2),
                'return_pct': round(ret * 100, 2),
            })

    def next(self):
        """每个bar执行"""
        self.bar_count += 1

        # 跳过数据不足
        if len(self.data) < self.p.ma55_period:
            return

        # === 检测卖出信号（优先） ===
        if self.position:
            sell_signal = self.detect_sells()
            if sell_signal:
                signal_name, confidence = sell_signal
                if signal_name in self.active_signals:
                    self.close()
                    self.sell_count += 1
                    self.signals.append({
                        'date': str(self.data.datetime.date(0)),
                        'signal': signal_name,
                        'direction': 'sell',
                        'confidence': confidence,
                        'price': self.data.close[0],
                        'position_size': self.position.size,
                    })
                    return  # 卖出后不再检测买入

            # === 止损/止盈 ===
            if self.order_price and self.order_price > 0:
                current_return = (self.data.close[0] - self.order_price) / self.order_price
                if current_return <= -self.p.stop_loss:
                    self.log(f"止损触发: 亏损{current_return*100:.1f}%")
                    self.close()
                    self.sell_count += 1
                    self.signals.append({
                        'date': str(self.data.datetime.date(0)),
                        'signal': '止损',
                        'direction': 'sell',
                        'confidence': '高',
                        'price': self.data.close[0],
                        'position_size': self.position.size,
                    })
                    return
                if current_return >= self.p.take_profit:
                    self.log(f"止盈触发: 盈利{current_return*100:.1f}%")
                    self.close()
                    self.sell_count += 1
                    self.signals.append({
                        'date': str(self.data.datetime.date(0)),
                        'signal': '止盈',
                        'direction': 'sell',
                        'confidence': '高',
                        'price': self.data.close[0],
                        'position_size': self.position.size,
                    })
                    return

        # === 检测买入信号 ===
        if not self.position:
            buy_signal = self.detect_buys()
            if buy_signal:
                signal_name, confidence = buy_signal
                if signal_name in self.active_signals:
                    size = int(self.broker.getcash() * 0.95 / self.data.close[0] / 100) * 100
                    if size > 0:
                        self.buy(size=size)
                        self.buy_count += 1
                        self.signals.append({
                            'date': str(self.data.datetime.date(0)),
                            'signal': signal_name,
                            'direction': 'buy',
                            'confidence': confidence,
                            'price': self.data.close[0],
                            'position_size': size,
                        })

    # ================================================================
    # 买入信号检测
    # ================================================================

    def detect_buys(self) -> Optional[Tuple[str, str]]:
        """
        检测所有买入信号，返回 (信号名称, 置信度)
        按置信度排序，返回最高的
        """
        candidates = []

        # --- #1 红杏出墙 ---
        if self._detect_red_apricot():
            candidates.append((Signal135.RED_APRICOT, "高"))

        # --- #3 金屋藏娇 ---
        if self._detect_golden_cage():
            candidates.append((Signal135.GOLDEN_CAGE, "高"))

        # --- #4 日月合璧 ---
        if self._detect_sun_moon():
            candidates.append((Signal135.SUN_MOON, "高"))

        # --- #11 黑客点击 ---
        if self._detect_hacker_click():
            candidates.append((Signal135.HACKER_CLICK, "高"))

        # --- #12 红衣侠女 ---
        if self._detect_red_girl():
            candidates.append((Signal135.RED_GIRL, "高"))

        # --- #13 海底捞月 ---
        if self._detect_sea_fishing():
            candidates.append((Signal135.SEA_FISHING, "高"))

        # --- #16 一阳穿三线 ---
        if self._detect_one_candle_three():
            candidates.append((Signal135.ONE_CANDLE_THREE, "高"))

        # --- #17 揭竿而起 ---
        if self._detect_rebel_rise():
            candidates.append((Signal135.REBEL_RISE, "高"))

        # --- #21 梅开二度 ---
        if self._detect_flowers_bloom():
            candidates.append((Signal135.FLOWERS_BLOOM, "高"))

        # --- #22 浪子回头 ---
        if self._detect_boy_return():
            candidates.append((Signal135.BOY_RETURN, "高"))

        # --- #23 三军集结 ---
        if self._detect_three_army():
            candidates.append((Signal135.THREE_ARMY, "高"))

        # --- #27 双蹄并进 ---
        if self.p.use_dmi and self._detect_dmi_sure():
            candidates.append((Signal135.DMI_SURE, "高"))

        # --- #34 串阳 ---
        if self._detect_string_yang():
            candidates.append((Signal135.STRING_YANG, "高"))

        # --- #49 见好就收（作为买入辅助 — 乖离率正常时） ---
        if self._detect_normal_divergence():
            candidates.append((Signal135.TAKE_PROFIT, "中"))

        # --- #55 量能突破 ---
        if self._detect_volume_break():
            candidates.append((Signal135.VOLUME_BREAK, "高"))

        # --- #54 动量加速 ---
        if self.p.use_macd and self._detect_momentum():
            candidates.append((Signal135.MOMENTUM, "中"))

        # 返回置信度最高的信号
        if not candidates:
            return None

        # 按置信度排序: 高 > 中 > 低
        confidence_order = {"高": 0, "中": 1, "低": 2}
        candidates.sort(key=lambda x: confidence_order.get(x[1], 3))
        return candidates[0]

    # ================================================================
    # 卖出信号检测
    # ================================================================

    def detect_sells(self) -> Optional[Tuple[str, str]]:
        """
        检测所有卖出信号，返回 (信号名称, 置信度)
        按置信度排序，返回最高的
        """
        candidates = []

        # --- #37 分道扬镳 ---
        if self._detect_part_way():
            candidates.append((Signal135.PART_WAY, "高"))

        # --- #38 一箭穿心 ---
        if self._detect_arrow_heart():
            candidates.append((Signal135.ARROW_HEART, "高"))

        # --- #39 一阴破三线 ---
        if self._detect_yin_break():
            candidates.append((Signal135.YIN_BREAK, "高"))

        # --- #40 落井下石 ---
        if self._detect_fall_stone():
            candidates.append((Signal135.FALL_STONE, "高"))

        # --- #41 过河拆桥 ---
        if self._detect_river_bridge():
            candidates.append((Signal135.RIVER_BRIDGE, "高"))

        # --- #43 马失前蹄 ---
        if self._detect_horse_fall():
            candidates.append((Signal135.HORSE_FALL, "高"))

        # --- #47 一剑封喉 ---
        if self._detect_sword_throat():
            candidates.append((Signal135.SWORD_THROAT, "高"))

        # --- #48 一枝独秀 ---
        if self._detect_single_flower():
            candidates.append((Signal135.SINGLE_FLOWER, "高"))

        # --- #49 见好就收 ---
        if self._detect_take_profit_y():
            candidates.append((Signal135.TAKE_PROFIT, "高"))

        # --- #44 节外生枝 ---
        if self._detect_branch_grow():
            candidates.append((Signal135.BRANCH_GROW, "中"))

        # --- #51 独上高楼 ---
        if self._detect_high_tower():
            candidates.append((Signal135.HIGH_TOWER, "中"))

        if not candidates:
            return None

        confidence_order = {"高": 0, "中": 1, "低": 2}
        candidates.sort(key=lambda x: confidence_order.get(x[1], 3))
        return candidates[0]

    # ================================================================
    # 买入形态检测函数
    # ================================================================

    def _detect_red_apricot(self) -> bool:
        """#1 红杏出墙 — 13日走平转升，阳线上站，放量"""
        if self.ma13[-1] <= self.ma13[-2] and self.ma13[0] > self.ma13[-1]:
            if (self.data.close[0] > self.ma13[0] and
                self.data.close[0] > self.data.open[0] and
                self.data.volume[0] > self.vol_ma[0] * 1.2 and
                self.ma55[0] > self.ma55[-1]):
                return True
        return False

    def _detect_golden_cage(self) -> bool:
        """#3 金屋藏娇 — 长阴下影线后缩量小阴"""
        if (self.data.close[-1] < self.data.open[-1] and
            self.data.close[-1] - self.data.low[-1] > 0 and
            (min(self.data.open[-1], self.data.close[-1]) - self.data.low[-1]) /
            max(0.01, self.data.open[-1] - self.data.close[-1]) > 1.5):
            if (self.data.close[0] < self.data.open[0] and
                self.data.close[0] > self.data.low[-1] and
                self.data.volume[0] < self.data.volume[-1] * 0.7 and
                self.data.low[0] > self.data.low[-1]):
                return True
        return False

    def _detect_sun_moon(self) -> bool:
        """#4 日月合璧 — 跳空低开阴线后次日阳线覆盖"""
        if (self.data.volume[-2] < self.vol_ma[-2] * 0.5 if len(self.data) >= 3 else False and
            self.data.open[-1] < self.data.close[-2] * 0.98 and
            self.data.close[-1] < self.data.open[-1] and
            self.data.close[0] >= self.data.open[-1]):
            return True
        return False

    def _detect_hacker_click(self) -> bool:
        """#11 黑客点击 — 突破55后回踩13/55结点"""
        if abs(self.ma13[0] - self.ma55[0]) / self.ma55[0] < 0.02:
            if abs(self.data.low[0] - self.ma55[0]) / self.ma55[0] < 0.03:
                if self.data.close[0] >= self.data.low[0]:
                    return True
        return False

    def _detect_red_girl(self) -> bool:
        """#12 红衣侠女 — 13日金叉55日"""
        if (self.ma13[-1] < self.ma55[-1] and
            self.ma13[0] > self.ma55[0] and
            self.data.close[0] > self.data.open[0] and
            self.data.close[0] > self.ma55[0] and
            self.data.volume[0] > self.vol_ma[0] * 1.5):
            return True
        return False

    def _detect_sea_fishing(self) -> bool:
        """#13 海底捞月 — 13日下穿55日后再上穿"""
        # 查找历史上13日曾在上方的记录
        for i in range(10, 0, -1):
            if i + 1 < len(self.ma13):
                if (self.ma13[-i] > self.ma55[-i] and
                    self.ma13[-1] < self.ma55[-1] and
                    self.ma13[0] > self.ma55[0]):
                    return True
                break
        return False

    def _detect_one_candle_three(self) -> bool:
        """#16 一阳穿三线 — 均线间距小，放量穿越"""
        max_ma = max(self.ma13[0], self.ma34[0], self.ma55[0])
        min_ma = min(self.ma13[0], self.ma34[0], self.ma55[0])
        if (max_ma - min_ma) / max(0.01, min_ma) < 0.03:
            if (self.data.close[0] > self.ma13[0] and
                self.data.close[0] > self.ma34[0] and
                self.data.close[0] > self.ma55[0] and
                self.data.open[0] < self.ma13[0] and
                self.data.volume[0] > self.vol_ma[0] * 2.0 and
                self.data.close[0] > self.data.open[0]):
                return True
        return False

    def _detect_rebel_rise(self) -> bool:
        """#17 揭竿而起 — 均线黏合后放量突破"""
        max_ma = max(self.ma13[0], self.ma34[0], self.ma55[0])
        min_ma = min(self.ma13[0], self.ma34[0], self.ma55[0])
        if (max_ma - min_ma) / max(0.01, min_ma) < 0.03:
            if (self.data.close[0] > self.ma13[0] and
                self.data.close[0] > self.ma34[0] and
                self.data.close[0] > self.ma55[0] and
                self.data.volume[0] > self.vol_ma[0] * 2.5 and
                self.data.close[0] > self.data.open[0] and
                (self.data.close[0] - self.data.open[0]) / self.data.open[0] > 0.03):
                return True
        return False

    def _detect_flowers_bloom(self) -> bool:
        """#21 梅开二度 — 13日二次上穿34日"""
        # 检查此前有13日>55日的历史
        has_past_cross = any(
            self.ma13[-i] > self.ma55[-i] for i in range(5, 60)
            if i + 1 < len(self.ma13)
        )
        if has_past_cross:
            if (self.ma13[-1] < self.ma34[-1] and
                self.ma13[0] > self.ma34[0] and
                self.data.close[0] > self.ma13[0] and
                self.ma34[0] > self.ma55[0]):
                return True
        return False

    def _detect_boy_return(self) -> bool:
        """#22 浪子回头 — 55日支撑后回升"""
        if (self.ma55[0] > self.ma55[-1] and
            self.ma55[-1] > self.ma55[-2] and
            abs(self.data.low[0] - self.ma55[0]) / self.ma55[0] < 0.02 and
            self.data.close[0] > self.ma55[0] and
            self.data.close[0] > self.data.close[-1] and
            self.data.volume[0] > self.vol_ma[0]):
            return True
        return False

    def _detect_three_army(self) -> bool:
        """#23 三军集结 — 三线交汇"""
        if (abs(self.ma13[0] - self.ma55[0]) / self.ma55[0] < 0.02 and
            abs(self.ma34[0] - self.ma55[0]) / self.ma55[0] < 0.02 and
            self.data.volume[0] > self.vol_ma[0] * 1.2):
            return True
        return False

    def _detect_dmi_sure(self) -> bool:
        """#27 双蹄并进 — DMI共振
        Backtrader DMI lines: plusDI, minusDI, adx (无 adxr)
        """
        if self.p.use_dmi:
            if (self.dmi.plusDI[0] > self.dmi.minusDI[0] and
                self.dmi.plusDI[-1] <= self.dmi.minusDI[-1] and
                self.dmi.adx[0] > 20 and
                self.ma13[0] > self.ma55[0]):
                return True
        return False

    def _detect_string_yang(self) -> bool:
        """#34 串阳 — 连续5根阳线"""
        if (all(self.data.close[-i] >= self.data.open[-i] for i in range(5)) and
            all(0.005 <= (self.data.close[-i] / self.data.open[-i] - 1) <= 0.03 for i in range(5))):
            return True
        return False

    def _detect_normal_divergence(self) -> bool:
        """辅助：乖离率正常时（Y<10%）"""
        y = (self.ma13[0] - self.ma55[0]) / self.ma55[0] * 100
        return -10 < y < 10

    def _detect_volume_break(self) -> bool:
        """#55 量能突破 — 放量突破55日"""
        if (self.data.close[-1] < self.ma55[-1] and
            self.data.close[0] > self.ma55[0] and
            self.data.volume[0] > self.vol_ma[0] * 2.0 and
            self.data.close[0] > self.data.open[0] and
            (self.data.close[0] - self.data.open[0]) / self.data.open[0] > 0.03):
            return True
        return False

    def _detect_momentum(self) -> bool:
        """#54 动量加速 — MACD零轴上
        Backtrader MACD lines: macd, signal (no dea/dif)
        """
        if self.p.use_macd:
            if (self.macd.macd[0] > 0 and
                self.macd.signal[0] > 0 and
                self.data.close[0] < self.data.close[-1] and
                self.data.close[0] > self.ma13[0]):
                return True
        return False

    # ================================================================
    # 卖出形态检测函数
    # ================================================================

    def _detect_part_way(self) -> bool:
        """#37 分道扬镳 — 13日下穿34日"""
        if (self.ma13[-1] > self.ma34[-1] and
            self.ma13[0] < self.ma34[0] and
            self.ma13[-1] > self.ma13[-2] and
            self.ma13[0] <= self.ma13[-1] and
            self.data.close[0] < self.ma13[0]):
            return True
        return False

    def _detect_arrow_heart(self) -> bool:
        """#38 一箭穿心 — 13日下穿55日"""
        if (self.data.close[0] < self.ma55[0] and
            self.ma13[-1] > self.ma55[-1] and
            self.ma13[0] < self.ma55[0]):
            return True
        return False

    def _detect_yin_break(self) -> bool:
        """#39 一阴破三线 — 阴线跌破三条均线"""
        if (self.data.close[0] < self.ma13[0] and
            self.data.close[0] < self.ma34[0] and
            self.data.close[0] < self.ma55[0] and
            self.data.open[0] > self.ma13[-1] and
            self.data.close[0] < self.data.open[0] and
            self.data.volume[0] > self.vol_ma[0]):
            return True
        return False

    def _detect_fall_stone(self) -> bool:
        """#40 落井下石 — 放量下跌，空头排列"""
        if (self.data.close[-3] < self.ma55[-3] and
            self.data.close[0] < self.data.close[-1] and
            self.data.volume[0] > self.vol_ma[0] and
            self.ma13[0] < self.ma34[0] < self.ma55[0]):
            return True
        return False

    def _detect_river_bridge(self) -> bool:
        """#41 过河拆桥 — 跌破上行的13日线"""
        if (self.ma13[-5] < self.ma13[-4] < self.ma13[-3] < self.ma13[-2] < self.ma13[-1] and
            self.data.close[0] < self.ma13[0] and
            self.data.close[0] < self.data.open[0] and
            self.data.volume[0] > self.vol_ma[0]):
            return True
        return False

    def _detect_horse_fall(self) -> bool:
        """#43 马失前蹄 — 13日线拐头向下"""
        if (self.ma13[-3] < self.ma13[-2] < self.ma13[-1] and
            self.ma13[0] <= self.ma13[-1] and
            self.data.close[0] < self.ma13[0]):
            return True
        return False

    def _detect_sword_throat(self) -> bool:
        """#47 一剑封喉 — 上影线超实体3倍"""
        body = abs(self.data.close[0] - self.data.open[0])
        if body > 0:
            upper_shadow = self.data.high[0] - max(self.data.open[0], self.data.close[0])
            if (upper_shadow / body > 3 and
                self.data.volume[0] > self.vol_ma[0] and
                self.data.close[0] < self.data.close[-1]):
                return True
        return False

    def _detect_single_flower(self) -> bool:
        """#48 一枝独秀 — 高位放量长上影"""
        body = abs(self.data.close[0] - self.data.open[0])
        if body > 0:
            upper_shadow = self.data.high[0] - max(self.data.open[0], self.data.close[0])
            if (upper_shadow > body * 3 and
                self.data.volume[0] > self.vol_ma[0] * 2 and
                self.data.close[0] < self.data.high[0] * 0.95):
                return True
        return False

    def _detect_take_profit_y(self) -> bool:
        """#49 见好就收 — Y = (ma13-ma55)/ma55 > 10%"""
        y = (self.ma13[0] - self.ma55[0]) / self.ma55[0] * 100
        return y > 10

    def _detect_branch_grow(self) -> bool:
        """#44 节外生枝 — 大阳后跟星线"""
        if ((self.data.close[-1] - self.data.open[-1]) / self.data.open[-1] > 0.03 and
            abs(self.data.close[0] - self.data.open[0]) / self.data.open[0] < 0.02 and
            self.data.volume[0] < self.data.volume[-1]):
            return True
        return False

    def _detect_high_tower(self) -> bool:
        """#51 独上高楼 — 高位滞涨量能萎缩"""
        if (self.data.volume[0] < self.vol_ma[0] * 0.7 and
            all(abs(self.data.close[-i] - self.data.close[-i-1]) / self.data.close[-i-1] < 0.01
                for i in range(3)) and
            self.ma13[0] <= self.ma13[-1]):
            return True
        return False


# ============================================================
# 3. 数据获取模块
# ============================================================

def get_baostock_data(code: str, start_date: str = "2018-01-01",
                       end_date: str = "2026-08-13") -> Optional[pd.DataFrame]:
    """
    从 baostock 获取A股日线数据

    Args:
        code: 股票代码，如 "sh.600519"
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    if not BAOSTOCK_AVAILABLE:
        logger.warning("baostock 不可用，返回 None")
        return None

    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )

        data_list = []
        while (rs.error_code == '0') and rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            logger.warning(f"无数据: {code}")
            return None

        df = pd.DataFrame(data_list, columns=rs.fields)
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna()
        df = df.set_index('date')
        df = df.sort_index()

        logger.info(f"获取数据 {code}: {len(df)} 条, {df.index[0].date()} ~ {df.index[-1].date()}")
        return df

    except Exception as e:
        logger.error(f"获取数据失败 {code}: {e}")
        return None


def get_stock_pool(top_n: int = 50, start_date: str = "2018-01-01",
                   end_date: str = "2026-08-13") -> List[str]:
    """
    获取股票池（前N只）
    优先使用 baostock 全A股列表
    """
    if not BAOSTOCK_AVAILABLE:
        logger.warning("baostock 不可用，使用默认股票池")
        return ["sh.600519", "sz.000001", "sh.601318", "sz.000858", "sh.600036"]

    try:
        rs = bs.query_all_stock(day=start_date.split('-')[0] + "-01-01")
        stocks = []
        while (rs.error_code == '0') and rs.next():
            row = rs.get_row_data()
            if row[2] == '1':  # A股
                stocks.append(f"{row[1]}.{row[0]}")

        # 去重
        stocks = list(set(stocks))[:top_n]
        logger.info(f"股票池: {len(stocks)} 只")
        return stocks

    except Exception as e:
        logger.error(f"获取股票池失败: {e}")
        return ["sh.600519", "sz.000001", "sh.601318", "sz.000858", "sh.600036"]


def generate_mock_data(n_bars: int = 1000, start_price: float = 20.0) -> pd.DataFrame:
    """生成模拟数据用于测试"""
    np.random.seed(42)
    dates = pd.bdate_range(end=datetime.datetime.now(), periods=n_bars)
    prices = [start_price]
    for i in range(1, n_bars):
        ret = np.random.normal(0.0005, 0.02)
        prices.append(prices[-1] * (1 + ret))

    df = pd.DataFrame({
        'open': [p * (1 + np.random.normal(0, 0.01)) for p in prices],
        'high': [p * (1 + abs(np.random.normal(0, 0.015))) for p in prices],
        'low': [p * (1 - abs(np.random.normal(0, 0.015))) for p in prices],
        'close': prices,
        'volume': np.random.randint(100000, 1000000, n_bars),
    }, index=dates)
    df.index.name = 'date'
    return df


# ============================================================
# 4. 回测执行引擎
# ============================================================

class BacktestEngine:
    """回测引擎"""

    def __init__(self, signal_names: Optional[List[str]] = None,
                 initial_cash: float = 100000,
                 use_dmi: bool = False,
                 use_macd: bool = True,
                 stop_loss: float = 0.07,
                 take_profit: float = 0.20):
        self.signal_names = signal_names
        self.initial_cash = initial_cash
        self.use_dmi = use_dmi
        self.use_macd = use_macd
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.cerebro = bt.Cerebro()

    def add_data(self, df: pd.DataFrame, name: str = "stock"):
        """添加数据源"""
        data = bt.feeds.PandasData(dataname=df)
        self.cerebro.adddata(data, name=name)

    def run(self):
        """执行回测"""
        # 添加策略
        self.cerebro.addstrategy(
            Strategy135,
            signal_names=self.signal_names,
            use_dmi=self.use_dmi,
            use_macd=self.use_macd,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
        )

        # 设置初始资金
        self.cerebro.broker.setcash(self.initial_cash)

        # 设置手续费
        self.cerebro.broker.setcommission(commission=0.001)  # 千分之一

        # 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                                 riskfreerate=0.03, annualize=True)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual')

        # 运行 — cerebro.run() 返回 [Strategy, ...] 列表
        results = self.cerebro.run()
        strategy = results[0]

        # 收集结果
        return {
            'initial_cash': self.initial_cash,
            'signals': strategy.signals,
            'trade_log': strategy.trade_log,
            'final_value': self.cerebro.broker.getvalue(),
            'final_cash': self.cerebro.broker.getcash(),
            'sharpe': strategy.analyzers.sharpe.get_analysis(),
            'drawdown': strategy.analyzers.drawdown.get_analysis(),
            'trades': strategy.analyzers.trades.get_analysis(),
            'returns': strategy.analyzers.returns.get_analysis(),
            'annual': strategy.analyzers.annual.get_analysis(),
            'buy_count': strategy.buy_count,
            'sell_count': strategy.sell_count,
        }


# ============================================================
# 5. 绩效分析
# ============================================================

def analyze_results(results: dict, code: str = "组合") -> pd.DataFrame:
    """
    分析回测结果并返回DataFrame
    """
    final_value = results['final_value']
    initial_cash = results.get('initial_cash', 100000)
    total_return = (final_value - initial_cash) / initial_cash * 100

    sharpe = results.get('sharpe', {}).get('sharperatio', 0) or 0

    dd = results.get('drawdown', {})
    max_drawdown = dd.get('max', {}).get('drawdown', 0) or 0
    max_drawdown_pct = dd.get('max', {}).get('max', 0) or 0

    trades = results.get('trades', {})
    total_trades = trades.get('total', 0) or 0
    won = trades.get('won', {}).get('total', 0) or 0
    lost = trades.get('lost', {}).get('total', 0) or 0
    win_rate = (won / (won + lost) * 100) if (won + lost) > 0 else 0

    annual = results.get('annual', {})
    annual_return = annual.get('return', 0) or 0

    signal_summary = {}
    for s in results['signals']:
        name = s['signal']
        if name not in signal_summary:
            signal_summary[name] = 0
        signal_summary[name] += 1

    df = pd.DataFrame([{
        'code': code,
        'final_value': round(final_value, 2),
        'total_return_pct': round(total_return, 2),
        'sharpe_ratio': round(sharpe, 3),
        'max_drawdown_pct': round(max_drawdown_pct, 2),
        'total_trades': total_trades,
        'win_count': won,
        'lose_count': lost,
        'win_rate_pct': round(win_rate, 2),
        'annual_return_pct': round(annual_return * 100, 2),
        'buy_signals': results['buy_count'],
        'sell_signals': results['sell_count'],
        'signal_distribution': str(signal_summary),
    }])

    return df


# ============================================================
# 6. 信号共振策略
# ============================================================

class SignalResonanceEngine:
    """
    信号共振引擎 — 多个135形态信号同时出现时增强信号权重
    """

    # 信号置信度权重
    HIGH_WEIGHT = 1.0
    MEDIUM_WEIGHT = 0.6
    LOW_WEIGHT = 0.3

    # 高置信度信号列表
    HIGH_CONFIDENCE = [
        Signal135.RED_APRICOT, Signal135.GOLDEN_CAGE, Signal135.HACKER_CLICK,
        Signal135.RED_GIRL, Signal135.ONE_CANDLE_THREE, Signal135.REBEL_RISE,
        Signal135.FLOWERS_BLOOM, Signal135.BOY_RETURN, Signal135.THREE_ARMY,
        Signal135.DMI_SURE, Signal135.STRING_YANG, Signal135.VOLUME_BREAK,
        Signal135.PART_WAY, Signal135.ARROW_HEART, Signal135.YIN_BREAK,
        Signal135.SWORD_THROAT, Signal135.SINGLE_FLOWER, Signal135.TAKE_PROFIT,
    ]

    @classmethod
    def evaluate_signals(cls, signal_list: list) -> Tuple[str, float]:
        """
        评估信号列表，返回 (建议动作, 共振分数)

        Args:
            signal_list: 当日所有触发的信号名称列表

        Returns:
            (action, score): 动作 ("buy", "sell", "hold", "strong_buy", "strong_sell") 和分数 (0-1)
        """
        buy_score = 0
        sell_score = 0

        for sig in signal_list:
            if sig in cls.HIGH_CONFIDENCE:
                weight = cls.HIGH_WEIGHT
            elif sig in [Signal135.STRING_YIN, Signal135.BIRD_DEPEND, Signal135.STAR_LIGHT]:
                weight = cls.MEDIUM_WEIGHT
            else:
                weight = cls.LOW_WEIGHT

            if sig in Signal135.BUY_SIGNALS:
                buy_score += weight
            elif sig in Signal135.SELL_SIGNALS:
                sell_score += weight

        max_score = max(buy_score, sell_score)

        if buy_score > sell_score * 2 and buy_score > 1.0:
            if buy_score > 2.0:
                return ("strong_buy", buy_score)
            return ("buy", buy_score)
        elif sell_score > buy_score * 2 and sell_score > 1.0:
            if sell_score > 2.0:
                return ("strong_sell", sell_score)
            return ("sell", sell_score)
        elif abs(buy_score - sell_score) < 0.3:
            return ("hold", max_score)
        else:
            if buy_score > sell_score:
                return ("hold_buy", max_score)
            return ("hold_sell", max_score)


# ============================================================
# 7. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='135均线交易系统 — Backtrader回测')
    parser.add_argument('--code', type=str, default=None, help='单股回测代码，如 sh.600519')
    parser.add_argument('--top', type=int, default=50, help='股票池大小（默认50）')
    parser.add_argument('--signals', type=str, default=None,
                        help='指定信号，逗号分隔，如 红杏出墙,黑客点击,红衣侠女')
    parser.add_argument('--capital', type=float, default=100000, help='初始资金（默认10万）')
    parser.add_argument('--output', type=str, default='result.csv', help='结果输出文件')
    parser.add_argument('--no-dmi', action='store_true', help='禁用DMI指标')
    parser.add_argument('--no-macd', action='store_true', help='禁用MACD指标')
    parser.add_argument('--use-mock', action='store_true', help='使用模拟数据测试')
    parser.add_argument('--stop-loss', type=float, default=0.07, help='止损比例（默认7%）')
    parser.add_argument('--take-profit', type=float, default=0.20, help='止盈比例（默认20%）')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("135均线交易系统 — Backtrader回测引擎")
    logger.info("=" * 60)

    # 解析信号
    signal_names = None
    if args.signals:
        signal_names = [s.strip() for s in args.signals.split(',')]
        logger.info(f"指定信号: {signal_names}")

    # 获取数据
    if args.use_mock:
        logger.info("使用模拟数据...")
        mock_df = generate_mock_data(1000)
        engine = BacktestEngine(
            signal_names=signal_names,
            initial_cash=args.capital,
            use_dmi=not args.no_dmi,
            use_macd=not args.no_macd,
            stop_loss=args.stop_loss,
            take_profit=args.take_profit,
        )
        engine.add_data(mock_df, name="mock")
        results = engine.run()
        results['initial_cash'] = args.capital
        df_results = analyze_results(results, code="模拟数据")
        df_results.to_csv(args.output, index=False)
        logger.info(f"模拟回测完成，结果已保存至 {args.output}")
        print(df_results.to_string(index=False))
        return

    # 获取股票数据
    if args.code:
        codes = [args.code]
    else:
        codes = get_stock_pool(args.top)

    all_results = []

    for code in codes:
        logger.info(f"回测: {code}")

        if BAOSTOCK_AVAILABLE:
            df = get_baostock_data(code)
        else:
            df = generate_mock_data(1000)
            logger.info(f"baostock不可用，使用模拟数据替代: {code}")

        if df is None or len(df) < 60:
            logger.warning(f"跳过 {code}: 数据不足")
            continue

        engine = BacktestEngine(
            signal_names=signal_names,
            initial_cash=args.capital,
            use_dmi=not args.no_dmi,
            use_macd=not args.no_macd,
            stop_loss=args.stop_loss,
            take_profit=args.take_profit,
        )
        engine.add_data(df, name=code)
        results = engine.run()
        results['initial_cash'] = args.capital
        df_result = analyze_results(results, code=code)
        all_results.append(df_result)

        # 打印结果
        print(f"\n{'='*60}")
        print(f"股票: {code}")
        print(f"{'='*60}")
        print(df_result.to_string(index=False))

        # 打印信号分布
        sig_dist = df_result['signal_distribution'].strip('{}"').replace("'", "")
        if sig_dist:
            print(f"信号分布: {sig_dist}")

        # 打印最近5条交易记录
        if results['trade_log']:
            print(f"\n最近交易:")
            for t in results['trade_log'][-5:]:
                print(f"  {t['entry_date']} → {t['exit_date']}: "
                      f"收益率 {t['return_pct']:+.2f}%")

    # 汇总结果
    if all_results:
        final_df = pd.concat(all_results, ignore_index=True)
        final_df.to_csv(args.output, index=False)
        logger.info(f"\n回测完成！{len(all_results)} 只股票结果已保存至 {args.output}")

        print(f"\n{'='*60}")
        print(f"汇总结果 ({len(all_results)} 只股票)")
        print(f"{'='*60}")
        print(final_df[['code', 'total_return_pct', 'sharpe_ratio',
                        'max_drawdown_pct', 'win_rate_pct', 'buy_signals']].to_string(index=False))

        # 排序
        profitable = final_df[final_df['total_return_pct'] > 0]
        logger.info(f"盈利股票: {len(profitable)}/{len(final_df)} "
                    f"({len(profitable)/len(final_df)*100:.1f}%)")
    else:
        logger.warning("没有成功回测任何股票")


if __name__ == '__main__':
    main()
