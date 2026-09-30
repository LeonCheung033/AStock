#!/usr/bin/env python3
"""
大盘环境数据获取 - Skill 4 Module 3

上证指数状态 + 个股与大盘Pearson相关性
只输出数据，不做操作建议。

用法:
    python3 scripts/market_context.py 002409
    python3 scripts/market_context.py 002409 600378
"""

import sys
import numpy as np
import pandas as pd

_client = None

def _get_client():
    global _client
    if _client is None:
        from mootdx.quotes import Quotes
        _client = Quotes.factory(market='std', quiet=True)
    return _client


def get_index_kline(n: int = 60) -> pd.DataFrame:
    """上证指数日K"""
    client = _get_client()
    df = client.index(symbol='000001', frequency=9, offset=n)
    if df is None or df.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        'close': df['close'].astype(float),
        'high': df['high'].astype(float),
        'low': df['low'].astype(float),
        'vol': df['vol'].astype(float),
        'datetime': df['datetime'] if 'datetime' in df.columns else df.index.astype(str),
    }).reset_index(drop=True)


def get_stock_kline(code: str, n: int = 30) -> pd.DataFrame:
    """个股日K"""
    client = _get_client()
    df = client.bars(symbol=code, frequency=9, offset=n)
    if df is None or df.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        'close': df['close'].astype(float),
        'datetime': df['datetime'] if 'datetime' in df.columns else df.index.astype(str),
    }).reset_index(drop=True)


def calc_correlation(stock_df: pd.DataFrame, index_df: pd.DataFrame, days: int = 20) -> float:
    """Pearson相关系数（20日日收益率）"""
    if len(stock_df) < days + 1 or len(index_df) < days + 1:
        return None

    stock_ret = np.diff(stock_df.tail(days + 1)['close'].values) / stock_df.tail(days + 1)['close'].values[:-1]
    index_ret = np.diff(index_df.tail(days + 1)['close'].values) / index_df.tail(days + 1)['close'].values[:-1]

    corr = np.corrcoef(stock_ret, index_ret)[0, 1]
    return round(corr, 3) if not np.isnan(corr) else None


def print_data(code: str):
    """输出大盘环境原始数据"""
    code = code.strip().zfill(6)
    print(f"\n{'='*50}")
    print(f"  大盘环境数据: {code}")
    print(f"{'='*50}")

    index_df = get_index_kline(n=60)
    if index_df.empty:
        print("  (上证指数数据获取失败)")
        return

    last = index_df.iloc[-1]
    print(f"\n[上证指数]")
    print(f"  收盘: {last['close']} | 日期: {last.get('datetime', '')}")

    # 近5日涨幅
    if len(index_df) >= 6:
        chg5 = (last['close'] - index_df.iloc[-6]['close']) / index_df.iloc[-6]['close'] * 100
        print(f"  近5日涨幅: {chg5:+.2f}%")

    # MA
    ma20 = index_df.tail(20)['close'].mean()
    print(f"  MA20: {ma20:.1f} (现价{'>' if last['close'] > ma20 else '<'}MA20)")
    if len(index_df) >= 60:
        ma60 = index_df.tail(60)['close'].mean()
        print(f"  MA60: {ma60:.1f} (现价{'>' if last['close'] > ma60 else '<'}MA60)")

    # 相关性
    stock_df = get_stock_kline(code, n=30)
    if not stock_df.empty:
        corr = calc_correlation(stock_df, index_df, days=20)
        print(f"\n[相关性]")
        print(f"  Pearson(20日): {corr}")
    else:
        print(f"\n  (个股K线获取失败)")

    print()


def main():
    if len(sys.argv) < 2:
        print("用法: python3 market_context.py <代码1> [代码2] ...")
        sys.exit(1)
    for code in sys.argv[1:]:
        print_data(code)


if __name__ == "__main__":
    main()
