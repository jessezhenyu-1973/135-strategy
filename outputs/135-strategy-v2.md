# 135 战法 — 交易策略全集（完整版 v2.0）

> 基于宁俊明《135战法》原著 + 网络资料整理
> 整理日期：2026-08-13
> 版本：v2.0（55种形态全部量化条件完整）
> 量化调用约定：每个形态标注 type/scenario/confidence/indicators/timeframe/hold_period

---

## 一、策略分类总览

| 编号 | 策略名 | 类型 | 场景 | 置信度 | 持有期 | 所在篇 |
|------|--------|------|------|--------|--------|--------|
| **抄底篇 — 底部反转** |
| 1 | 红杏出墙 | buy | 底部反转 | 高 | 中线(5-20天) | 抄底 |
| 2 | 动感地带 | buy | 底部吸筹 | 中 | 中线(5-20天) | 抄底 |
| 3 | 金屋藏娇 | buy | 底部见底 | 高 | 短线(1-5天) | 抄底 |
| 4 | 日月合璧 | buy | 底部反转 | 高 | 短线(1-5天) | 抄底 |
| 5 | 四渡赤水 | buy | 底部筑底 | 高 | 中线(5-20天) | 抄底 |
| 6 | 绝处逢生 | buy | 底部反转 | 中 | 短线(1-5天) | 抄底 |
| 7 | 八仙过海 | buy | 底部转势 | 高 | 中线(5-20天) | 抄底 |
| 8 | 九九艳阳天 | buy | 底部拉升 | 高 | 中线(5-20天) | 抄底 |
| 9 | 十全十美 | buy | 底部转势 | 中 | 中线(5-20天) | 抄底 |
| 10 | 四星望月 | buy | 底部四阳 | 中 | 中线(5-20天) | 抄底 |
| **转势篇 — 趋势反转** |
| 11 | 黑客点击 | buy | 突破回踩 | 高 | 中线(5-20天) | 转势 |
| 12 | 红衣侠女 | buy | 均线金叉 | 高 | 中线(5-20天) | 转势 |
| 13 | 海底捞月 | buy | 均线回穿 | 高 | 中线(5-20天) | 转势 |
| 14 | 均线互换 | buy | 趋势确认 | 高 | 中长线(20天+) | 转势 |
| 15 | 三线推进 | buy | 底部突破 | 高 | 中长线(20天+) | 转势 |
| 16 | 一阳穿三线 | buy | 底部突破 | 高 | 中线(5-20天) | 转势 |
| 17 | 揭竿而起 | buy | 底部放量 | 高 | 中线(5-20天) | 转势 |
| 18 | 投石问路 | buy | 支撑确认 | 中 | 短线(1-5天) | 转势 |
| 19 | 破镜重圆 | buy | 突破回踩 | 中 | 短线(1-5天) | 转势 |
| 20 | 步步登高 | buy | 趋势延续 | 中 | 短线(1-5天) | 转势 |
| **攻击篇 — 上升趋势** |
| 21 | 梅开二度 | buy | 上升中继 | 高 | 短线(1-5天) | 攻击 |
| 22 | 浪子回头 | buy | 55日支撑 | 高 | 中线(5-20天) | 攻击 |
| 23 | 三军集结 | buy | 三线共振 | 高 | 短线(1-5天) | 攻击 |
| 24 | 突出重围 | sell | 高位派发 | 高 | — | 攻击 |
| 25 | 蚂蚁上树 | buy | 小阳推进 | 中 | 短线(1-5天) | 攻击 |
| 26 | 走四方 | buy | 温和洗盘 | 中 | 短线(1-5天) | 攻击 |
| 27 | 双蹄并进 | buy | DMI共振 | 高 | 中线(5-20天) | 攻击 |
| 28 | 一石两鸟 | buy | 一阳二阴 | 中 | 短线(1-5天) | 攻击 |
| 29 | 星星点灯 | buy | 放量攻击 | 中 | 短线(1-5天) | 攻击 |
| 30 | 小鸟依人 | buy | 缩量震仓 | 中 | 短线(1-5天) | 攻击 |
| 31 | 暗渡陈仓 | buy | 缩量阴线 | 中 | 短线(1-5天) | 攻击 |
| 32 | 明修栈道 | sell | 诱多陷阱 | 中 | — | 攻击 |
| **调整篇 — 洗盘/回调** |
| 33 | 串阴 | buy | 洗盘结束 | 中 | 短线(1-5天) | 调整 |
| 34 | 串阳 | buy | 强势整理 | 高 | 短线(1-5天) | 调整 |
| 35 | 立竿见影 | buy | 缩量回踩 | 中 | 短线(1-5天) | 调整 |
| 36 | 拖泥带水 | sell | 高位派发 | 中 | — | 调整 |
| 37 | 分道扬镳 | sell | 均线死叉 | 高 | — | 调整 |
| 38 | 一箭穿心 | sell | 均线死叉 | 高 | — | 调整 |
| 39 | 一阴破三线 | sell | 跌破均线 | 高 | — | 调整 |
| 40 | 落井下石 | sell | 加速下跌 | 高 | — | 调整 |
| 41 | 过河拆桥 | sell | 跌破13日 | 高 | — | 调整 |
| 42 | 晨钟暮鼓 | sell | 见顶信号 | 中 | — | 调整 |
| 43 | 马失前蹄 | sell | 趋势终止 | 高 | — | 调整 |
| 44 | 节外生枝 | sell | 调整信号 | 中 | — | 调整 |
| 45 | 笑里藏刀 | sell | 诱多后跌 | 中 | — | 调整 |
| 46 | 狗急跳墙 | sell | 高位缺口 | 中 | — | 调整 |
| **卖出篇 — 见顶/出货** |
| 47 | 一剑封喉 | sell | 见顶形态 | 高 | — | 卖出 |
| 48 | 一枝独秀 | sell | 高位见顶 | 高 | — | 卖出 |
| 49 | 见好就收 | sell | 乖离过大 | 高 | — | 卖出 |
| 50 | 金蝉脱壳 | sell | 高位洗盘 | 中 | — | 卖出 |
| 51 | 独上高楼 | sell | 高位滞涨 | 中 | — | 卖出 |
| 52 | 三剑客 | sell | 震仓结束 | 中 | 短线(1-5天) | 卖出 |
| 53 | 红杏出墙·二买 | buy | 二次确认 | 高 | 中线(5-20天) | 卖出 |
| 54 | 动量加速 | buy | MACD零轴上 | 中 | 短线(1-5天) | 卖出 |
| 55 | 量能突破 | buy | 放量突破55 | 高 | 中线(5-20天) | 卖出 |

