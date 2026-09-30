# Skill 4 Trend-Tracking Module Design

## Problem

Current Skill 4 only supports "wash-pattern bottom-fishing" — it scores stocks based on wash intensity and entry signals near cost zones. This works for stocks in accumulation, but completely misses **trend-driven stocks** powered by industry catalysts (from Skill 1-3).

Stocks like 雅克科技, 兴森科技, 东方钽业 are already in strong uptrends (+30-60% above VWAP60), yet Skill 4 gives them low scores and recommends "don't participate." This is wrong when there's confirmed industry logic backing the move.

## Solution

Add a **trend-tracking module** that activates when the stock is in a confirmed uptrend. It provides two signal types:
1. **Pullback confirmation** — buy on dips to moving averages
2. **Breakout confirmation** — buy on volume breakouts of key levels

Both require **industry logic from Skill 1-3 as a hard prerequisite**.

## Routing Logic

```
Enter Skill 4
    ↓
Check MA alignment: MA5 > MA10 > MA20 AND price > MA5?
    ├── YES → Trend-Tracking Module (this new module)
    └── NO  → Existing Wash-Pattern Module (unchanged)
```

## Trigger Conditions (ALL must be met)

1. **Industry logic confirmed** — stock came from Skill 1-3 pipeline with identified catalyst
2. **Multi-head alignment** — MA5 > MA10 > MA20 (short-term bullish structure)
3. **Price above MA5** — currently in the trend, not broken down

## Signal Type A: Pullback Confirmation (Low Risk)

**What it detects**: Price pulled back from a high to MA10/MA20, volume contracted during pullback, then a bullish candle with volume expansion confirms support.

**Data signals (script outputs)**:
- `pullback_target`: which MA the price is pulling back toward (MA5/MA10/MA20)
- `pullback_depth_pct`: how far below recent high
- `vol_contraction`: volume during pullback vs prior expansion (ratio)
- `bounce_candle`: whether last candle is bullish + volume > 5-day avg

**LLM interpretation framework**:
- Buy point: Pullback holds MA20 + bullish candle with volume
- Stop loss: Below the pullback low (or below MA20)
- Position: Based on deviation table

## Signal Type B: Breakout Confirmation (Medium Risk)

**What it detects**: Price breaks above a prior high/resistance level with volume expansion.

**Data signals (script outputs)**:
- `breakout_level`: the resistance level being broken (prior high / platform top)
- `breakout_volume_ratio`: today's volume vs 5-day average
- `breakout_close_above`: whether close is above the breakout level
- `is_limit_up`: whether it's a 涨停 (if yes, NOT a valid signal — can't chase limit-up)

**LLM interpretation framework**:
- Buy point: Close above breakout level + volume > 1.5x 5-day avg + NOT limit-up
- Stop loss: Below breakout level (prior high becomes support)
- Position: One tier lower than pullback type

## Position Sizing by Deviation

| Deviation from MA20 | State | Max Position | Stop Loss Logic |
|---------------------|-------|-------------|-----------------|
| 0-10% | Pullback zone | 70% | Below MA20 |
| 10-20% | Mid-trend | 50% | Below MA10 |
| 20-40% | Acceleration | 30% | Below MA5 |
| >40% | Overheated | DO NOT CHASE | — |

## Risk Controls (Hard Veto — Do NOT chase if any triggers)

1. **VWAP60 deviation > 40%** — overheated, too far from cost base
2. **3 consecutive days: volume expanding but gains shrinking** — distribution/topping pattern
3. **Profit ratio < 80%** — chipset unstable, potential selling pressure
4. **No industry catalyst from Skill 1-3** — pure technical trend without fundamental backing
5. **Limit-up today** — never chase a 涨停, wait for next day confirmation

## Output Format (LLM Analysis Template)

```
【趋势追踪】
  状态: 多头排列 (MA5>MA10>MA20>MA60)
  偏离MA20: +X.X% → 仓位上限: X成
  
  [回踩信号] / [突破信号]
  信号强度: X/10
  {signal details}
  
  进场区间: XX.X ~ XX.X
  止损位: XX.X (依据: MAxx / 回踩低点)
  风险%: X.X%
  仓位: X成 (偏离度限制)
  
  前提: 产业逻辑 ← {Skill 1-3 确认的催化}
```

## Integration with full_analysis.py

The `technicals.py` script adds a new function `calc_trend_signals(kline_df)` that returns raw data:

```python
def calc_trend_signals(kline_df: pd.DataFrame) -> dict:
    """Trend tracking raw data output"""
    # Returns:
    # {
    #   'ma_aligned': True/False (MA5>MA10>MA20),
    #   'above_ma5': True/False,
    #   'deviation_ma20_pct': float,
    #   'deviation_ma60_pct': float,
    #   'pullback_target': 'MA5'/'MA10'/'MA20'/None,
    #   'pullback_depth_pct': float,
    #   'vol_contraction_ratio': float,
    #   'bounce_confirmed': True/False,
    #   'breakout_level': float or None,
    #   'breakout_vol_ratio': float,
    #   'is_limit_up': True/False,
    #   'topping_signal': True/False (3 days vol up + gain down),
    #   'recent_high': float,
    #   'recent_high_date': str,
    # }
```

`full_analysis.py` calls this function and prints the raw data. LLM interprets per SKILL.md framework.

## What Does NOT Change

- `analyze_wash_pattern()` — unchanged, still used for non-trending stocks
- `calc_entry_signals()` — unchanged, still used for wash-pattern scenario
- `get_volume_price_data()` — unchanged, used by both modules
- Fundamental analysis — unchanged
- Market context — unchanged
- The principle: **scripts output raw data, LLM interprets**

## Success Criteria

After implementation, running Skill 4 on 东方钽业/兴森科技/雅克科技 should:
1. Correctly identify them as "trend mode" (not wash-pattern mode)
2. Output deviation %, pullback/breakout signals, position limit
3. LLM can give actionable "回踩买入" or "突破跟进" advice instead of blanket "不参与"
