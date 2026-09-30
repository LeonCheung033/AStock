#!/usr/bin/env python3
"""
基本面数据获取 - Skill 4 Module 1

纯数据获取，不做判断。输出原始数值供LLM分析。

用法:
    python3 scripts/fundamentals.py 002409
    python3 scripts/fundamentals.py 002409 600378 600160
"""

import sys
import pywencai
import pandas as pd


def _safe_float(val):
    """安全转换为float"""
    try:
        if pd.isna(val):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_df(result) -> pd.DataFrame:
    """从pywencai结果中提取DataFrame"""
    if isinstance(result, pd.DataFrame):
        return result
    elif isinstance(result, dict):
        if 'tableV1' in result:
            return result['tableV1']
        for v in result.values():
            if isinstance(v, pd.DataFrame) and len(v) > 0:
                return v
    return pd.DataFrame()


def get_financials(code: str) -> dict:
    """获取财务指标原始数据"""
    query = (f'股票代码是{code} 市盈率TTM 市盈率 市净率 销售毛利率 '
             f'营业收入 营业收入同比增长率 归母净利润 归母净利润同比增长率 '
             f'资产负债率 流动比率 商誉')
    result = pywencai.get(query=query, loop=True)

    df = _extract_df(result)
    if df.empty:
        return {}

    data = {}
    for _, row in df.iterrows():
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                continue
            cl = col.lower()
            if '简称' in col and 'name' not in data:
                data['name'] = str(val)
            elif '所属' in col and '行业' in col and 'industry' not in data:
                data['industry'] = str(val)
            elif '市盈率' in col and 'ttm' in cl:
                data['pe_ttm'] = _safe_float(val)
            elif '市盈率' in col and '预测' not in col and 'pe' not in data:
                data['pe'] = _safe_float(val)
            elif ('市净率' in col or 'pb' in cl) and 'pb' not in data:
                data['pb'] = _safe_float(val)
            elif '销售毛利率' in col and 'gross_margin' not in data:
                data['gross_margin'] = _safe_float(val)
            elif '营业收入' in col and '同比' in col and 'rev_growth' not in data:
                data['rev_growth'] = _safe_float(val)
            elif ('营业收入' in col or '营业总收入' in col) and '同比' not in col and '增长' not in col and 'revenue' not in data:
                data['revenue'] = _safe_float(val)
            elif '归属' in col and '净利润' in col and '同比' in col and 'profit_growth' not in data:
                data['profit_growth'] = _safe_float(val)
            elif '归属' in col and '净利润' in col and '同比' not in col and '增长' not in col and 'net_profit' not in data:
                data['net_profit'] = _safe_float(val)
            elif '资产负债率' in col and 'debt_ratio' not in data:
                data['debt_ratio'] = _safe_float(val)
            elif '流动比率' in col and 'current_ratio' not in data:
                data['current_ratio'] = _safe_float(val)
            elif '商誉' in col and 'goodwill' not in data:
                data['goodwill'] = _safe_float(val)
    return data


def get_shareholders(code: str) -> list:
    """获取十大流通股东原始数据"""
    result = pywencai.get(query=f'股票代码是{code} 十大流通股东', loop=True)

    if isinstance(result, dict):
        change_list = result.get('十大流通股东变化', [])
        if isinstance(change_list, list) and change_list:
            shareholders = []
            for item in change_list:
                if isinstance(item, dict):
                    shareholders.append({
                        'name': item.get('流通股东名称', ''),
                        'ratio': item.get('持股比例', 0),
                        'shares': item.get('持股数量', 0),
                        'change': item.get('变动类型', ''),
                    })
            return shareholders
    return []


def get_chip_data(code: str) -> dict:
    """获取筹码数据"""
    result = pywencai.get(query=f'股票代码是{code} 筹码集中度 获利比例 平均成本', loop=True)

    df = _extract_df(result)
    data = {}
    if not df.empty:
        row = df.iloc[0]
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                continue
            if '平均成本' in col:
                data['avg_cost'] = _safe_float(val)
            elif '获利' in col:
                data['profit_ratio'] = _safe_float(val)
            elif '集中度90' in col:
                data['concentration_90'] = _safe_float(val)
            elif '90%' in col and '上限' in col:
                data['cost_upper_90'] = _safe_float(val)
            elif '90%' in col and '下限' in col:
                data['cost_lower_90'] = _safe_float(val)
            elif '最新价' in col:
                data['price'] = _safe_float(val)
    return data


def print_data(code: str):
    """输出原始数据"""
    code = code.strip().zfill(6)
    print(f"\n{'='*50}")
    print(f"  基本面数据: {code}")
    print(f"{'='*50}")

    # 财务
    fin = get_financials(code)
    print(f"\n[财务]")
    print(f"  名称: {fin.get('name', 'N/A')} | 行业: {fin.get('industry', 'N/A')}")
    print(f"  PE(TTM): {fin.get('pe_ttm')} | PE(静态): {fin.get('pe')} | PB: {fin.get('pb')} | 毛利率: {fin.get('gross_margin')}%")
    rev = fin.get('revenue')
    rev_str = f"{rev/1e8:.2f}亿" if rev and rev > 1e8 else f"{rev}" if rev else "N/A"
    prof = fin.get('net_profit')
    prof_str = f"{prof/1e8:.2f}亿" if prof and abs(prof) > 1e8 else f"{prof}" if prof else "N/A"
    print(f"  营收: {rev_str} (同比: {fin.get('rev_growth')}%)")
    print(f"  归母净利: {prof_str} (同比: {fin.get('profit_growth')}%)")
    print(f"  资产负债率: {fin.get('debt_ratio')}% | 流动比率: {fin.get('current_ratio')}")
    if fin.get('goodwill'):
        print(f"  商誉: {fin['goodwill']/1e8:.2f}亿")

    # 股东
    shareholders = get_shareholders(code)
    print(f"\n[十大流通股东]")
    if shareholders:
        for i, sh in enumerate(shareholders[:10]):
            print(f"  {i+1}. {sh['name']} | {sh['ratio']:.2f}% | {sh['change']}")
    else:
        print("  (无数据)")

    # 筹码
    chip = get_chip_data(code)
    print(f"\n[筹码]")
    if chip:
        print(f"  获利比例: {chip.get('profit_ratio')}%")
        print(f"  平均成本: {chip.get('avg_cost')}")
        print(f"  集中度90: {chip.get('concentration_90')}%")
        upper = chip.get('cost_upper_90')
        lower = chip.get('cost_lower_90')
        if upper and lower:
            print(f"  90%成本区间: {lower} ~ {upper}")
        print(f"  现价: {chip.get('price')}")
    else:
        print("  (无数据)")

    print()


def main():
    if len(sys.argv) < 2:
        print("用法: python3 fundamentals.py <代码1> [代码2] ...")
        sys.exit(1)
    for code in sys.argv[1:]:
        print_data(code)


if __name__ == "__main__":
    main()