---

## 二、抄底篇 — 底部反转策略（10种）

### #1 红杏出墙（核心买点）

```
【定义】空头排列末期，13日均线走平，股价站上13日线收阳。
【量化条件】
  C1: ma13[t] > ma13[t-1]  AND  ma13[t-1] <= ma13[t-2]  (13日走平转升)
  C2: close[t] > ma13[t]  AND  open[t] <= ma13[t]  (阳线上站)
  C3: ma55[t] > ma55[t-1]  (55日仍下行，空头未完全扭转)
  C4: volume[t] >= MA(volume, 5) * 1.2  (放量确认)
  C5: (ma13[t] - ma55[t]) / ma55[t] < 0.15  (未远离)
【操作】首次轻仓1-2成；指数配合半仓；跌破13日止损；34日上穿55日加仓
【参数】buy|bottom_reversal|高|ma13,ma34,ma55,volume|日线|中线
```

### #2 动感地带

```
【定义】长期下跌后底部小幅震荡，55日均线被拉直，13日均线翘头向上，底部抬升。
【量化条件】
  C1: ma13[t] > ma13[t-3]  (13日翘头)
  C2: ma55[t] - ma55[t-5] > 0  (55日开始走平转升)
  C3: close[t] > close[t-1]  (底部抬高)
  C4: volume[t] >= MA(volume, 10) * 1.1  (温和放量)
  C5: high[t] - low[t] < MA(high-low, 20) * 1.5  (振幅收窄)
【操作】密切关注，放量突破后介入
【参数】buy|bottom_accumulation|中|ma13,ma34,ma55,volume|日线|中线
```

### #3 金屋藏娇

```
【定义】长阴下影线后跟缩量小阴线，不创新低，见底形态。
【量化条件】
  C1: 前日长阴: open[t-1] > close[t-1] AND (open[t-1] - close[t-1]) > body_avg * 2
  C2: 前日下影: (min(open[t-1], close[t-1]) - low[t-1]) / max(1, open[t-1] - close[t-1]) > 1.5
  C3: 次日小阴: close[t] < open[t] AND close[t] > low[t-1]  (在长阴下影内)
  C4: volume[t] < volume[t-1] * 0.7  (缩量)
  C5: low[t] > low[t-1]  (不创新低)
【操作】典型见底，可重仓介入；止损：跌破最低点
【参数】buy|bottom_seen|高|ma13,ma34,ma55,volume|日线|短线
```

### #4 日月合璧

```
【定义】缩量下跌尾段跳空低开阴线，次日止跌回升阳线，两K线并排。
【量化条件】
  C1: volume[t-2] 连续3日递减至地量水平（< MA(volume,5) * 0.5）
  C2: 前日跳空: open[t-1] < close[t-2] * 0.98  (低开>2%)
  C3: 前日阴线: close[t-1] < open[t-1]
  C4: 次日阳线: close[t] >= open[t-1]  (覆盖前日)
  C5: ma13[t] - ma13[t-3] ≈ 0  (13日线走平)
【操作】轻仓摸索→次日确认半仓→站稳55日重仓
【参数】buy|bottom_reversal|高|ma13,ma34,ma55,volume|日线|短线
```

### #5 四渡赤水

```
【定义】反弹-回落反复4次，每次低点抬高、高点抬高，筑底完成。
【量化条件】
  C1: 存在4个波段，每波段2-10日
  C2: low[w1] < low[w2] < low[w3] < low[w4]  (低点抬高)
  C3: high[w1] < high[w2] < high[w3] < high[w4]  (高点抬高)
  C4: volume[wave4] 较前3波明显放大
【操作】第4次回落后介入；止损：跌破第4次低点
【参数】buy|bottom_building|高|ma13,ma34,ma55,volume|日线|中线
```

### #6 绝处逢生

```
【定义】趋势末期跳空低开，随即低开高走长阳线快速上攻，趋势反转标记。
【量化条件】
  C1: 前5日趋势: close[t-5] > close[t-1]  (前期下跌)
  C2: 跳空低开: open[t] < close[t-1] * 0.98
  C3: 大阳线: close[t] > open[t] AND (close[t] - open[t]) / open[t] > 0.03
  C4: close[t] > MA(close, 5)  (站上短期均线)
  C5: volume[t] > MA(volume, 5)  (放量)
【操作】当天盘中可低吸，形态确认后台重出击
【参数】buy|bottom_reversal|中|ma13,ma34,ma55,volume|日线|短线
```

### #7 八仙过海

