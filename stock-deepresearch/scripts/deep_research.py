"""
产业链深度研究入口（Skill 5 编排脚本）

串联 news_fetcher → chain_search → pool_filter，从一个方向/事件出发，
拉取数据并输出结构化信息供LLM做完整的深度研究报告。

用法：
    # 方式A：主动扫描模式（先拉新闻，再分析）
    python3 scripts/deep_research.py --scan --hours 3

    # 方式B：方向驱动模式（指定方向直接搜索）
    python3 scripts/deep_research.py --direction "碳化硅" \
        --concept "碳化硅" --business "SiC" "碳化硅器件" \
        --chain "碳化硅产业链上市公司" \
        --leaders 600703 603290

    # 方式C：简化模式（只给方向名，自动构造搜索词）
    python3 scripts/deep_research.py --direction "国产算力"

    # 输出保存到文件
    python3 scripts/deep_research.py --direction "碳化硅" --output outputs/sic_research.md
"""

import argparse
import subprocess
import sys
import os
from datetime import datetime


STOCK_DIR = "/Users/bytedance/Documents/stock"
NEWS_SCRIPT = f"{STOCK_DIR}/theme-discovery/scripts/news_fetcher.py"
CHAIN_SCRIPT = f"{STOCK_DIR}/chain-mapping/scripts/chain_search.py"
POOL_SCRIPT = f"{STOCK_DIR}/stock-pool/scripts/pool_filter.py"
ANALYSIS_SCRIPT = f"{STOCK_DIR}/stock-analysis/scripts/full_analysis.py"


def run_cmd(cmd: list, desc: str = "") -> str:
    """执行命令并返回输出"""
    if desc:
        print(f"\n{'─'*50}")
        print(f"  ▶ {desc}")
        print(f"{'─'*50}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr] {result.stderr[:500]}"
        print(output[:3000])  # 限制输出长度
        return output
    except subprocess.TimeoutExpired:
        print(f"  [超时] 命令执行超过120秒")
        return ""
    except Exception as e:
        print(f"  [错误] {e}")
        return ""


def phase1_scan(hours: int = 3, session: str = None) -> str:
    """Phase 1: 新闻拉取"""
    cmd = ["python3", NEWS_SCRIPT]
    if hours:
        cmd.extend(["--hours", str(hours)])
    elif session:
        cmd.extend(["--session", session])
    else:
        cmd.extend(["--hours", "3"])

    return run_cmd(cmd, f"Phase 1: 拉取新闻（过去{hours}小时）")


def phase2_chain_search(concept: str = None, business: list = None,
                        chain: str = None, gap: bool = True, days: int = 5) -> str:
    """Phase 2: 产业链搜索 + 传导缺口"""
    cmd = ["python3", CHAIN_SCRIPT, "--all"]

    if concept:
        cmd.extend(["--concept", concept])
    if business:
        cmd.extend(["--business"] + business)
    if chain:
        cmd.extend(["--chain", chain])
    if gap:
        cmd.extend(["--gap", "--days", str(days)])

    return run_cmd(cmd, "Phase 2: 产业链搜索 + 缺口筛选")


def phase3_pool_filter(direction: str = None, leaders: list = None,
                       concept: str = None, business: list = None,
                       chain: str = None, days: int = 5) -> str:
    """Phase 3: 方向验证 + 股池筛选"""
    cmd = ["python3", POOL_SCRIPT]

    if direction:
        cmd.extend(["--direction", direction])
    if leaders:
        cmd.extend(["--leaders"] + leaders)
    if concept:
        cmd.extend(["--concept", concept])
    if business:
        cmd.extend(["--business"] + business)
    if chain:
        cmd.extend(["--chain", chain])
    cmd.extend(["--days", str(days)])

    return run_cmd(cmd, "Phase 3: 方向验证 + 股池筛选")


def main():
    parser = argparse.ArgumentParser(description="产业链深度研究入口")

    # 模式选择
    parser.add_argument("--scan", action="store_true", help="主动扫描模式（先拉新闻）")
    parser.add_argument("--direction", type=str, help="方向名称（方向驱动模式）")

    # Phase 1 参数
    parser.add_argument("--hours", type=int, default=3, help="新闻回看小时数 (default: 3)")
    parser.add_argument("--session", type=str, choices=["morning", "noon", "after", "full"],
                        help="新闻时段")

    # Phase 2/3 搜索参数
    parser.add_argument("--concept", type=str, help="概念标签")
    parser.add_argument("--business", nargs="+", help="主营业务关键词")
    parser.add_argument("--chain", type=str, help="产业链搜索语句")
    parser.add_argument("--leaders", nargs="+", help="方向代表标的")
    parser.add_argument("--days", type=int, default=5, help="回看天数 (default: 5)")

    # 输出
    parser.add_argument("--output", type=str, help="保存输出到文件")

    args = parser.parse_args()

    # 开始
    print(f"\n{'━'*60}")
    print(f"  📊 产业链深度研究")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if args.direction:
        print(f"  方向: {args.direction}")
    print(f"  模式: {'主动扫描' if args.scan else '方向驱动'}")
    print(f"{'━'*60}")

    all_output = []

    # === Phase 1: 新闻扫描（主动扫描模式） ===
    if args.scan:
        output = phase1_scan(args.hours, args.session)
        all_output.append(f"## Phase 1: 新闻扫描\n\n{output}")
        print(f"\n  💡 Phase 1完成。请基于新闻内容确认方向后，")
        print(f"     用 --direction 重新运行或让LLM继续分析。")

        if not args.direction:
            # 扫描模式如果没给方向，到这里停（等LLM分析新闻后确认方向）
            if args.output:
                _save_output(args.output, "\n\n".join(all_output))
            return

    # === Phase 2: 产业链搜索 ===
    if args.direction:
        # 如果没有明确搜索词，用方向名作为默认
        concept = args.concept or args.direction
        business = args.business or [args.direction]
        chain = args.chain or f"{args.direction}产业链上市公司"

        output = phase2_chain_search(concept, business, chain, gap=True, days=args.days)
        all_output.append(f"## Phase 2: 产业链搜索\n\n{output}")

    # === Phase 3: 股池筛选 ===
    if args.direction:
        concept = args.concept or args.direction
        business = args.business or [args.direction]
        chain = args.chain or f"{args.direction}产业链上市公司"

        output = phase3_pool_filter(
            direction=args.direction,
            leaders=args.leaders,
            concept=concept,
            business=business,
            chain=chain,
            days=args.days
        )
        all_output.append(f"## Phase 3: 股池筛选\n\n{output}")

    # === 输出总结 ===
    print(f"\n{'━'*60}")
    print(f"  ✅ 深度研究数据收集完成")
    print(f"{'━'*60}")
    print(f"\n  后续步骤:")
    print(f"  1. LLM基于以上数据做传导推演（Skill 2方法论）")
    print(f"  2. 确认精选候选后，运行Skill 4技术分析:")
    print(f"     python3 {ANALYSIS_SCRIPT} <代码1> <代码2> ...")
    print()

    # 保存
    if args.output:
        _save_output(args.output, "\n\n".join(all_output))


def _save_output(filepath: str, content: str):
    """保存输出到文件"""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# 产业链深度研究报告\n\n")
        f.write(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(content)
    print(f"  📄 已保存到: {filepath}")


if __name__ == "__main__":
    main()
