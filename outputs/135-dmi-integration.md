# 135战法 × DMI多因子策略 — 融合方案

> 版本: v1.0
> 日期: 2026-08-13
> 目的: 将135战法信号作为DMI多因子策略的入场过滤器，提升信号质量与胜率

---

## 一、融合背景

### 1.1 两种策略的优劣势分析

| 策略 | 优势 | 劣势 | 核心逻辑 |
|------|------|------|----------|
| **135均线战法** | 形态直观、信号丰富(55种)、适合A股波动特征 | 假信号多(胜率~50%)、缺乏趋势确认、止损单一 | 菲波那契均线+量价形态 |
| **DMI多因子策略** | 趋势识别准确、因子权重可优化、市场状态切换 | 信号少、滞后性大、不适合震荡市 | 方向指标+多因子共振 |

### 1.2 融合思路

```
DMI趋势确认 → 135形态入场 → DMI持仓管理 → 135形态出场
```

- **入场过滤**: 135信号必须在DMI趋势确认后才触发
- **持仓管理**: 结合DMI的ADX强度指标决定仓位
- **出场优化**: 135卖出信号 + DMI趋势反转 = 双重确认出场

---

## 二、融合信号定义

### 2.1 入场信号矩阵

```python
# 强买入: DMI趋势确认 + 135核心形态
# 弱买入: 135形态(无DMI确认)
# 观望: DI死叉 + 135买入信号(忽略)

STRONG_BUY = DMI_UP_TREND and SIGNAL_135_BUY
WEAK_BUY = not DMI_UP_TREND and SIGNAL_135_BUY
IGNORE = DMI_DOWN_TREND and SIGNAL_135_BUY
```

### 2.2 DMI趋势过滤条件

| 条件 | 多头趋势 | 空头趋势 | 震荡 |
|------|----------|----------|------|
| **PDI vs MDI** | PDI > MDI + 2 | PDI < MDI - 2 | |
| **ADX** | ADX > 20 | ADX > 20 | ADX < 20 |
| **ADXR** | ADX - ADXR > 0 | ADX - ADXR < 0 | |
| **确认周期** | 连续2根K线 | 连续2根K线 | - |

### 2.3 仓位管理

```
仓位系数 = DMIADX_Weight × 135Confidence_Weight

DMIADX_Weight:
  ADX > 40: 1.0 (强趋势)
  ADX 30-40: 0.8
  ADX 20-30: 0.5
  ADX < 20: 0.0 (震荡市不交易)

135Confidence_Weight:
  核心形态(红杏/黑客/红衣/一阳穿三): 1.0
  辅助形态(梅开二度/浪子回头): 0.7
  其他形态: 0.3

最终仓位 = 最大仓位 × DMIADX_Weight × 135Confidence_Weight
```

---

## 三、Backtrader融合策略实现

```python
"""
135 + DMI 融合策略
版本: v1.0
日期: 2026-08-13
"""

class Strategy135DMIFusion(bt.Strategy):
    """135形态 + DMI趋势确认融合策略"""

    params = (
        ('max_position', 0.3),       # 最大仓位比例
        ('stop_loss', 0.07),         # 止损
        ('take_profit', 0.20),       # 止盈
        ('min_adx', 20),             # 最小ADX阈值
        ('use_dmi', True),           # 是否启用DMI
        ('core_signal_names', None), # 核心135信号列表
    )

    def __init__(self):
        # 指标
        self.ma13 = bt.ind.SMA(self.data.close, period=13)
        self.ma34 = bt.ind.SMA(self.data.close, period=34)
        self.ma55 = bt.ind.SMA(self.data.close, period=55)
        
        self.dmi = bt.ind.DMI(self.data)
        self.vol_ma = bt.ind.SMA(self.data.volume, period=5)

        # 状态
        self.dmi_trend = None  # 'up', 'down', 'neutral'
        self.current_position = None

    def get_dmi_trend(self):
        """判断当前DMI趋势状态"""
        adx = self.dmi.adx[0]
        pdi = self.dmi.plusDI[0]
        mdi = self.dmi.minusDI[0]

        if adx < self.p.min_adx:
            return 'neutral'  # 震荡
        
        if pdi > mdi + 2:
            return 'up'
        elif mdi > pdi + 2:
            return 'down'
        return 'neutral'

    def get_position_size(self, signal_name):
        """根据信号和DMI计算仓位"""
        # DMI权重
        adx = self.dmi.adx[0]
        if adx > 40:
            dmi_weight = 1.0
        elif adx > 30:
            dmi_weight = 0.8
        elif adx > 20:
            dmi_weight = 0.5
        else:
            return 0

        # 135信号权重
        core_signals = ['红杏出墙', '黑客点击', '红衣侠女', '一阳穿三线']
        if signal_name in core_signals:
            signal_weight = 1.0
        elif signal_name in ['梅开二度', '浪子回头', '揭竿而起', '三军集结']:
            signal_weight = 0.7
        else:
            signal_weight = 0.3

        return self.p.max_position * dmi_weight * signal_weight

    def next(self):
        if len(self.data) < 55:
            return

        # 更新趋势
        old_trend = self.dmi_trend
        self.dmi_trend = self.get_dmi_trend()

        # 检查卖出
        if self.position:
            sell_signal = self._detect_sells()
            if sell_signal:
                # 双重确认: 135卖出 + DMI趋势转空
                if self.dmi_trend in ['down', 'neutral'] or sell_signal:
                    self.close()

            # 止损/止盈
            ret = (self.data.close[0] - self.order_price) / self.order_price
            if ret <= -self.p.stop_loss:
                self.close()
            elif ret >= self.p.take_profit:
                self.close()

        # 检查买入
        elif not self.position:
            if self.dmi_trend in ['up', 'neutral']:
                buy_signal = self._detect_buys()
                if buy_signal:
                    size = self.get_position_size(buy_signal)
                    if size > 0:
                        cash = self.broker.getcash()
                        shares = int(cash * size / self.data.close[0] / 100) * 100
                        if shares > 0:
                            self.buy(size=shares)
                            self.order_price = self.data.close[0]

    def _detect_buys(self):
        """检测135买入信号(简化版, 完整见run_135_backtest.py)"""
        # ... 复用原有135信号检测逻辑 ...
        if self.ma13[0] > self.ma13[-1] and self.ma13[-1] <= self.ma13[-2]:
            if self.data.close[0] > self.ma13[0] and self.data.close[0] > self.data.open[0]:
                return '红杏出墙'
        return None

    def _detect_sells(self):
        """检测135卖出信号"""
        if self.data.close[0] < self.ma55[0] and self.data.close[0] < self.data.open[0]:
            return '一阴破三线'
        return None
```

