"""
方向验证与股池筛选器（Skill 3 核心脚本）

从传导节点出发，验证方向热度、构建可交易股池、排除不合格标的。

用法：
    # 完整流程：方向热度 + 三层搜索 + 排除
    python3 scripts/pool_filter.py --direction "半导体特种气体" \
        --leaders 002409 600378 002971 \
        --concept "电子特气" --business "电子气体" "特种气体" \
        --chain "半导体特种气体产业链上市公司"

    # 只做方向热度判断
    python3 scripts/pool_filter.py --heat-only --leaders 002409 600378 002971

    # 只做排除过滤（输入已有候选池）
    python3 scripts/pool_filter.py --filter-only --codes 002409 600378 603690

    # 指定回看天数
    python3 scripts/pool_filter.py --direction "碳化硅" --leaders 600703 603290 --days 5
"""

import argparse
import sys
import pywencai
import pandas as pd
from typing import Optional

# 复用chain_search的搜索能力
sys.path.insert(0, "/Users/bytedance/Documents/stock/chain-mapping/scripts")
try:
    from chain_search import search_by_concept, search_by_business, search_by_chain, merge_results
except ImportError:
    print("  [警告] 无法导入chain_search，三层搜索功能不可用")
    search_by_concept = search_by_business = search_by_chain = merge_results = None


def check_heat(codes: list, days: int = 5) -> pd.DataFrame:
    """查询代表标的近N日和近20日涨幅，判断方向热度"""
    if not codes:
        return pd.DataFrame()

    codes_query = " 或 ".join(f"股票代码是{c}" for c in codes)
    query = f"({codes_query}) 近{days}日涨跌幅 近20日涨跌幅 股票简称"

    try:
        result = pywencai.get(query=query, loop=True)
        if not isinstance(result, pd.DataFrame) or len(result) == 0:
            return pd.DataFrame()

        code_col = next((c for c in result.columns if "代码" in c), None)
        name_col = next((c for c in result.columns if "简称" in c), None)

        # 找涨跌幅列
        chg_5d_col = None
        chg_20d_col = None
        for c in result.columns:
            if "涨跌幅" in c and f"{days}日" in c:
                chg_5d_col = c
            elif "涨跌幅" in c and "20日" in c:
                chg_20d_col = c

        if not code_col:
            return pd.DataFrame()

        out = pd.DataFrame({
            "code": result[code_col].apply(lambda x: str(x)[:6]),
            "name": result[name_col] if name_col else "N/A",
        })
        if chg_5d_col:
            out[f"chg_{days}d"] = pd.to_numeric(result[chg_5d_col], errors="coerce")
        if chg_20d_col:
            out["chg_20d"] = pd.to_numeric(result[chg_20d_col], errors="coerce")

        return out

    except Exception as e:
        print(f"  [错误] 热度查询失败: {e}")
        return pd.DataFrame()


def judge_heat(heat_df: pd.DataFrame, days: int = 5) -> str:
    """根据热度数据判断方向状态"""
    if heat_df.empty:
        return "unknown"

    chg_col = f"chg_{days}d"
    max_5d = heat_df[chg_col].max() if chg_col in heat_df.columns else 0
    max_20d = heat_df["chg_20d"].max() if "chg_20d" in heat_df.columns else 0

    if max_5d > 20 and max_20d > 50:
        return "overheated"  # 全线过热
    elif max_5d > 10 or max_20d > 20:
        return "accelerating"  # 加速期
    elif max_5d > 5 or max_20d > 10:
        return "starting"  # 启动期
    else:
        return "not_started"  # 尚未启动


def check_purity(code: str) -> Optional[float]:
    """查询标的主营纯正度（返回相关系数或None）"""
    try:
        result = pywencai.get(query=f"{code} 主营业务构成", loop=True)
        if isinstance(result, pd.DataFrame) and len(result) > 0:
            # 返回主营数据供LLM判断
            return result
    except Exception:
        pass
    return None