```
【定义】长期横盘后持续8根小阳线（含星线），庄家限价买入尾声。
【量化条件】
  C1: 连续8根K线: close[t-k] >= open[t-k]  for k=0..7  (阳线或星线)
  C2: 每根涨幅0.5%-3%: 0.005 <= (close/open - 1) <= 0.03
  C3: volume温和放大: volume[t] > volume[t-7] AND volume[t] < MA(volume,20) * 2
  C4: 8日累计涨幅5%-15%
  C5: 均线开始胶合: abs(ma13-ma34)/ma34 < 0.03
【操作】第8根确认后介入；止损：跌破8根K线最低点
【参数】buy|bottom_transition|高|ma13,ma34,ma55,volume|日线|中线
```

### #8 九九艳阳天

```
【定义】连续9根小阳线，庄家限价买入痕迹，大幅拉升信号。
【量化条件】
  C1: 连续9根阳线: close[t-k] >= open[t-k] for k=0..8
  C2: 每根涨幅1%-4%
  C3: volume温和放大
  C4: ma13 由平转升
  C5: 前30日处于下跌或横盘状态
【操作】第9根确认后重仓介入；止损：跌破13日
【参数】buy|bottom_rally|高|ma13,ma34,ma55,volume|日线|中线
```

### #9 十全十美

```
【定义】持续10根阳线，底部转势信号。
【量化条件】
  C1: 连续10根阳线
  C2: 每根涨幅1%-5%
  C3: ma13 > ma13[t-10]
  C4: volume[t] >= MA(volume, 5)
【操作】确认介入，中线持有
【参数】buy|bottom_transition|中|ma13,ma34,ma55,volume|日线|中线
```

### #10 四星望月

```
【定义】底部四阳包裹一阴，大底信号。
【量化条件】
  C1: 四根阳线包裹一根阴线：阳-阳-阴-阳-阳（或类似排列）
  C2: 中间阴线实体较小，被前后阳线覆盖
  C3: 四根阳线累计涨幅 > 5%
  C4: volume 在阳线日放大
  C5: ma13 走平或向上
【操作】可抄大底；止损：跌破四阳最低价
【参数】buy|bottom_seen|中|ma13,ma34,ma55,volume|日线|中线
```

---

## 三、转势篇 — 趋势反转策略（10种）

### #11 黑客点击

```
【定义】突破55日后回踩，落在13/55日均线结点处，均线互换完成。
【量化条件】
  C1: 存在前期高点（N日最高）
  C2: 此前有突破55日线的记录
  C3: low[t] 接近 ma55[t]（误差 < 2%）
  C4: abs(ma13[t] - ma55[t]) / ma55[t] < 0.02  (均线结点)
  C5: close[t] 接近结点处
  C6: 34日均线已完成上穿55日（均线互换完成）
【操作】均线互换完成后重仓；放量上攻进场；涨20%后13日线走软先出局
【参数】buy|breakout_pullback|高|ma13,ma34,ma55,volume|日线|中线
```

### #12 红衣侠女

```
【定义】13日线上穿55日（金叉）之日，携量上攻。
【量化条件】
  C1: ma55[t-2] ≈ ma55[t-1] ≈ ma55[t]  (55日水平)
  C2: ma13[t-1] < ma55[t-1]  AND  ma13[t] > ma55[t]  (金叉)
  C3: close[t] > open[t]  (阳线)
  C4: close[t] > ma55[t]
  C5: volume[t] >= MA(volume, 5) * 1.5
【操作】立即上涨或调整后放量起涨，即将拉升标志
【参数】buy|ma_crossover|高|ma13,ma34,ma55,volume|日线|中线
```

### #13 海底捞月

```
【定义】13日下穿55日后再上穿55日，短期持续走高。
【量化条件】
  C1: ma13[t-k] > ma55[t-k]  (此前在上方)
  C2: ma13[t-1] < ma55[t-1]  (下穿)
  C3: ma13[t] > ma55[t]  (上穿回)
  C4: volume[t] 温和放大
  C5: 34日均线保持平行
【操作】新资金进场信号，短期持续走高
【参数】buy|ma_reversal|高|ma13,ma34,ma55,volume|日线|中线
```

### #14 均线互换

```
【定义】34日下穿55日后再上穿55日，标志股价走强。
【量化条件】
  C1: 此前有 ma34 > ma55 的历史
  C2: ma34[t-1] < ma55[t-1]  (下穿)
  C3: ma34[t] > ma55[t]  (上穿回)
  C4: volume[t] 放大
  C5: ma13 也向上
【操作】均线多头排列形成，后市一波上攻，中线持有
【参数】buy|trend_confirm|高|ma13,ma34,ma55,volume|日线|中长线
```

### #15 三线推进

```
【定义】底部胶合半年左右后，一阳穿三线或从三线上腾空而起。
【量化条件】
  C1: 均线胶合: abs(ma13-ma34)/ma34 < 0.02 AND abs(ma34-ma55)/ma55 < 0.02
  C2: 胶合时长: ma13 持续30日以上间距小
  C3: 突破: close[t] > ma13[t] AND close[t] > ma34[t] AND close[t] > ma55[t]
  C4: volume[t] >= MA(volume, 5) * 1.5
  C5: 前30日振幅 < 15%
【操作】庄家开始拉升标志，立即介入
【参数】buy|bottom_breakout|高|ma13,ma34,ma55,volume|日线|中长线
```

### #16 一阳穿三线

```
【定义】均线间距极小后，某天放量穿越所有三条均线。
【量化条件】
  C1: 均线间距极小: max(ma13,ma34,ma55) - min(ma13,ma34,ma55) < 3% * ma55
  C2: close[t] > ma13[t] AND close[t] > ma34[t] AND close[t] > ma55[t]
  C3: open[t] < ma13[t]  (从下方穿越)
  C4: volume[t] >= MA(volume, 5) * 2.0  (倍量)
  C5: close[t] / open[t] - 1 > 0.03  (大阳线)
【操作】难得的进场良机，庄家大反攻标志
【参数】buy|bottom_breakout|高|ma13,ma34,ma55,volume|日线|中线
```

