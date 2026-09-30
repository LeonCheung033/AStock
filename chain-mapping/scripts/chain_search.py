"""
产业链候选票搜索器（pywencai多层搜索 + 传导缺口筛选）

用法：
    python3 scripts/chain_search.py --concept "先进封装"
    python3 scripts/chain_search.py --business "电子玻璃" "玻璃基板"
    python3 scripts/chain_search.py --chain "玻璃基板产业链上市公司"
    python3 scripts/chain_search.py --all --concept "先进封装" --business "电子玻璃" "玻璃基板" --chain "玻璃基板产业链上市公司"

    # 传导缺口模式：找多源命中但近5日涨幅小的（逻辑相关但还没涨）
    python3 scripts/chain_search.py --all --concept "先进封装" --business "电子玻璃" "玻璃基板" --chain "玻璃基板产业链上市公司" --gap
    python3 scripts/chain_search.py --all --concept "先进封装" --business "覆铜板" "电子布" --chain "PCB产业链上市公司" --gap --days 3
"""

import argparse
import pywencai
import pandas as pd


def search_by_concept(concept: str, chg_filter: str = "") -> pd.DataFrame:
    """Layer 1: 概念标签搜索"""
    query = f"所属概念包含{concept}{chg_filter}"
    result = pywencai.get(query=query, loop=True)
    if isinstance(result, pd.DataFrame) and len(result) > 0:
        return _normalize(result, source=f"概念({concept})")
    return pd.DataFrame()


def search_by_business(keywords: list, chg_filter: str = "") -> pd.DataFrame:
    """Layer 2: 主营业务搜索"""
    parts = " 或 ".join(f"主营业务包含{kw}" for kw in keywords)
    query = f"({parts}){chg_filter}"
    result = pywencai.get(query=query, loop=True)
    if isinstance(result, pd.DataFrame) and len(result) > 0:
        return _normalize(result, source=f"主营({','.join(keywords)})")
    return pd.DataFrame()


def search_by_chain(chain_query: str, chg_filter: str = "") -> pd.DataFrame:
    """Layer 3: 产业链搜索"""
    query = f"{chain_query}{chg_filter}"
    result = pywencai.get(query=query, loop=True)
    if isinstance(result, pd.DataFrame) and len(result) > 0:
        return _normalize(result, source=f"产业链({chain_query[:10]})")
    return pd.DataFrame()


def _normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """标准化输出格式"""
    code_col = next((c for c in df.columns if "代码" in c), None)
    name_col = next((c for c in df.columns if "简称" in c), None)
    chg_col = next((c for c in df.columns if "涨跌幅" in c and "近" not in c), None)
    # 尝试找近N日涨跌幅列
    chg_nd_col = next((c for c in df.columns if "涨跌幅" in c and "近" in c), None)

    if not code_col or not name_col:
        return pd.DataFrame()

    out = pd.DataFrame({
        "code": df[code_col].apply(lambda x: str(x)[:6]),
        "name": df[name_col],
        "source": source,
    })
    if chg_col:
        out["change_pct"] = pd.to_numeric(df[chg_col], errors="coerce")
    if chg_nd_col:
        out["change_nd"] = pd.to_numeric(df[chg_nd_col], errors="coerce")
    return out


def _board_label(code: str) -> str:
    """判断板块：主板可交易，创业板/科创板/北交所不可交易"""
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return ""
    elif code.startswith(("300", "301")):
        return "[创业板]"
    elif code.startswith(("688", "689")):
        return "[科创板]"
    elif code.startswith(("8", "4")):
        return "[北交所]"
    return "[其他]"


