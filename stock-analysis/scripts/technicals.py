#!/usr/bin/env python3
"""
技术面数据获取 - Skill 4 Module 2

洗盘评分(计算) + 入场信号(计算) + 量价原始数据 + 均线数据
只输出数据和分数，不输出判断文字。

数据源: mootdx K线

用法:
    python3 scripts/technicals.py 002409
    python3 scripts/technicals.py 002409 600378
"""

import sys
import pandas as pd

_client = None

def _get_client():
    global _client
    if _client is None:
        from mootdx.quotes import Quotes
        _client = Quotes.factory(market='std', quiet=True)
    return _client


def get_kline(code: str, n: int = 60) -> pd.DataFrame:
    """获取日K线，返回标准列: open/close/high/low/vol/datetime"""
    client = _get_client()
    df = client.bars(symbol=code, frequency=9, offset=n)
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        'open': df['open'].astype(float),
        'close': df['close'].astype(float),
        'high': df['high'].astype(float),
        'low': df['low'].astype(float),
        'vol': df['vol'].astype(float),
        'datetime': df['datetime'] if 'datetime' in df.columns else df.index.astype(str),
    }).reset_index(drop=True)
    return out


def analyze_wash_pattern(kline_df: pd.DataFrame, n_recent: int = 10) -> tuple:
    """华电辽能洗盘评分（满分14），返回(分数, 明细dict)"""
    if kline_df is None or len(kline_df) < 20:
        return 0, {}

    recent = kline_df.tail(n_recent)
    full_20 = kline_df.tail(20)
    details = {}
    score = 0

    # 阶段零：放量砸盘但跌不动
    if len(kline_df) >= 15:
        vol_avg = kline_df['vol'].mean()
        for i in range(len(kline_df) - 5):
            row = kline_df.iloc[i]
            if row['open'] > 0 and row['vol'] > vol_avg * 1.5:
                day_pct = (row['close'] - row['open']) / row['open'] * 100
                if day_pct < -2.5:
                    after = kline_df.iloc[i+1:i+6]
                    if len(after) >= 3:
                        dd = (row['close'] - after['low'].min()) / row['close'] * 100
                        if dd < 5:
                            score += 2
                            details["放量砸盘跌不动"] = "+2"
                            break

    # 阶段一：均线粘合
    if len(kline_df) >= 20:
        ma5 = kline_df.tail(5)['close'].mean()
        ma10 = kline_df.tail(10)['close'].mean()
        ma20 = kline_df.tail(20)['close'].mean()
        ma_spread = (max(ma5, ma10, ma20) - min(ma5, ma10, ma20)) / min(ma5, ma10, ma20) * 100
        if ma_spread < 2:
            score += 2; details["均线粘合"] = f"+2({ma_spread:.1f}%)"
        elif ma_spread < 3:
            score += 1.5; details["均线粘合"] = f"+1.5({ma_spread:.1f}%)"
        elif ma_spread < 5:
            score += 1; details["均线接近"] = f"+1({ma_spread:.1f}%)"

    # 缩量
    vol_5 = kline_df.tail(5)['vol'].mean()
    vol_20 = full_20['vol'].mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1
    if vol_ratio < 0.5:
        score += 2; details["地量"] = f"+2(5/20={vol_ratio:.2f})"
    elif vol_ratio < 0.7:
        score += 1; details["缩量"] = f"+1(5/20={vol_ratio:.2f})"

    # 振幅窄
    amps = [(r['high'] - r['low']) / r['low'] * 100 for _, r in full_20.iterrows() if r['low'] > 0]
    avg_amp = sum(amps) / len(amps) if amps else 99
    if avg_amp < 4:
        score += 1; details["窄振幅"] = f"+1({avg_amp:.1f}%)"

    # 横盘
    if len(kline_df) >= 20:
        rng = (full_20['high'].max() - full_20['low'].min()) / full_20['low'].min() * 100
        if rng < 10:
            score += 1; details["横盘"] = f"+1(区间{rng:.1f}%)"

    # 阶段二：放量不涨
    if len(kline_df) >= 15:
        vol_r5 = kline_df.tail(5)['vol'].mean()
        vol_p10 = kline_df.iloc[-15:-5]['vol'].mean()
        vol_amp = vol_r5 / vol_p10 if vol_p10 > 0 else 1
        p5ago = kline_df.iloc[-6]['close'] if len(kline_df) >= 6 else kline_df.iloc[0]['close']
        pct5 = (kline_df.iloc[-1]['close'] - p5ago) / p5ago * 100 if p5ago > 0 else 0
        if vol_amp > 1.5 and abs(pct5) < 3:
            score += 2; details["放量不涨"] = f"+2(量×{vol_amp:.1f},涨{pct5:+.1f}%)"
        elif vol_amp > 1.2 and abs(pct5) < 4:
            score += 1; details["放量不涨"] = f"+1(量×{vol_amp:.1f},涨{pct5:+.1f}%)"

    # 冲高回落
    us_count = 0
    for _, row in recent.iterrows():
        body = abs(row['close'] - row['open'])
        us = row['high'] - max(row['close'], row['open'])
        if us > body * 1.5 and us > 0:
            us_count += 1
    if us_count >= 3:
        score += 2; details["冲高回落"] = f"+2({us_count}次)"
    elif us_count >= 2:
        score += 1; details["冲高回落"] = f"+1({us_count}次)"

    # 底部抬高
    if len(kline_df) >= 20:
        if kline_df.tail(10)['low'].min() > kline_df.iloc[-20:-10]['low'].min():
            score += 1; details["底部抬高"] = "+1"

    return int(score), details