### #17 揭竿而起

```
【定义】均线黏合后，某天从三线上腾空而起。
【量化条件】
  C1: 均线黏合: max(ma13,ma34,ma55) - min(ma13,ma34,ma55) < 3% * ma55
  C2: close[t] > ma13[t] AND close[t] > ma34[t] AND close[t] > ma55[t]
  C3: volume[t] >= MA(volume, 5) * 2.5
  C4: close[t] / open[t] - 1 > 0.03  (大阳线)
  C5: close[t] > MA(close, 20) * 1.05
【操作】庄家开始拉升标志，立即介入
【参数】buy|bottom_volume_break|高|ma13,ma34,ma55,volume|日线|中线
```

### #18 投石问路

```
【定义】股价缓步爬上34日顺势回落，在13/34日均线结点处获得双重支撑。
【量化条件】
  C1: ma13[t] ≈ ma34[t]  (双重支撑结点，误差 < 1%)
  C2: close[t] 接近结点（误差 < 3%）
  C3: ma13[t] > ma13[t-1]  (13日向上)
  C4: low[t] >= min(ma13[t], ma34[t])  (不跌破结点)
  C5: volume[t] 温和
【操作】支撑确认后跟进
【参数】buy|support_confirm|中|ma13,ma34,ma55,volume|日线|短线
```

### #19 破镜重圆

```
【定义】突破55日后回踩确认，再次站上55日线。
【量化条件】
  C1: 此前 close > ma55 有突破记录
  C2: low[t-3] 曾低于 ma55（回踩）
  C3: close[t] > ma55[t]  (重新站上)
  C4: volume[t] 温和放大
  C5: ma13 向上
【操作】突破确认信号，中线介入
【参数】buy|breakout_retest|中|ma13,ma34,ma55,volume|日线|短线
```

### #20 步步登高

```
【定义】连续小阳逐步抬高，趋势延续。
【量化条件】
  C1: close[t] > close[t-1] > close[t-2] > close[t-3]
  C2: close[t] > ma13[t] > ma34[t] > ma55[t]  (多头排列)
  C3: 每根涨幅1%-3%
  C4: volume[t] 温和
  C5: ma13[t] - ma13[t-1] > 0
【操作】趋势延续确认，短线持有
【参数】buy|trend_continuation|中|ma13,ma34,ma55,volume|日线|短线
```

---

## 四、攻击篇 — 上升趋势策略（12种）

### #21 梅开二度

```
【定义】13日上穿55后回落，13日二次上穿34日。
【量化条件】
  C1: 此前有 ma13 上穿 ma55 的历史
  C2: ma13[t-1] < ma34[t-1]  AND  ma13[t] > ma34[t]  (二次金叉)
  C3: close[t] > ma13[t]
  C4: volume[t] 温和
  C5: ma34[t] > ma55[t]  (34在55之上)
【操作】主力拉升在即，短期有可观上行空间，中线持有
【参数】buy|mid_rally|高|ma13,ma34,ma55,volume|日线|短线
```

### #22 浪子回头

```
【定义】上升趋势中股价回调至55日均线处获得支撑，重拾升势。
【量化条件】
  C1: ma55[t] 斜率向上（中长期均线向上）
  C2: low[t] 接近 ma55[t]（误差 < 2%）
  C3: close[t] > ma55[t]
  C4: close[t] > close[t-1]
  C5: volume[t] 温和放大
  C6: ma13[t] > ma34[t] > ma55[t]  (多头排列)
【操作】主力洗盘，55日强力支撑，中线持有
【参数】buy|ma55_support|高|ma13,ma34,ma55,volume|日线|中线
```

### #23 三军集结

```
【定义】13/34/55三均线同时向55日线靠拢交汇，市场共振。
【量化条件】
  C1: ma13 向上靠近 ma55
  C2: ma34 向下靠近 ma55
  C3: abs(ma13[t] - ma55[t]) < 2% * ma55[t]
  C4: abs(ma34[t] - ma55[t]) < 2% * ma55[t]
  C5: volume[t] 开始放大
  C6: 此前有拉升后回调的历史
【操作】市场共振，拉升在即，立即介入
【参数】buy|triple_convergence|高|ma13,ma34,ma55,volume|日线|短线
```

### #24 突出重围（卖出）

```
【定义】三均线打成死结后大涨，大跌信号。
【量化条件】
  C1: abs(ma13-ma34)/ma34 < 0.02 AND abs(ma34-ma55)/ma55 < 0.02
  C2: close[t] / close[t-5] - 1 > 0.05  (大涨)
  C3: volume[t] 放天量
  C4: close[t] = high[t] 或接近最高价
  C5: ma13[t] >= ma34[t] >= ma55[t]  (刚死结完就涨)
【操作】果断清仓，这是大跌信号
【参数】sell|top_warning|高|ma13,ma34,ma55,volume|日线|—
```

### #25 蚂蚁上树

```
【定义】13日线走平后，股价连续小阳缓步盘升送上55日线。
【量化条件】
  C1: ma13[t-5] ≈ ma13[t]  (13日走平)
  C2: close[t-k] > close[t-k-1] for k=0..4  (连续小阳)
  C3: 每根涨幅1%-3%
  C4: close[t] 接近 ma55[t] 或站上
  C5: volume[t] 温和
【操作】放量上攻时毫不犹豫跟进
【参数】buy|small_rally|中|ma13,ma34,ma55,volume|日线|短线
```

### #26 走四方

```
【定义】高开低走小阳推进，温和洗盘方法。
【量化条件】
  C1: close[t] >= open[t]  (收阳，尽管高开低走)
  C2: 连续3-5根这种K线
  C3: 每根振幅 < 3%
  C4: volume[t] 缩小或持平
  C5: close[t] 在13/34日均线上方
【操作】温和洗盘，时间短震幅小见效快，继续持有
【参数】buy|mild_wash|中|ma13,ma34,ma55,volume|日线|短线
```