def check_exclusion(codes: list) -> dict:
    """
    批量检查排除条件：
    - 过热排除：近5日>25% 且 近20日>50%
    - 减持/证伪需要涨停原因数据（此处返回原始数据供LLM判断）
    """
    exclusions = {}

    # 查涨幅
    heat = check_heat(codes, days=5)
    if heat.empty:
        return exclusions

    for _, row in heat.iterrows():
        code = row["code"]
        reasons = []

        chg_5d = row.get("chg_5d", 0) or 0
        chg_20d = row.get("chg_20d", 0) or 0

        if chg_5d > 25 and chg_20d > 50:
            reasons.append(f"过热(5日{chg_5d:+.1f}%, 20日{chg_20d:+.1f}%)")

        if reasons:
            exclusions[code] = reasons

    return exclusions


def get_catalyst_info(code: str) -> Optional[dict]:
    """获取涨停原因/催化时间线"""
    try:
        result = pywencai.get(query=f"{code} 涨停原因", loop=True)
        if isinstance(result, dict):
            return result
        elif isinstance(result, pd.DataFrame) and len(result) > 0:
            return {"data": result}
    except Exception:
        pass
    return None


def board_label(code: str) -> tuple:
    """返回 (板块标签, 是否可交易)"""
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "", True
    elif code.startswith(("300", "301")):
        return "[创业板]", False
    elif code.startswith(("688", "689")):
        return "[科创板]", False
    elif code.startswith(("8", "4")):
        return "[北交所]", False
    return "[其他]", False


