#!/usr/bin/env python3
"""
135战法 × baostock实盘回测
===========================
版本: v1.1 — 修复AutoOrderedDict错误
日期: 2026-08-13

用法:
  python run_real_backtest.py                    # 全部300只
  python run_real_backtest.py --top 100          # 前100只
  python run_real_backtest.py --code sh.600519   # 单股
  python run_real_backtest.py --scan             # 参数扫描
  python run_real_backtest.py --freq             # 信号频率
  python run_real_backtest.py --start 2020-01-01 --end 2026-08-13
  python run_real_backtest.py --stop-loss 0.05 --take-profit 0.25
"""

import argparse
import datetime
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

import pandas as pd
import numpy as np

import backtrader as bt
import baostock as bs

# 导入回测引擎
sys.path.insert(0, os.path.dirname(__file__))
from run_135_backtest import (
    Strategy135,
    BacktestEngine,
    analyze_results,
    Signal135,
    BAOSTOCK_AVAILABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ============================================================
# 1. 数据获取
# ============================================================

def get_hs300_stocks() -> List[str]:
    """获取沪深300成分股列表"""
    if not BAOSTOCK_AVAILABLE:
        logger.error("baostock 未安装")
        return []
    try:
        bs.login()
        import baostock.common.context as ctx
        ctx.user_id = 'test'
        rs = bs.query_hs300_stocks()
        codes = []
        while rs is not None and rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            code = row[1] if len(row) > 1 else row[0]
            codes.append(code)
        bs.logout()
        logger.info(f"获取沪深300成分股: {len(codes)} 只")
        return codes
    except Exception as e:
        logger.error(f"获取沪深300失败: {e}")
        return []


def get_stock_data(code: str, start_date: str = "2023-01-01",
                   end_date: str = "2026-08-13") -> Optional[pd.DataFrame]:
    """从baostock获取日线数据"""
    try:
        bs.login()
        import baostock.common.context as ctx
        ctx.user_id = 'test'

        rs = bs.query_history_k_data_plus(
            code,
            "date,open,high,low,close,volume,turn",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )

        data_list = []
        while (rs.error_code == '0') and rs.next():
            data_list.append(rs.get_row_data())

        bs.logout()

        if not data_list:
            return None

        df = pd.DataFrame(data_list, columns=rs.fields)
        # baostock的rs.fields会包含date列，但data_list每行也有date
        # 确保日期列只出现一次
        if 'date' in df.columns and df.index.name is None:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        else:
            df['date'] = pd.to_datetime(df['date'])
            df.index = pd.to_datetime(df['date'])
            df = df.drop(columns=['date'], errors='ignore')

        for col in ['open', 'high', 'low', 'close', 'volume', 'turn']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close', 'volume'])
        df = df.sort_index()

        if 'volume' in df.columns:
            df['amount'] = df['volume'] * 100 * df['close']

        return df

    except Exception as e:
        try:
            bs.logout()
        except:
            pass
        return None


# ============================================================
# 2. 单股回测
# ============================================================

@dataclass
class BacktestResult:
    """单只股票回测结果"""
    code: str
    name: str = ""
    final_value: float = 0
    total_return_pct: float = 0
    sharpe_ratio: float = 0
    max_drawdown_pct: float = 0
    annual_return_pct: float = 0
    total_trades: int = 0
    win_count: int = 0
    lose_count: int = 0
    win_rate_pct: float = 0
    buy_signals: int = 0
    sell_signals: int = 0
    avg_hold_days: float = 0
    best_trade_pct: float = 0
    worst_trade_pct: float = 0
    signal_distribution: str = ""
    data_start: str = ""
    data_end: str = ""
    data_bars: int = 0
    error: str = ""


def run_single_backtest(code: str, signal_names: Optional[List[str]] = None,
                        initial_cash: float = 100000,
                        start_date: str = "2023-01-01",
                        end_date: str = "2026-08-13",
                        use_dmi: bool = True,
                        stop_loss: float = 0.07,
                        take_profit: float = 0.20) -> BacktestResult:
    """单只股票回测"""
    result = BacktestResult(code=code)

    # 获取数据
    df = get_stock_data(code, start_date, end_date)
    if df is None or len(df) < 60:
        result.error = "数据不足"
        return result

    result.data_start = str(df.index[0].date())
    result.data_end = str(df.index[-1].date())
    result.data_bars = len(df)

    try:
        # 获取股票名称
        try:
            rs_name = bs.query_stock_basic(code)
            while rs_name.next():
                row = rs_name.get_row_data()
                result.name = row[2] if len(row) > 2 else ""
        except:
            pass

        # 运行回测 — 直接在策略内收集trade_log，绕过analyze_results的
        # Backtrader内部对象解析问题
        cerebro = bt.Cerebro()
        data_feed = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data_feed)
        cerebro.addstrategy(
            Strategy135,
            signal_names=signal_names,
            use_dmi=use_dmi,
            use_macd=True,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        cerebro.broker.setcash(initial_cash)
        cerebro.broker.setcommission(commission=0.001)

        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                            riskfreerate=0.03, annualize=True)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual')

        results = cerebro.run()
        strat = results[0]

        signals = strat.signals
        trade_log = strat.trade_log

        final_value = cerebro.broker.getvalue()
        initial = initial_cash
        total_return = (final_value - initial) / initial * 100

        # 从trade_log计算交易统计
        total_trades = len(trade_log)
        returns_list = []
        total_hold_days = 0
        best_ret = -999
        worst_ret = 999
        for t in trade_log:
            ret = t.get('return_pct', 0)
            if isinstance(ret, (int, float)):
                returns_list.append(ret)
                if ret > best_ret:
                    best_ret = ret
                if ret < worst_ret:
                    worst_ret = ret
            entry_d = t.get('entry_date', '')
            exit_d = t.get('exit_date', '')
            if isinstance(entry_d, str) and isinstance(exit_d, str) and entry_d != 'N/A':
                try:
                    d1 = datetime.datetime.strptime(entry_d, '%Y-%m-%d')
                    d2 = datetime.datetime.strptime(exit_d, '%Y-%m-%d')
                    total_hold_days += abs((d2 - d1).days)
                except:
                    pass

        win_trades = [r for r in returns_list if r > 0]
        lose_trades = [r for r in returns_list if r <= 0]
        win_count = len(win_trades)
        lose_count = len(lose_trades)
        win_rate = win_count / total_trades * 100 if total_trades > 0 else 0
        avg_hold = total_hold_days / total_trades if total_trades > 0 else 0
        best_trade_pct = best_ret if returns_list else 0
        worst_trade_pct = worst_ret if returns_list else 0

        # 夏普比率
        sharpe = 0
        sharpe_analysis = strat.analyzers.sharpe.get_analysis()
        if isinstance(sharpe_analysis, dict) and 'sharperatio' in sharpe_analysis:
            v = sharpe_analysis['sharperatio']
            if isinstance(v, (int, float)):
                sharpe = v

        # 最大回撤 — AutoOrderedDict 需强制转 dict
        max_dd = 0
        dd_analysis = strat.analyzers.drawdown.get_analysis()
        if isinstance(dd_analysis, dict):
            max_dd_obj = dd_analysis.get('max', {})
            max_dd_dict = dict(max_dd_obj) if not isinstance(max_dd_obj, dict) else max_dd_obj
            if isinstance(max_dd_dict, dict):
                max_dd = max_dd_dict.get('drawdown', 0)
            elif isinstance(max_dd_dict, (int, float)):
                max_dd = max_dd_dict

        # 年化收益
        annual_ret = 0
        ret_analysis = strat.analyzers.returns.get_analysis()
        if isinstance(ret_analysis, dict) and 'rtot' in ret_analysis:
            rtot = ret_analysis['rtot']
            if isinstance(rtot, (int, float)):
                annual_ret = rtot * 100
        # 如果returns为空(无交易)，用总收益近似
        if annual_ret == 0 and total_trades == 0:
            # 计算年化: 假设数据覆盖N年
            try:
                d_start = pd.to_datetime(result.data_start)
                d_end = pd.to_datetime(result.data_end)
                years = (d_end - d_start).days / 365.25
                if years > 0:
                    annual_ret = ((final_value / initial) ** (1 / years) - 1) * 100
            except:
                pass

        # 信号统计
        buy_signals = [s for s in signals if s.get('direction') == 'buy']
        sell_signals = [s for s in signals if s.get('direction') == 'sell']
        signal_dist = {}
        for s in signals:
            name = s.get('signal', 'unknown')
            signal_dist[name] = signal_dist.get(name, 0) + 1

        result.final_value = round(final_value, 2)
        result.total_return_pct = round(total_return, 2)
        result.sharpe_ratio = round(sharpe, 3)
        result.max_drawdown_pct = round(max_dd, 2)
        result.annual_return_pct = round(annual_ret, 2)
        result.total_trades = total_trades
        result.win_count = win_count
        result.lose_count = lose_count
        result.win_rate_pct = round(win_rate, 1)
        result.buy_signals = len(buy_signals)
        result.sell_signals = len(sell_signals)
        result.avg_hold_days = round(avg_hold, 1)
        result.best_trade_pct = round(best_trade_pct, 2)
        result.worst_trade_pct = round(worst_trade_pct, 2)
        result.signal_distribution = str(signal_dist)

    except Exception as e:
        result.error = str(e)
        logger.warning(f"回测失败 {code}: {e}")

    return result