### #27 双蹄并进

```
【定义】DMI的+DI上穿-DI（前蹄），ADX≈ADXR（后蹄），四蹄并拢。
【量化条件】
  C1: +DI[t] > -DI[t]  AND  +DI[t-1] <= -DI[t-1]  (+DI上穿-DI)
  C2: abs(ADX[t] - ADXR[t]) < 2  (后蹄并拢)
  C3: ADX[t] > 20  (趋势强度)
  C4: ma13[t] > ma55[t]  (均线多头)
【操作】DMI信号共振，中线持有
【参数】buy|dmi_resonance|高|ma13,ma34,ma55,dmi,dmi,dmi,volume|日线|中线
```

### #28 一石两鸟

```
【定义】上升趋势中"一阳二阴"震仓，行进中停顿。
【量化条件】
  C1: 阳线: close[t] > open[t] AND volume[t] 放大
  C2: 随后两日阴线: close[t+1] < open[t+1] AND close[t+2] < open[t+2]
  C3: 两日阴线实体小（涨幅<3%）
  C4: close[t+2] > low[t]  (不破阳线最低点)
  C5: volume 在阴线日缩小
【操作】震仓而非走软信号，继续持有
【参数】buy|shakeout|中|ma13,ma34,ma55,volume|日线|短线
```

### #29 星星点灯

```
【定义】大阳报收→次日高开高走留影小阳不破昨收，攻击补仓。
【量化条件】
  C1: 前日大阳: close[t-1] - open[t-1] > 3% * open[t-1]
  C2: 次日高开: open[t] > close[t-1]
  C3: 次日小阳/星线: 实体 < 2%
  C4: close[t] > close[t-1]  (不破昨收)
  C5: volume[t] 急剧放大
【操作】庄家攻击性补仓，非卖出信号
【参数】buy|aggressive_fill|中|ma13,ma34,ma55,volume|日线|短线
```

### #30 小鸟依人

```
【定义】巨量中阳后平开/低开收缩量小阴小阳，观察抛压。
【量化条件】
  C1: 前日大阳: close[t-1] - open[t-1] > 3% * open[t-1]
  C2: 前日放量: volume[t-1] > MA(volume, 5) * 2
  C3: 次日小阴小阳: abs(close[t]-open[t]) / open[t] < 0.02
  C4: volume[t] < volume[t-1] * 0.7
  C5: close[t] > ma13[t-1]
【操作】观察市抛压和跟风，次日可介入
【参数】buy|volume_shakeout|中|ma13,ma34,ma55,volume|日线|短线
```

### #31 暗渡陈仓

```
【定义】拉升途中缩量大阴线，次日或第三天止跌回升。
【量化条件】
  C1: 在上升趋势中: ma13斜率向上
  C2: 前日缩量阴线: close < open AND volume < MA(volume, 5)
  C3: 次日或第三天: close > open
  C4: close[t] > MA(close, 13)
  C5: volume[t+1或t+2] 恢复放大
【操作】庄家刻意打压洗盘，第二天止跌回升，新升浪开始
【参数】buy|volume_shadow|中|ma13,ma34,ma55,volume|日线|短线
```

### #32 明修栈道（卖出）

```
【定义】平台整理或一波拉升后突然加速上攻+巨量大阳线，诱多陷阱。
【量化条件】
  C1: 前3日横盘或缓涨
  C2: 当日大阳线: close - open > 5% * open
  C3: 巨量: volume > MA(volume, 5) * 3
  C4: close < high  (不是涨停)
  C5: MACD红柱虽长但DIFF开始走平
【操作】精心设置的诱多陷阱，格外小心，减仓或清仓
【参数】sell|bull_trap|中|ma13,ma34,ma55,volume,macd|日线|—
```

---

## 五、调整篇 — 洗盘/回调策略（14种）

### #33 串阴

```
【定义】小幅拉升后窄幅平台，持续5根以上缩量阴线，洗盘结束信号。
【量化条件】
  C1: 连续5根以上阴线: close[t-k] < open[t-k] for k=0..4+
  C2: 每根振幅小: high-low < 3% * open
  C3: volume逐日缩小: volume[t] < volume[t-1]
  C4: close[t] > MA(close, 13) * 0.98  (不跌破13日线太多)
  C5: 此前有一波小幅拉升
【操作】洗盘结束信号，次日可介入
【参数】buy|washout_end|中|ma13,ma34,ma55,volume|日线|短线
```

### #34 串阳

```
【定义】平台上持续5根以上小阳线，驱逐获利盘和限价收集。
【量化条件】
  C1: 连续5根以上阳线: close[t-k] >= open[t-k]
  C2: 每根涨幅1%-3%
  C3: volume温和
  C4: close[t] 在13/34日均线上方
  C5: MA(close, 5) 向上
【操作】即将拉升的显著标志，介入
【参数】buy|strong_reorganization|高|ma13,ma34,ma55,volume|日线|短线
```

### #35 立竿见影

```
【定义】阳线下影线内藏缩量小阴线，缩量回踩确认。
【量化条件】
  C1: 前日阳线: close[t-1] > open[t-1]
  C2: 前日上影线较长: (high[t-1] - max(open,t-1), close[t-1])) / (close[t-1] - open[t-1]) > 2
  C3: 次日缩量小阴: close[t] < open[t]  AND  volume[t] < volume[t-1] * 0.6
  C4: close[t] 在前日阳实体范围内
  C5: close[t] > ma13[t]
【操作】缩量回踩确认，短线介入
【参数】buy|pullback_confirm|中|ma13,ma34,ma55,volume|日线|短线
```