def calc_entry_signals(kline_df: pd.DataFrame) -> tuple:
    """入场信号（满分10），返回(分数, 明细dict)"""
    if kline_df is None or len(kline_df) < 26:
        return 0, {}

    closes = kline_df['close'].values.tolist()
    last_price = closes[-1]
    score = 0
    details = {}

    # MACD
    if len(closes) >= 35:
        s = pd.Series(closes)
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2

        golden = (dif.iloc[-2] <= dea.iloc[-2]) and (dif.iloc[-1] > dea.iloc[-1])
        near = ((dif.iloc[-1] < dea.iloc[-1]) and (dif.iloc[-1] > dif.iloc[-2]) and
                (dea.iloc[-1] - dif.iloc[-1] < abs(dif.iloc[-1]) * 0.1 + 0.02))

        if golden:
            score += 3; details["MACD"] = "金叉(+3)"
        elif near:
            score += 2; details["MACD"] = "即将金叉(+2)"
        elif hist.iloc[-1] < 0 and hist.iloc[-1] > hist.iloc[-2]:
            score += 1; details["MACD"] = "绿柱缩(+1)"
        else:
            details["MACD"] = "无信号"

    # VWAP60
    recent = kline_df.tail(60) if len(kline_df) >= 60 else kline_df
    total_vol = recent['vol'].sum()
    if total_vol > 0:
        vwap = ((recent['high'] + recent['low'] + recent['close']) / 3 * recent['vol']).sum() / total_vol
        dev = (last_price - vwap) / vwap * 100
        if abs(dev) < 3:
            score += 3; details["VWAP60"] = f"成本区({dev:+.1f}%,+3)"
        elif abs(dev) < 5:
            score += 2; details["VWAP60"] = f"接近({dev:+.1f}%,+2)"
        elif dev > 5:
            score += 1; details["VWAP60"] = f"偏高({dev:+.1f}%,+1)"
        else:
            details["VWAP60"] = f"偏低({dev:+.1f}%)"

    # MA支撑
    if len(kline_df) >= 20:
        ma20 = kline_df.tail(20)['close'].mean()
        ma60 = kline_df.tail(60)['close'].mean() if len(kline_df) >= 60 else kline_df['close'].mean()
        if last_price >= ma20 * 0.98 and last_price >= ma60 * 0.98:
            score += 2; details["MA支撑"] = "双线(+2)"
        elif last_price >= ma60 * 0.98:
            score += 1; details["MA支撑"] = "MA60(+1)"
        else:
            details["MA支撑"] = "破位"

    # MA30趋势余量
    if len(kline_df) >= 30:
        ma30 = kline_df.tail(30)['close'].mean()
        dev30 = (last_price - ma30) / ma30 * 100
        if 0 < dev30 <= 5:
            score += 2; details["MA30余量"] = f"回调到位({dev30:+.1f}%,+2)"
        elif dev30 > 5:
            score += 1; details["MA30余量"] = f"趋势中({dev30:+.1f}%,+1)"
        elif dev30 < 0:
            score -= 1; details["MA30余量"] = f"破位({dev30:+.1f}%,-1)"

    return score, details