def main():
    parser = argparse.ArgumentParser(description="方向验证与股池筛选器")
    parser.add_argument("--direction", type=str, help="方向名称（用于显示）")
    parser.add_argument("--leaders", nargs="+", help="方向代表标的代码（用于热度判断）")
    parser.add_argument("--concept", type=str, help="概念标签搜索词")
    parser.add_argument("--business", nargs="+", help="主营业务关键词")
    parser.add_argument("--chain", type=str, help="产业链搜索语句")
    parser.add_argument("--codes", nargs="+", help="直接输入候选代码（跳过搜索）")
    parser.add_argument("--days", type=int, default=5, help="热度回看天数 (default: 5)")
    parser.add_argument("--heat-only", action="store_true", help="只做热度判断")
    parser.add_argument("--filter-only", action="store_true", help="只做排除过滤")
    args = parser.parse_args()

    direction = args.direction or "未指定方向"

    print(f"\n{'='*60}")
    print(f"  🎯 方向筛选：{direction}")
    print(f"{'='*60}")

    # === Step 1: 方向热度 ===
    if args.leaders:
        print(f"\n【Step 1: 方向热度判断】")
        print(f"  代表标的: {', '.join(args.leaders)}")
        heat_df = check_heat(args.leaders, args.days)

        if not heat_df.empty:
            print(f"\n  {'代码':<8} {'名称':<10} {f'近{args.days}日':<10} {'近20日':<10}")
            print(f"  {'-'*45}")
            for _, row in heat_df.iterrows():
                chg_5d = f"{row.get(f'chg_{args.days}d', 0):+.1f}%" if pd.notna(row.get(f"chg_{args.days}d")) else "N/A"
                chg_20d = f"{row.get('chg_20d', 0):+.1f}%" if pd.notna(row.get("chg_20d")) else "N/A"
                print(f"  {row['code']:<8} {row['name']:<10} {chg_5d:<10} {chg_20d:<10}")

            status = judge_heat(heat_df, args.days)
            status_map = {
                "overheated": "🔴 全线过热 → 直接PASS，不参与",
                "accelerating": "🟡 加速期 → 重点看二线/滞后标的",
                "starting": "🟢 启动期 → 最佳，全面筛选",
                "not_started": "⭐ 尚未启动 → 可能需等催化触发",
            }
            print(f"\n  方向状态: {status_map.get(status, '未知')}")

            if status == "overheated":
                print(f"\n  ⚠️ 方向已过热，暂不参与。流程结束。")
                return
        else:
            print("  (热度数据获取失败，继续后续步骤)")

        if args.heat_only:
            return

    # === Step 2: 股池构建 ===
    candidates = []

    if args.filter_only and args.codes:
        # 直接用给定代码
        print(f"\n【Step 2: 跳过（直接使用输入代码）】")
        candidates = args.codes
    elif search_by_concept is not None:
        print(f"\n【Step 2: 三层搜索构建股池】")
        results = []

        if args.concept:
            print(f"  Layer 1: 概念搜索 — \"{args.concept}\"")
            df = search_by_concept(args.concept)
            print(f"   → {len(df)} 条")
            results.append(df)

        if args.business:
            print(f"  Layer 2: 主营搜索 — {args.business}")
            df = search_by_business(args.business)
            print(f"   → {len(df)} 条")
            results.append(df)

        if args.chain:
            print(f"  Layer 3: 产业链搜索 — \"{args.chain}\"")
            df = search_by_chain(args.chain)
            print(f"   → {len(df)} 条")
            results.append(df)

        if results:
            merged = merge_results(results)
            print(f"\n  合并去重: {len(merged)} 只")

            # 可交易筛选
            tradable = merged[merged["tradable"]].copy()
            non_tradable = merged[~merged["tradable"]].copy()

            print(f"  可交易(主板): {len(tradable)} 只 | 不可交易: {len(non_tradable)} 只")

            if len(tradable) > 0:
                # 多源命中优先
                multi = tradable[tradable["hit_count"] > 1]
                if len(multi) > 0:
                    print(f"\n  ⭐ 多源命中({len(multi)}只):")
                    for _, row in multi.iterrows():
                        print(f"    {row['code']} {row['name']:<10} ← {row['source']}")

                candidates = tradable["code"].tolist()

            if len(non_tradable) > 0:
                print(f"\n  不可交易但供参考:")
                for _, row in non_tradable.head(5).iterrows():
                    print(f"    {row['code']} {row['name']:<10} {row['board']} ← {row['source']}")
    else:
        print("\n  [警告] chain_search不可用，跳过三层搜索")
        if args.codes:
            candidates = args.codes

    if not candidates:
        print("\n  ⚠️ 无候选标的，流程结束。")
        return

    # === Step 3: 排除过滤 ===
    print(f"\n{'='*60}")
    print(f"【Step 3: 排除过滤】")
    print(f"  候选: {len(candidates)} 只")

    # 查热度数据做排除
    heat_all = check_heat(candidates[:50], args.days)  # 最多50只

    excluded = []
    passed = []

    if not heat_all.empty:
        for _, row in heat_all.iterrows():
            code = row["code"]
            name = row.get("name", "N/A")
            chg_5d = row.get(f"chg_{args.days}d", 0) or 0
            chg_20d = row.get("chg_20d", 0) or 0

            # 过热排除
            if chg_5d > 25 and chg_20d > 50:
                excluded.append({
                    "code": code, "name": name,
                    "reason": f"过热({args.days}日{chg_5d:+.1f}%, 20日{chg_20d:+.1f}%)"
                })
            else:
                passed.append({
                    "code": code, "name": name,
                    f"chg_{args.days}d": chg_5d, "chg_20d": chg_20d
                })
    else:
        # 热度查询失败，全部通过
        passed = [{"code": c, "name": "N/A"} for c in candidates]

    # 输出排除结果
    if excluded:
        print(f"\n  ❌ 排除({len(excluded)}只):")
        for ex in excluded:
            print(f"    {ex['code']} {ex['name']:<10} — {ex['reason']}")

    if passed:
        print(f"\n  ✅ 通过({len(passed)}只，送Skill 4):")
        print(f"    {'代码':<8} {'名称':<10} {f'近{args.days}日':<10} {'近20日':<10}")
        print(f"    {'-'*45}")
        for p in passed:
            chg_5d = f"{p.get(f'chg_{args.days}d', 0):+.1f}%" if p.get(f"chg_{args.days}d") is not None else "N/A"
            chg_20d = f"{p.get('chg_20d', 0):+.1f}%" if p.get("chg_20d") is not None else "N/A"
            print(f"    {p['code']:<8} {p['name']:<10} {chg_5d:<10} {chg_20d:<10}")

    # === 总结 ===
    print(f"\n{'='*60}")
    print(f"  📊 筛选结果: {len(passed)} 只通过 / {len(excluded)} 只排除")
    if passed:
        codes_str = " ".join(p["code"] for p in passed)
        print(f"\n  💡 进入Skill 4:")
        print(f"  python3 /Users/bytedance/Documents/stock/stock-analysis/scripts/full_analysis.py {codes_str}")
    print()


if __name__ == "__main__":
    main()