### #36 拖泥带水（卖出）

```
【定义】涨停或接近涨停开盘后逐步回落，收长下影线，悄悄派发。
【量化条件】
  C1: open[t] >= close[t-1] * 1.03  (高开>3%)
  C2: close[t] < open[t]  (收阴或十字星)
  C3: (high[t] - low[t]) / open[t] > 0.05  (振幅大)
  C4: low[t] 接近最高价  (长下影线)
  C5: volume[t] 放大
【操作】庄家筹码太多无法一次派发，留长下影利于次日更好派发
【参数】sell|distribution|中|ma13,ma34,ma55,volume|日线|—
```

### #37 分道扬镳（卖出）

```
【定义】13日下穿34日死叉点，13日由升趋平转下。
【量化条件】
  C1: ma13[t-1] > ma34[t-1]  AND  ma13[t] < ma34[t]  (13下穿34)
  C2: ma13[t-1] > ma13[t-2]  AND  ma13[t] <= ma13[t-1]  (13日走平转跌)
  C3: close[t] < ma13[t]
  C4: volume[t] 放大或持平
  C5: 此前有一段拉升
【操作】此后转向空方，清仓离场
【参数】sell|ma_death_cross|高|ma13,ma34,ma55,volume|日线|—
```

### #38 一箭穿心（卖出）

```
【定义】13日下穿55日线死叉点，庄家派发完毕。
【量化条件】
  C1: close[t] < ma55[t]  (跌破55日线)
  C2: ma13[t-1] > ma55[t-1]  AND  ma13[t] < ma55[t]  (13下穿55)
  C3: ma55[t-3] < ma55[t-2] < ma55[t-1]  (55日由升趋平)
  C4: volume[t] 放量
  C5: close[t] 在结点下方
【操作】庄家已派发完毕，从速离去
【参数】sell|ma_death_cross_55|高|ma13,ma34,ma55,volume|日线|—
```

### #39 一阴破三线（卖出）

```
【定义】一根阴线同时跌破13/34/55三条均线。
【量化条件】
  C1: close[t] < ma13[t] AND close[t] < ma34[t] AND close[t] < ma55[t]
  C2: open[t] > ma13[t-1]  (开盘在均线之上)
  C3: close[t] < open[t]  (阴线)
  C4: volume[t] 放大
  C5: close[t] / open[t] < 0.97  (跌幅>3%)
【操作】先用低开阴线锁定套牢盘，然后慢慢派发，坚决清仓
【参数】sell|break_below_all_ma|高|ma13,ma34,ma55,volume|日线|—
```

### #40 落井下石（卖出）

```
【定义】跌破均线后继续放量下跌，加速下跌形态。
【量化条件】
  C1: close[t-3] < ma55[t-3]  (已跌破55日线)
  C2: close[t] < close[t-1]  (继续跌)
  C3: volume[t] > MA(volume, 5)  (放量下跌)
  C4: 阴线实体扩大: close[t] - open[t] > (close[t-1] - open[t-1])
  C5: ma13[t] < ma34[t] < ma55[t]  (空头排列)
【操作】加速下跌，立即清仓，不抄底
【参数】sell|accelerating_drop|高|ma13,ma34,ma55,volume|日线|—
```

### #41 过河拆桥（卖出）

```
【定义】跌破上行的13日均线中阴线，行情进入尾声。
【量化条件】
  C1: ma13[t-5] < ma13[t-4] < ma13[t-3] < ma13[t-2] < ma13[t-1]  (13日连续上行)
  C2: close[t] < ma13[t]  (跌破13日)
  C3: close[t] < open[t]  (阴线)
  C4: volume[t] 放大
  C5: (ma13[t-1] - ma55[t-1]) / ma55[t-1] > 0.1  (涨幅已大)
【操作】持仓巨大无法一次性派发，跌破13日行情进入尾声，脱掉持股
【参数】sell|break_below_13|高|ma13,ma34,ma55,volume|日线|—
```

### #42 晨钟暮鼓（卖出）

```
【定义】高位连续阴线，见顶信号。
【量化条件】
  C1: 连续3根以上阴线
  C2: close 逐日降低
  C3: volume 逐日放大（恐慌抛售）
  C4: close[t] < ma13[t]
  C5: 此前有一段明显拉升
【操作】见顶信号，清仓
【参数】sell|top_signal|中|ma13,ma34,ma55,volume|日线|—
```

### #43 马失前蹄（卖出）

```
【定义】上升趋势终止信号，MA13拐头向下。
【量化条件】
  C1: 此前 ma13 斜率向上
  C2: ma13[t] <= ma13[t-1]  (13日拐头)
  C3: close[t] < ma13[t]
  C4: 且 close[t] < MA(close, 13)
  C5: MACD红柱缩短或转绿
【操作】上升趋势终止，清仓
【参数】sell|trend_end|高|ma13,ma34,ma55,volume,macd|日线|—
```

### #44 节外生枝（卖出）

```
【定义】最后一根阳线后拉出星阳线或星阴线，调整信号。
【量化条件】
  C1: 前日大阳线: close[t-1] - open[t-1] > 3% * open[t-1]
  C2: 当日星线: abs(close[t] - open[t]) / open[t] < 0.02
  C3: volume[t] < volume[t-1]
  C4: close[t] 接近 close[t-1]
  C5: 此前有一段连续上涨
【操作】调整信号，主动回避
【参数】sell|adjustment_signal|中|ma13,ma34,ma55,volume|日线|—
```

### #45 笑里藏刀（卖出）