def get_volume_price_data(kline_df: pd.DataFrame) -> dict:
    """量价原始数据"""
    if kline_df is None or len(kline_df) < 10:
        return {}

    vol_5 = kline_df.tail(5)['vol'].mean()
    vol_20 = kline_df.tail(20)['vol'].mean() if len(kline_df) >= 20 else vol_5
    today_vol = kline_df.iloc[-1]['vol']

    # 量价配合
    up_vol, down_vol = [], []
    for i in range(max(0, len(kline_df) - 10), len(kline_df)):
        row = kline_df.iloc[i]
        pct = (row['close'] - row['open']) / row['open'] * 100 if row['open'] > 0 else 0
        if pct > 0.3:
            up_vol.append(row['vol'])
        elif pct < -0.3:
            down_vol.append(row['vol'])

    # 背离
    divergence = None
    if len(kline_df) >= 10:
        p5 = kline_df.tail(5)['close'].values
        pp5 = kline_df.iloc[-10:-5]['close'].values
        v5 = kline_df.tail(5)['vol'].values
        vp5 = kline_df.iloc[-10:-5]['vol'].values
        if p5[-1] > pp5[-1] and v5.mean() < vp5.mean() * 0.8:
            divergence = "顶背离(价升量缩)"
        elif p5[-1] < pp5[-1] and v5.mean() < vp5.mean() * 0.7:
            divergence = "底背离(价跌量缩)"

    return {
        'vol_5_20_ratio': round(vol_5 / vol_20, 2) if vol_20 > 0 else None,
        'today_vol': int(today_vol),
        'today_vs_5avg': round(today_vol / vol_5, 2) if vol_5 > 0 else None,
        'up_avg_vol': int(sum(up_vol) / len(up_vol)) if up_vol else None,
        'down_avg_vol': int(sum(down_vol) / len(down_vol)) if down_vol else None,
        'divergence': divergence,
    }