def search_n_day_change(codes: list, days: int = 5) -> dict:
    """用pywencai查询一批股票的近N日涨幅"""
    if not codes:
        return {}

    change_map = {}
    batch_size = 30
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        # 用"股票代码是X或股票代码是Y"格式逐批查询
        codes_query = " 或 ".join(f"股票代码是{c}" for c in batch)
        query = f"({codes_query}) 近{days}日涨跌幅"
        try:
            result = pywencai.get(query=query, loop=True)
            if isinstance(result, pd.DataFrame) and len(result) > 0:
                code_col = next((c for c in result.columns if "代码" in c), None)
                # 找涨跌幅列：优先匹配"N日"
                chg_col = None
                for c in result.columns:
                    if "涨跌幅" in c:
                        chg_col = c
                        break
                if code_col and chg_col:
                    for _, row in result.iterrows():
                        code = str(row[code_col])[:6]
                        try:
                            val = row[chg_col]
                            if pd.notna(val):
                                change_map[code] = float(val)
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            # 如果批量查询失败，尝试用更简单的查询
            pass

    # 如果上面的方法没拿到数据，用备选方案：逐个查或用概念+涨幅排序
    if not change_map:
        # 备选：直接查这些票的涨跌幅（用简单格式）
        for code in codes[:50]:  # 最多查50只避免太慢
            try:
                result = pywencai.get(query=f"{code} 近{days}日涨跌幅", loop=True)
                if isinstance(result, pd.DataFrame) and len(result) > 0:
                    chg_col = next((c for c in result.columns if "涨跌幅" in c), None)
                    if chg_col:
                        val = result.iloc[0][chg_col]
                        if pd.notna(val):
                            change_map[code] = float(val)
            except Exception:
                pass

    return change_map


def merge_results(dfs: list) -> pd.DataFrame:
    """合并去重，多源命中标注"""
    if not dfs:
        return pd.DataFrame()

    all_df = pd.concat([d for d in dfs if len(d) > 0], ignore_index=True)
    if len(all_df) == 0:
        return pd.DataFrame()

    # 按code分组，合并source
    grouped = all_df.groupby("code").agg({
        "name": "first",
        "source": lambda x: " + ".join(sorted(set(x))),
        "change_pct": "first",
    }).reset_index()

    # 多源命中排前面
    grouped["hit_count"] = grouped["source"].apply(lambda x: x.count("+") + 1)
    # 标注板块
    grouped["board"] = grouped["code"].apply(_board_label)
    grouped["tradable"] = grouped["board"] == ""
    grouped = grouped.sort_values(["hit_count", "tradable"], ascending=[False, False]).reset_index(drop=True)

    return grouped


def find_gap_stocks(merged: pd.DataFrame, days: int = 5, max_change: float = 5.0) -> pd.DataFrame:
    """
    传导缺口筛选：找出多源命中+可交易+近N日涨幅小于阈值的股票
    这些是"逻辑相关但还没涨"的潜力标的
    """
    # 只看可交易+多源命中的
    candidates = merged[(merged["tradable"]) & (merged["hit_count"] >= 2)].copy()
    if len(candidates) == 0:
        print("  ⚠️ 无多源命中的可交易标的")
        # 退而求其次：看单源命中的可交易标的
        candidates = merged[merged["tradable"]].copy()

    # 查询近N日涨幅
    codes = candidates["code"].tolist()
    print(f"\n🔍 查询 {len(codes)} 只候选票近{days}日涨幅...")
    change_map = search_n_day_change(codes, days)

    # 合并涨幅数据
    candidates[f"chg_{days}d"] = candidates["code"].map(change_map)

    # 筛选：近N日涨幅 < max_change%
    gap = candidates[candidates[f"chg_{days}d"] <= max_change].copy()
    gap = gap.sort_values(f"chg_{days}d", ascending=True).reset_index(drop=True)

    return gap, candidates