```
【定义】冲高后受阻，次日高开高走但始终冲不破昨日上影线。
【量化条件】
  C1: 前日长上影: (high[t-1] - max(open[t-1], close[t-1])) / (open[t-1]-close[t-1]) > 3
  C2: 次日高开: open[t] > close[t-1]
  C3: close[t] < high[t-1]  (冲不破前日上影)
  C4: volume[t] 缩小
  C5: close[t] < MA(close, 5)
【操作】拉升虚张声势，调整在即，主动跳出
【参数】sell|false_bull|中|ma13,ma34,ma55,volume|日线|—
```

### #46 狗急跳墙（卖出）

```
【定义】拉升后高位留带量向上跳空缺口。
【量化条件】
  C1: open[t] > high[t-1]  (向上跳空)
  C2: volume[t] >= MA(volume, 5) * 1.5  (带量)
  C3: close[t] < high[t]  (留长上影或不涨停)
  C4: 此前有一段连续上涨
  C5: gap(t) = (open[t] - high[t-1]) / high[t-1] > 0.02  (缺口>2%)
【操作】派发阶段，减仓或清仓
【参数】sell|gap_distribution|中|ma13,ma34,ma55,volume|日线|—
```

---

## 六、卖出篇 — 见顶/出货策略（5种）

### #47 一剑封喉（见顶）

```
【定义】携量上攻后冲高回落，上影线超出实体3-5倍，典型见顶。
【量化条件】
  C1: 上影线长: (high - max(open, close)) / max(1, abs(open - close)) > 3
  C2: volume 放量（非天量）
  C3: close / close[t-5] - 1 > 0.15  (短期涨幅大)
  C4: close[t] < close[t-1]  (收阴居多)
  C5: 此前连续上涨3日+
【操作】典型见顶，清仓出局
【参数】sell|top_pattern|高|ma13,ma34,ma55,volume|日线|—
```

### #48 一枝独秀（高位见顶）

```
【定义】高位放量急拉留长长上影线，主力放量诱多。
【量化条件】
  C1: high[t] - close[t] > (close[t] - open[t]) * 3  (上影线远大于实体)
  C2: volume[t] >= MA(volume, 5) * 2.0
  C3: close[t] / close[t-5] - 1 > 0.20  (短期涨幅大)
  C4: close[t] < high[t] * 0.95  (收盘远离最高价)
  C5: 处于前期高点附近
【操作】主力为顺利派发，放量诱多，很快自由落体，清仓
【参数】sell|top_volume|高|ma13,ma34,ma55,volume|日线|—
```

### #49 见好就收（乖离过大）

```
【定义】Y = (ma13 - ma55) / ma55 * 100%。Y<10%持股，Y>10%预警，Y>15%清仓。
【量化条件】
  C1: Y = (ma13[t] - ma55[t]) / ma55[t] * 100
  C2: if Y < 10: hold
  C3: if 10 < Y < 15: warning（减仓至5成）
  C4: if Y > 15: sell（清仓）
  C5: Y 值在扩大趋势中则更紧急
【操作】量化纪律，严格执行
【参数】sell|ma_divergence|高|ma13,ma34,ma55|日线|—
```

### #50 金蝉脱壳（高位洗盘）

```
【定义】高位刻意震仓，制造恐慌让持仓者不安。
【量化条件】
  C1: 此前有一段上涨（涨幅>20%）
  C2: 连续2-3日大阴线
  C3: volume 在阴线日放大
  C4: close[t] 接近 ma13[t] 但不跌破
  C5: 次日或第三天缩量小阳
【操作】震仓结束后可重新介入；若连续跌破13日则清仓
【参数】sell|high_wash|中|ma13,ma34,ma55,volume|日线|—
```

### #51 独上高楼（高位滞涨）

```
【定义】连续上涨后在高位滞涨，量能萎缩，趋势衰竭。
【量化条件】
  C1: close[t] 接近前高: close[t] > high[t-1] * 0.98
  C2: volume[t] < MA(volume, 5) * 0.7  (量能萎缩)
  C3: 连续3日涨幅 < 1%
  C4: ma13 斜率趋平或向下
  C5: MACD红柱缩短
【操作】趋势衰竭信号，减仓
【参数】sell|exhaustion|中|ma13,ma34,ma55,volume,macd|日线|—
```

---

## 七、补充形态（5种）

### #52 三剑客（卖出/买入判断）

```
【定义】三根高开低走阴线后在13日线附近止跌企稳，震仓后重拾升势。
【量化条件】
  C1: 连续3日高开低走阴线
  C2: 每根振幅大但跌幅可控
  C3: close[3] 接近 ma13
  C4: close[4] 收阳: close[4] > open[4]
  C5: volume[4] 恢复
【操作】震仓结束，可重新介入（注意：是震仓结束而非继续下跌）
【参数】sell|shakeout_end|中|ma13,ma34,ma55,volume|日线|短线
```

### #53 红杏出墙·二买

```
【定义】红杏出墙后回调再次站上13日线，二次确认买点。
【量化条件】
  C1: 此前有红杏出墙信号
  C2: 回调后 close < ma13（跌破）
  C3: 再次站上: close[t] > ma13[t] AND open[t] < ma13[t]
  C4: close[t] > open[t]（阳线）
  C5: volume[t] 温和放大
【操作】二次确认，中线加仓
【参数】buy|secondary_buy|高|ma13,ma34,ma55,volume|日线|中线
```

### #54 动量加速

```
【定义】MACD两线从零轴上穿到零轴之上，红柱第一次缩短，阴线回调。
【量化条件】
  C1: MACD.DIF[t] > 0 AND MACD.DEA[t] > 0
  C2: 此前 DIF 曾 < 0（从零轴下穿上来）
  C3: MACD histogram 第一次缩短
  C4: close[t] < close[t-1]（收阴回调）
  C5: close[t] > ma13[t]（仍站在13日线上方）
【操作】短线绝佳进仓点
【参数】buy|momentum_acceleration|中|ma13,ma34,ma55,macd,macd,macd|日线|短线
```