def calc_trend_signals(kline_df: pd.DataFrame) -> dict:
    """趋势追踪原始数据（多头排列+回踩/突破信号）"""
    if kline_df is None or len(kline_df) < 20:
        return {}

    closes = kline_df['close'].values
    last_price = closes[-1]

    # 均线
    ma5 = kline_df.tail(5)['close'].mean()
    ma10 = kline_df.tail(10)['close'].mean()
    ma20 = kline_df.tail(20)['close'].mean()
    ma60 = kline_df.tail(60)['close'].mean() if len(kline_df) >= 60 else kline_df['close'].mean()

    # 多头排列
    ma_aligned = (ma5 > ma10 > ma20)
    ma_near_aligned = (ma5 > ma10 and ma5 > ma20 and not ma_aligned)  # MA5领先但MA10还没超MA20
    above_ma5 = (last_price >= ma5)

    # 偏离度
    dev_ma20 = (last_price - ma20) / ma20 * 100 if ma20 > 0 else 0
    dev_ma60 = (last_price - ma60) / ma60 * 100 if ma60 > 0 else 0

    # 近期高点
    recent_high = kline_df.tail(20)['high'].max()
    high_idx = kline_df.tail(20)['high'].idxmax()
    recent_high_date = kline_df.loc[high_idx, 'datetime'] if 'datetime' in kline_df.columns else ''

    # 回踩检测：价格从近期高点回落，接近哪根均线
    pullback_target = None
    pullback_depth_pct = (recent_high - last_price) / recent_high * 100 if recent_high > 0 else 0

    if last_price <= ma5 * 1.01 and last_price >= ma5 * 0.98:
        pullback_target = 'MA5'
    elif last_price <= ma10 * 1.01 and last_price >= ma10 * 0.97:
        pullback_target = 'MA10'
    elif last_price <= ma20 * 1.01 and last_price >= ma20 * 0.96:
        pullback_target = 'MA20'

    # 回踩期间缩量
    vol_5 = kline_df.tail(5)['vol'].mean()
    vol_10_prev = kline_df.iloc[-15:-5]['vol'].mean() if len(kline_df) >= 15 else vol_5
    vol_contraction_ratio = vol_5 / vol_10_prev if vol_10_prev > 0 else 1.0

    # 反弹确认：最后一根K线为阳线+放量
    last_row = kline_df.iloc[-1]
    is_bullish = last_row['close'] > last_row['open']
    last_vol_vs_5avg = last_row['vol'] / vol_5 if vol_5 > 0 else 1
    bounce_confirmed = is_bullish and last_vol_vs_5avg > 1.2

    # 突破检测：收盘创近20日新高 + 放量
    prev_high = kline_df.iloc[-21:-1]['high'].max() if len(kline_df) >= 21 else kline_df.iloc[:-1]['high'].max()
    breakout_level = prev_high if last_price > prev_high else None
    breakout_vol_ratio = last_vol_vs_5avg

    # 涨停检测
    prev_close = kline_df.iloc[-2]['close'] if len(kline_df) >= 2 else last_price
    day_change_pct = (last_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
    is_limit_up = day_change_pct >= 9.7

    # 顶部特征：连续3日放量但涨幅递减
    topping_signal = False
    if len(kline_df) >= 4:
        last3_vols = kline_df.tail(3)['vol'].values
        last3_chg = []
        for i in range(-3, 0):
            c = kline_df.iloc[i]['close']
            o = kline_df.iloc[i-1]['close'] if abs(i-1) <= len(kline_df) else kline_df.iloc[i]['open']
            last3_chg.append((c - o) / o * 100 if o > 0 else 0)
        if (last3_vols[0] < last3_vols[1] < last3_vols[2] or
            all(v > vol_5 * 0.8 for v in last3_vols)):
            if len(last3_chg) == 3 and last3_chg[0] > last3_chg[1] > last3_chg[2] and last3_chg[2] < last3_chg[0] * 0.5:
                topping_signal = True

    return {
        'ma_aligned': ma_aligned,
        'ma_near_aligned': ma_near_aligned,
        'above_ma5': above_ma5,
        'deviation_ma20_pct': round(dev_ma20, 1),
        'deviation_ma60_pct': round(dev_ma60, 1),
        'pullback_target': pullback_target,
        'pullback_depth_pct': round(pullback_depth_pct, 1),
        'vol_contraction_ratio': round(vol_contraction_ratio, 2),
        'bounce_confirmed': bounce_confirmed,
        'breakout_level': round(breakout_level, 2) if breakout_level else None,
        'breakout_vol_ratio': round(breakout_vol_ratio, 2),
        'is_limit_up': is_limit_up,
        'topping_signal': topping_signal,
        'recent_high': round(recent_high, 2),
        'recent_high_date': str(recent_high_date),
        'ma5': round(ma5, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
    }


def print_data(code: str):
    """输出技术面原始数据"""
    code = code.strip().zfill(6)
    print(f"\n{'='*50}")
    print(f"  技术面数据: {code}")
    print(f"{'='*50}")

    kdf = get_kline(code, n=60)
    if kdf.empty:
        print("  (K线数据获取失败)")
        return

    last = kdf.iloc[-1]
    print(f"\n[行情]")
    print(f"  最新: {last['close']} | 最高: {last['high']} | 最低: {last['low']}")
    print(f"  日期: {last.get('datetime', 'N/A')}")

    # 均线
    print(f"\n[均线]")
    ma5 = kdf.tail(5)['close'].mean()
    ma10 = kdf.tail(10)['close'].mean()
    ma20 = kdf.tail(20)['close'].mean()
    ma60 = kdf.tail(60)['close'].mean() if len(kdf) >= 60 else None
    print(f"  MA5={ma5:.2f} | MA10={ma10:.2f} | MA20={ma20:.2f} | MA60={ma60:.2f}" if ma60 else
          f"  MA5={ma5:.2f} | MA10={ma10:.2f} | MA20={ma20:.2f}")

    # 洗盘评分
    wash_score, wash_details = analyze_wash_pattern(kdf)
    print(f"\n[洗盘评分] {wash_score}/14")
    for k, v in wash_details.items():
        print(f"  {k}: {v}")

    # 入场信号
    entry_score, entry_details = calc_entry_signals(kdf)
    print(f"\n[入场信号] {entry_score}/10")
    for k, v in entry_details.items():
        print(f"  {k}: {v}")

    # 量价数据
    vp = get_volume_price_data(kdf)
    print(f"\n[量价]")
    print(f"  5日/20日量比: {vp.get('vol_ratio_5_20', vp.get('vol_5_20_ratio'))}")
    print(f"  今日成交量: {vp.get('today_vol')} | 今日/5日均: {vp.get('today_vs_5avg')}x")
    print(f"  涨日均量: {vp.get('up_avg_vol')} | 跌日均量: {vp.get('down_avg_vol')}")
    if vp.get('divergence'):
        print(f"  背离: {vp['divergence']}")

    print()


def main():
    if len(sys.argv) < 2:
        print("用法: python3 technicals.py <代码1> [代码2] ...")
        sys.exit(1)
    for code in sys.argv[1:]:
        print_data(code)


if __name__ == "__main__":
    main()