def main():
    parser = argparse.ArgumentParser(description="产业链候选票搜索器")
    parser.add_argument("--concept", type=str, help="概念标签搜索词")
    parser.add_argument("--business", nargs="+", help="主营业务关键词(可多个)")
    parser.add_argument("--chain", type=str, help="产业链搜索语句")
    parser.add_argument("--all", action="store_true", help="执行全部三层搜索")
    parser.add_argument("--gap", action="store_true", help="传导缺口模式：筛选多源命中但近N日涨幅小的")
    parser.add_argument("--days", type=int, default=5, help="缺口筛选的回看天数 (default: 5)")
    parser.add_argument("--max-change", type=float, default=5.0, help="缺口筛选的涨幅上限%% (default: 5.0)")
    args = parser.parse_args()

    results = []

    # gap模式下在搜索时直接加涨幅条件（让pywencai服务端过滤，更高效）
    chg_filter = ""
    if args.gap:
        chg_filter = f"，近{args.days}日涨跌幅小于{args.max_change}%"

    if args.concept or args.all:
        concept = args.concept or "先进封装"
        suffix = " + 涨幅筛选" if args.gap else ""
        print(f"🔍 Layer 1: 概念搜索 — \"{concept}\"{suffix}")
        df = search_by_concept(concept, chg_filter)
        print(f"   → {len(df)} 条结果")
        results.append(df)

    if args.business or args.all:
        keywords = args.business or ["电子玻璃", "玻璃基板"]
        suffix = " + 涨幅筛选" if args.gap else ""
        print(f"🔍 Layer 2: 主营搜索 — {keywords}{suffix}")
        df = search_by_business(keywords, chg_filter)
        print(f"   → {len(df)} 条结果")
        results.append(df)

    if args.chain or args.all:
        chain_q = args.chain or "玻璃基板产业链上市公司"
        suffix = " + 涨幅筛选" if args.gap else ""
        print(f"🔍 Layer 3: 产业链搜索 — \"{chain_q}\"{suffix}")
        df = search_by_chain(chain_q, chg_filter)
        print(f"   → {len(df)} 条结果")
        results.append(df)

    if not results:
        print("⚠️ 请指定至少一种搜索方式 (--concept / --business / --chain / --all)")
        return

    # 合并
    merged = merge_results(results)
    print(f"\n{'='*60}")
    print(f"  合并去重后共 {len(merged)} 只候选票")
    print(f"{'='*60}\n")

    if len(merged) == 0:
        return

    # === 传导缺口模式 ===
    if args.gap:
        # 在gap模式下，pywencai已经在搜索时过滤了涨幅
        # 所以merged里的都是满足"近N日涨幅<X%"的股票
        tradable = merged[merged["tradable"]].copy()
        multi_hit = tradable[tradable["hit_count"] >= 2]
        single_hit = tradable[tradable["hit_count"] == 1]

        print(f"\n{'='*60}")
        print(f"  🎯 传导缺口：近{args.days}日涨幅 < {args.max_change}% 的相关标的")
        print(f"  （逻辑相关但还没涨 = 潜力标的）")
        print(f"{'='*60}\n")

        if len(multi_hit) > 0:
            print(f"⭐ 多源命中缺口（{len(multi_hit)}只，关联度高+还没涨）:")
            print(f"   {'代码':<8} {'名称':<10} {'今日涨幅':<10} {'来源'}")
            print(f"   {'-'*65}")
            for _, row in multi_hit.iterrows():
                chg = f"{row['change_pct']:+.1f}%" if pd.notna(row.get("change_pct")) else "N/A"
                print(f"   {row['code']:<8} {row['name']:<10} {chg:<10} ← {row['source']}")
            print()

        if len(single_hit) > 0:
            print(f"  单源命中缺口（{len(single_hit)}只，供参考）:")
            for _, row in single_hit.head(20).iterrows():
                chg = f"{row['change_pct']:+.1f}%" if pd.notna(row.get("change_pct")) else "N/A"
                print(f"   {row['code']:<8} {row['name']:<10} {chg:<10} ← {row['source']}")

        # 统计
        print(f"\n  📊 传导缺口(可交易): {len(tradable)}只 (多源{len(multi_hit)} + 单源{len(single_hit)})")
        print(f"  💡 这些是逻辑相关但近{args.days}日涨幅<{args.max_change}%的标的，可能存在补涨机会")
        return

    # === 普通模式（原有逻辑） ===
    # 多源命中
    multi = merged[merged["hit_count"] > 1]
    if len(multi) > 0:
        print("⭐ 多源命中（关联度高）:")
        for _, row in multi.iterrows():
            chg = f" {row['change_pct']:+.1f}%" if pd.notna(row.get("change_pct")) else ""
            board = f" {row['board']}" if row['board'] else ""
            print(f"   {row['code']} {row['name']:8s}{chg}{board}  ← {row['source']}")
        print()

    # 单源命中
    single = merged[merged["hit_count"] == 1]
    if len(single) > 0:
        print("  单源命中:")
        for _, row in single.head(30).iterrows():
            chg = f" {row['change_pct']:+.1f}%" if pd.notna(row.get("change_pct")) else ""
            board = f" {row['board']}" if row['board'] else ""
            print(f"   {row['code']} {row['name']:8s}{chg}{board}  ← {row['source']}")

    # 统计可交易票数
    tradable_count = len(merged[merged["tradable"]])
    non_tradable = len(merged) - tradable_count
    print(f"\n  📊 可交易(主板): {tradable_count}只 | 不可交易(创业板/科创板): {non_tradable}只")


if __name__ == "__main__":
    main()