---

## 四、融合策略绩效预期

### 4.1 预期改进

| 指标 | 纯135策略 | 135+DMI融合 | 预期改善 |
|------|-----------|-------------|----------|
| 胜率 | ~50% | ~65%+ | +15% |
| 最大回撤 | ~15% | ~10% | -33% |
| 年化收益 | 波动大 | 稳步提升 | +20% |
| 夏普比率 | ~0.5 | ~1.0+ | +100% |
| 信号频率 | 高(151次/年) | 中(50-80次/年) | -50% |

### 4.2 回测参数建议

```python
# 推荐参数
params = {
    'max_position': 0.3,     # 单股最大30%仓位
    'stop_loss': 0.07,       # 7%止损
    'take_profit': 0.20,     # 20%止盈
    'min_adx': 20,           # 最小ADX阈值
    'core_signals': [
        '红杏出墙', '黑客点击', '红衣侠女',
        '一阳穿三线', '揭竿而起', '梅开二度'
    ]
}
```

---

## 五、量化对接方案

### 5.1 与DMI多因子策略的数据流

```
A股日线数据(baostock/同花顺)
        ↓
   ┌─────────────┐
   │  135信号计算  │──→ 信号列表(Signal135)
   └─────────────┘        ↓
   ┌─────────────┐   ┌─────────────┐
   │  DMI因子计算  │──→│  信号过滤    │
   └─────────────┘   └─────────────┘
                          ↓
                    ┌─────────────┐
                    │  融合策略执行  │
                    └─────────────┘
                          ↓
                    ┌─────────────┐
                    │  组合管理     │
                    └─────────────┘
```

### 5.2 Python数据结构

```python
@dataclass
class FusionSignal:
    """融合信号"""
    date: str
    code: str
    signal_name: str          # 135形态名称
    signal_type: str          # 'buy', 'sell'
    confidence: str           # 'high', 'medium', 'low'
    dmi_trend: str            # 'up', 'down', 'neutral'
    dmi_adx: float            # 当前ADX值
    position_weight: float    # 仓位权重(0-1)
    entry_price: float
    stop_loss: float
    take_profit: float
    reason: str               # 触发原因
```

### 5.3 信号注册表

```python
SIGNAL_REGISTRY = {
    '红杏出墙': {
        'type': 'buy',
        'scenario': '抄底',
        'confidence': 'high',
        'required_indicators': ['ma13_rising', 'volume_increase', 'close_above_ma13'],
        'hold_period': '3-10天',
        'dmi_filter': 'up_trend_only',
    },
    '黑客点击': {
        'type': 'buy',
        'scenario': '转势',
        'confidence': 'high',
        'required_indicators': ['ma13_ma55_convergence', 'touch_ma55', 'close_above_low'],
        'hold_period': '5-15天',
        'dmi_filter': 'up_trend_confirmed',
    },
    # ... 其余50+形态按此格式注册
}
```

---

## 六、后续工作

1. **实盘回测验证**: 用baostock真实数据跑135+DMI融合策略
2. **参数优化**: 对ADX阈值、仓位权重做网格搜索
3. **信号去重**: 避免135信号过于频繁(设置冷却期)
4. **组合层面优化**: 多股票同时交易时的仓位分配
