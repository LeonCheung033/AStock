#!/usr/bin/env python3
"""
全量数据获取 - Skill 4 主入口

串联三个模块，输出所有原始数据供LLM分析。

用法:
    python3 scripts/full_analysis.py 002409
    python3 scripts/full_analysis.py 002409 600378 600160
"""

import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from fundamentals import get_financials, get_shareholders, get_chip_data
from technicals import get_kline, analyze_wash_pattern, calc_entry_signals, get_volume_price_data, calc_trend_signals
from market_context import get_index_kline, get_stock_kline, calc_correlation
import pandas as pd


def full_data(code: str):
    """输出单只股票全量原始数据"""
    code = code.strip().zfill(6)

    print(f"\n{'━'*60}")
    print(f"  {code} 全量数据")
    print(f"{'━'*60}")

    # === 基本面 ===
    print(f"\n[基本面]")
    fin = get_financials(code)
    print(f"  名称: {fin.get('name', 'N/A')} | 行业: {fin.get('industry', 'N/A')}")
    print(f"  PE(TTM): {fin.get('pe_ttm')} | PE(静态): {fin.get('pe')} | PB: {fin.get('pb')} | 毛利率: {fin.get('gross_margin')}%")
    rev = fin.get('revenue')
    rev_str = f"{rev/1e8:.2f}亿" if rev and rev > 1e8 else str(rev) if rev else "N/A"
    prof = fin.get('net_profit')
    prof_str = f"{prof/1e8:.2f}亿" if prof and abs(prof) > 1e8 else str(prof) if prof else "N/A"
    print(f"  营收: {rev_str} (同比: {fin.get('rev_growth')}%)")
    print(f"  归母净利: {prof_str} (同比: {fin.get('profit_growth')}%)")
    print(f"  资产负债率: {fin.get('debt_ratio')}% | 流动比率: {fin.get('current_ratio')}")

    # 股东
    print(f"\n[十大流通股东]")
    shareholders = get_shareholders(code)
    if shareholders:
        for i, sh in enumerate(shareholders[:10]):
            print(f"  {i+1}. {sh['name']} | {sh['ratio']:.2f}% | {sh['change']}")
    else:
        print("  (无数据)")

    # 筹码
    print(f"\n[筹码]")
    chip = get_chip_data(code)
    if chip:
        print(f"  获利: {chip.get('profit_ratio')}% | 平均成本: {chip.get('avg_cost')}"
              f" | 集中度90: {chip.get('concentration_90')}%")
        upper = chip.get('cost_upper_90')
        lower = chip.get('cost_lower_90')
        if upper and lower:
            print(f"  90%成本区间: {lower} ~ {upper} | 现价: {chip.get('price')}")
    else:
        print("  (无数据)")

    # === 技术面 ===
    print(f"\n[技术面]")
    kdf = get_kline(code, n=60)
    if kdf.empty:
        print("  (K线获取失败)")
    else:
        last = kdf.iloc[-1]
        print(f"  最新: {last['close']} | 日期: {last.get('datetime', '')}")

        # 均线
        ma5 = kdf.tail(5)['close'].mean()
        ma10 = kdf.tail(10)['close'].mean()
        ma20 = kdf.tail(20)['close'].mean()
        ma60 = kdf.tail(60)['close'].mean() if len(kdf) >= 60 else None
        print(f"  MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}", end="")
        print(f" MA60={ma60:.2f}" if ma60 else "")

        # 洗盘
        wash_score, wash_details = analyze_wash_pattern(kdf)
        print(f"  洗盘: {wash_score}/14 — {wash_details}")

        # 入场
        entry_score, entry_details = calc_entry_signals(kdf)
        print(f"  入场: {entry_score}/10 — {entry_details}")

        # 量价
        vp = get_volume_price_data(kdf)
        print(f"  量比5/20: {vp.get('vol_5_20_ratio')} | 今日/5均: {vp.get('today_vs_5avg')}x"
              f" | 背离: {vp.get('divergence', '无')}")

        # 趋势追踪
        trend = calc_trend_signals(kdf)
        if trend.get('ma_aligned') or trend.get('ma_near_aligned'):
            tag = "★多头排列" if trend['ma_aligned'] else "☆趋势初期(MA10<MA20)"
            print(f"\n[趋势追踪] {tag}")
            print(f"  MA5={trend['ma5']} > MA10={trend['ma10']} > MA20={trend['ma20']} | MA60={trend['ma60']}")
            print(f"  偏离MA20: {trend['deviation_ma20_pct']:+.1f}% | 偏离MA60: {trend['deviation_ma60_pct']:+.1f}%")
            if trend['deviation_ma20_pct'] <= 10:
                print(f"  仓位上限: 7成(回踩区)")
            elif trend['deviation_ma20_pct'] <= 20:
                print(f"  仓位上限: 5成(趋势中)")
            elif trend['deviation_ma20_pct'] <= 40:
                print(f"  仓位上限: 3成(加速段)")
            else:
                print(f"  ⚠️ 过热(>40%)，不追")
            # 回踩信号
            if trend.get('pullback_target'):
                print(f"  回踩信号: 接近{trend['pullback_target']} | 回撤: {trend['pullback_depth_pct']:.1f}%"
                      f" | 缩量: {trend['vol_contraction_ratio']:.2f} | 反弹确认: {'是' if trend['bounce_confirmed'] else '否'}")
            # 突破信号
            if trend.get('breakout_level'):
                limit_tag = " [涨停,不追]" if trend['is_limit_up'] else ""
                print(f"  突破信号: 突破{trend['breakout_level']} | 放量: {trend['breakout_vol_ratio']:.2f}x{limit_tag}")
            # 顶部特征
            if trend.get('topping_signal'):
                print(f"  ⚠️ 顶部特征: 连续放量+涨幅递减")
            print(f"  近期高点: {trend['recent_high']} ({trend['recent_high_date']})")

    # === 大盘 ===
    print(f"\n[大盘]")
    index_df = get_index_kline(n=60)
    if index_df.empty:
        print("  (指数数据获取失败)")
    else:
        idx_last = index_df.iloc[-1]
        idx_ma20 = index_df.tail(20)['close'].mean()
        print(f"  上证: {idx_last['close']} | MA20: {idx_ma20:.1f}"
              f" ({'上方' if idx_last['close'] > idx_ma20 else '下方'})")
        if len(index_df) >= 6:
            chg5 = (idx_last['close'] - index_df.iloc[-6]['close']) / index_df.iloc[-6]['close'] * 100
            print(f"  近5日: {chg5:+.2f}%")

        if not kdf.empty:
            stock_30 = get_stock_kline(code, n=30)
            if not stock_30.empty:
                corr = calc_correlation(stock_30, index_df, days=20)
                print(f"  相关性: {corr}")

    print(f"\n{'━'*60}\n")


def main():
    if len(sys.argv) < 2:
        print("用法: python3 full_analysis.py <代码1> [代码2] ...")
        sys.exit(1)
    for code in sys.argv[1:]:
        full_data(code)


if __name__ == "__main__":
    main()