# ============================================================
# 3. 批量回测
# ============================================================

def run_batch_backtest(codes: List[str], signal_names: Optional[List[str]] = None,
                       top_n: int = 50, initial_cash: float = 100000,
                       start_date: str = "2023-01-01", end_date: str = "2026-08-13",
                       use_dmi: bool = True, stop_loss: float = 0.07,
                       take_profit: float = 0.20,
                       top_results: int = 50) -> pd.DataFrame:
    """批量回测 + 排序"""
    codes = codes[:top_n]
    logger.info(f"开始批量回测: {len(codes)} 只股票")
    logger.info(f"参数: 初始资金={initial_cash}, 止损={stop_loss*100}%, 止盈={take_profit*100}%")
    if signal_names:
        logger.info(f"信号: {signal_names}")

    results = []
    for i, code in enumerate(codes):
        t_start = time.time()
        result = run_single_backtest(
            code=code,
            signal_names=signal_names,
            initial_cash=initial_cash,
            start_date=start_date,
            end_date=end_date,
            use_dmi=use_dmi,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        results.append(asdict(result))

        elapsed = time.time() - t_start
        logger.info(f"[{i+1}/{len(codes)}] {code} {result.name}: "
                    f"收益={result.total_return_pct:+.2f}%, "
                    f"交易={result.total_trades}笔, "
                    f"胜率={result.win_rate_pct:.1f}%, "
                    f"耗时={elapsed:.1f}s")

    df = pd.DataFrame(results)

    # 排除有错误的
    df_clean = df[df['error'] == '']

    # 按收益率排序
    df_sorted = df_clean.sort_values('total_return_pct', ascending=False)

    # 返回Top N
    df_top = df_sorted.head(top_results).copy()

    # 重命名显示
    rename_map = {
        'code': '代码', 'name': '名称', 'final_value': '最终价值',
        'total_return_pct': '总收益率(%)', 'sharpe_ratio': '夏普比率',
        'max_drawdown_pct': '最大回撤(%)', 'annual_return_pct': '年化收益(%)',
        'total_trades': '总交易', 'win_count': '盈利笔数', 'lose_count': '亏损笔数',
        'win_rate_pct': '胜率(%)', 'buy_signals': '买入信号',
        'sell_signals': '卖出信号', 'avg_hold_days': '平均持仓(天)',
        'best_trade_pct': '最佳交易(%)', 'worst_trade_pct': '最差交易(%)',
        'signal_distribution': '信号分布', 'data_start': '数据起始',
        'data_end': '数据截止', 'data_bars': '数据K线数',
    }
    df_top = df_top.rename(columns=rename_map)

    # 格式化数值
    num_cols = ['总收益率(%)', '夏普比率', '最大回撤(%)', '年化收益(%)',
                '胜率(%)', '平均持仓(天)', '最佳交易(%)', '最差交易(%)']
    for col in num_cols:
        if col in df_top.columns:
            df_top[col] = df_top[col].apply(
                lambda x: f'{x:.2f}' if pd.notna(x) else 'N/A')

    return df_top, df_clean


# ============================================================
# 4. 主入口
# ============================================================

def main():
    import backtrader as bt  # 确保导入

    parser = argparse.ArgumentParser(description='135战法 × baostock实盘回测')
    parser.add_argument('--code', type=str, default=None, help='单股回测代码')
    parser.add_argument('--top', type=int, default=50, help='股票池大小（默认50）')
    parser.add_argument('--signals', type=str, default=None,
                        help='指定信号，逗号分隔')
    parser.add_argument('--start', type=str, default='2023-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2026-08-13', help='结束日期')
    parser.add_argument('--output', type=str, default='outputs/real_backtest_result.csv',
                        help='结果输出CSV')
    parser.add_argument('--results', type=int, default=50, help='返回结果Top N')
    parser.add_argument('--no-dmi', action='store_true', help='禁用DMI')
    parser.add_argument('--capital', type=float, default=100000, help='初始资金')
    parser.add_argument('--stop-loss', type=float, default=0.07, help='止损')
    parser.add_argument('--take-profit', type=float, default=0.20, help='止盈')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("135战法 × baostock实盘回测")
    logger.info("=" * 70)

    signal_names = None
    if args.signals:
        signal_names = [s.strip() for s in args.signals.split(',')]

    # 单股模式
    if args.code:
        logger.info(f"单股回测: {args.code}")
        df = get_stock_data(args.code, args.start, args.end)
        if df is None:
            logger.error("获取数据失败")
            return
        result = run_single_backtest(
            args.code, signal_names=signal_names,
            initial_cash=args.capital,
            start_date=args.start, end_date=args.end,
            use_dmi=not args.no_dmi,
            stop_loss=args.stop_loss, take_profit=args.take_profit,
        )
        print(f"\n{'='*60}")
        print(f"  {args.code} {result.name}")
        print(f"{'='*60}")
        print(f"  最终价值:    {result.final_value:,.2f}")
        print(f"  总收益率:    {result.total_return_pct:+.2f}%")
        print(f"  夏普比率:    {result.sharpe_ratio:.3f}")
        print(f"  最大回撤:    {result.max_drawdown_pct:.2f}%")
        print(f"  年化收益:    {result.annual_return_pct:.2f}%")
        print(f"  总交易:      {result.total_trades}笔")
        print(f"  胜率:        {result.win_rate_pct:.1f}%")
        print(f"  买入信号:    {result.buy_signals}")
        print(f"  卖出信号:    {result.sell_signals}")
        print(f"  平均持仓:    {result.avg_hold_days:.1f}天")
        print(f"  最佳交易:    {result.best_trade_pct:+.2f}%")
        print(f"  最差交易:    {result.worst_trade_pct:+.2f}%")
        print(f"  信号分布:    {result.signal_distribution}")
        print(f"{'='*60}")
        if result.error:
            print(f"  错误: {result.error}")
        return

    # 获取股票池
    logger.info("获取沪深300成分股...")
    codes = get_hs300_stocks()
    if not codes:
        logger.error("无法获取股票池")
        return

    logger.info(f"股票池: {len(codes)} 只 (前 {args.top} 只参与回测)")

    # 批量回测
    logger.info(f"批量回测: {args.top} 只股票, "
                f"止损={args.stop_loss*100}%, 止盈={args.take_profit*100}%, "
                f"DMI={'启用' if not args.no_dmi else '禁用'}")

    df_top, df_clean = run_batch_backtest(
        codes=codes,
        signal_names=signal_names,
        top_n=args.top,
        initial_cash=args.capital,
        start_date=args.start,
        end_date=args.end,
        use_dmi=not args.no_dmi,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        top_results=args.results,
    )

    # 输出结果
    output_file = args.output
    df_top.to_csv(output_file, index=False, encoding='utf-8-sig')
    logger.info(f"\n回测完成！结果已保存: {output_file}")
    print(f"\n{'='*70}")
    print(f"TOP {len(df_top)} 只股票回测结果")
    print(f"{'='*70}")

    display_cols = ['代码', '名称', '总收益率(%)', '夏普比率', '最大回撤(%)',
                    '胜率(%)', '总交易', '买入信号', '平均持仓(天)',
                    '最佳交易(%)', '最差交易(%)']
    available_cols = [c for c in display_cols if c in df_top.columns]
    print(df_top[available_cols].to_string(index=False))

    # 统计
    if len(df_clean) > 0:
        profitable = df_clean[df_clean['total_return_pct'] > 0]
        logger.info(f"\n汇总统计 ({len(df_clean)} 只股票):")
        logger.info(f"  盈利: {len(profitable)} 只 ({len(profitable)/len(df_clean)*100:.1f}%)")
        logger.info(f"  平均收益率: {df_clean['total_return_pct'].mean():.2f}%")
        logger.info(f"  中位数收益率: {df_clean['total_return_pct'].median():.2f}%")
        logger.info(f"  平均胜率: {df_clean['win_rate_pct'].mean():.1f}%")
        logger.info(f"  平均交易次数: {df_clean['total_trades'].mean():.0f}笔")
        if len(df_top) > 0:
            logger.info(f"  最佳股票: {df_top.iloc[0]['代码']} ({df_top.iloc[0]['名称']}) "
                        f"收益={df_top.iloc[0]['总收益率(%)']}%")

    # 保存完整结果
    df_clean.to_csv(output_file.replace('.csv', '_all.csv'), index=False, encoding='utf-8-sig')

    # 信号分布
    logger.info(f"\n信号分布示例 (前10只):")
    for _, row in df_top.head(10).iterrows():
        dist = row.get('信号分布', '')
        logger.info(f"  {row['代码']} {row['名称']}: {dist}")


if __name__ == '__main__':
    main()