### #55 量能突破

```
【定义】放量突破55日均线，上升通道确认。
【量化条件】
  C1: close[t-1] < ma55[t-1]  (此前在55日下方)
  C2: close[t] > ma55[t]  (突破55日)
  C3: volume[t] >= MA(volume, 5) * 2.0  (倍量)
  C4: close[t] / open[t] - 1 > 0.03  (大阳线)
  C5: ma13[t] > ma13[t-1]  (13日向上)
【操作】放量突破55日，中线持有
【参数】buy|volume_break|高|ma13,ma34,ma55,volume|日线|中线
```

---

## 八、量化实现 — Python 数据结构与回测框架

### 8.1 信号数据结构

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class Signal135:
    name: str                    # 形态名称
    code: str                    # 股票代码
    date: str                    # 信号日期 "YYYY-MM-DD"
    direction: str               # "buy" or "sell"
    confidence: str              # "高" "中" "低"
    scenario: str                # 场景分类
    hold_period: str             # 持有期
    stop_loss_pct: float         # 建议止损位（%）
    take_profit_pct: float       # 建议止盈位（%）
    ma13: float
    ma34: float
    ma55: float
    volume: float
    volume_ratio: float          # 量比
    macd_dif: float
    macd_dea: float
    macd_hist: float
    dmi_di_plus: float
    dmi_di_minus: float
    dmi_adx: float
    dmi_adxr: float
```

### 8.2 推荐回测框架

| 框架 | 适用场景 | 优势 |
|------|----------|------|
| **Backtrader** | 本地回测 | 纯Python，自定义指标，支持多策略 |
| **vn.py** | 实盘对接 | 对接CTP/券商，生产级 |
| **聚宽JoinQuant** | 在线回测 | 数据全，社区活跃 |
| **米筐RiceQuant** | 在线回测 | 因子研究强 |
| **通达信公式** | 快速选股 | 即时可用 |

### 8.3 Backtrader 策略模板

```python
import backtrader as bt

class Strategy135(bt.Strategy):
    params = (
        ('ma13_period', 13),
        ('ma34_period', 34),
        ('ma55_period', 55),
        ('vol_period', 5),
    )

    def __init__(self):
        self.ma13 = bt.indicators.SMA(self.data.close, period=self.p.ma13_period)
        self.ma34 = bt.indicators.SMA(self.data.close, period=self.p.ma34_period)
        self.ma55 = bt.indicators.SMA(self.data.close, period=self.p.ma55_period)
        self.vol = bt.indicators.SMA(self.data.volume, period=self.p.vol_period)
        self.macd = bt.indicators.MACD(self.data.close)

    def next(self):
        # 红杏出墙检测
        if self.detect_red_apricot():
            self.buy()

        # 见好就收检测
        if self.detect_take_profit():
            self.close()

    def detect_red_apricot(self):
        """红杏出墙"""
        return (
            self.ma13[0] > self.ma13[-1] and
            self.ma13[-1] <= self.ma13[-2] and
            self.data.close[0] > self.ma13[0] and
            self.data.close[0] > self.data.open[0] and
            self.data.volume[0] > self.vol[0] * 1.2
        )

    def detect_take_profit(self):
        """见好就收"""
        y = (self.ma13[0] - self.ma55[0]) / self.ma55[0] * 100
        return y > 15 and self.position
```

### 8.4 通达信选股公式

```
{135战法-红杏出墙选股公式}
MA13:=MA(C,13);
MA34:=MA(C,34);
MA55:=MA(C,55);
MA13_ZP:=MA13>=REF(MA13,1) AND REF(MA13,1)<=REF(MA13,2);  {13日走平转升}
YANGXIAN:=C>O AND C>MA13 AND O<=MA13;  {阳线上站}
FANG_LIANG:=V>MA(V,5)*1.2;  {放量}
TOU_SHI_WEN_LU:=MA13<=REF(MA34,1) AND V>MA(V,5);  {投石问路}
XIAO_HEI:=(H-LOW)/(HIGH-LOW)>0.3;  {下影线占比>30%}
JIN_WU_CANG_JIAO:=REF(C<O AND (MIN(O,C)-L)/MAX(1,O-C)>1.5,1) AND L>REF(L,1) AND V<REF(V,1)*0.7;

{综合选股:满足任一条件}
XUangu: MA13_ZP AND YANGXIAN AND FANG_LIANG OR TOU_SHI_WEN_LU OR JIN_WU_CANG_JIAO;
```

---

## 九、纪律与风险管理

### 核心铁律
1. **严把买进关** — 135战法重中之重
2. **重兵出击单打一** — 集中资金，分散投资欠合力
3. **进退有据，速战急归** — 短线操作不恋战
4. **常捂资金短捂股** — 强做弱休常空仓
5. **不贪不躁** — 守株待兔，耐心空仓守候

### 资金管理
- 单笔仓位 ≤ 总资金 30%
- 止损: 跌破13日线或形态最低点（-5%~-8%）
- 止盈: 见好就收（Y值>10%预警，>15%清仓）
- 最大回撤: 单策略 ≤ 总资金 15%

### 时间框架
- **主要**: 日线级别
- **辅助**: 60分钟/30分钟（确认信号）
- **超短**: 5分钟（精确入场）

### 信号共振规则
- 单一信号: 轻仓试探
- 2个信号共振: 半仓介入
- 3个以上信号共振: 重仓出击
- 卖出信号与持有冲突: 优先卖出

---

*本策略文档整理自宁俊明《135战法》原著及网络公开资料，仅供量化研究参考，不构成投资建议。*
