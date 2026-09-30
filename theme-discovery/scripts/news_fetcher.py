"""
东财全球财经快讯拉取器（支持翻页 + 时段过滤 + 去重合并）

用法：
    python3 scripts/news_fetcher.py                    # 拉盘后时段(15:00~18:30)
    python3 scripts/news_fetcher.py --session morning  # 拉盘前(隔夜18:30~08:30)
    python3 scripts/news_fetcher.py --session noon     # 拉午盘(08:30~12:00)
    python3 scripts/news_fetcher.py --session after    # 拉盘后(15:00~18:30)
    python3 scripts/news_fetcher.py --session full     # 拉全天(08:00~次日00:00)
    python3 scripts/news_fetcher.py --hours 3          # 拉过去3小时（不受时段限制）
    python3 scripts/news_fetcher.py --pages 5          # 手动指定翻页数
    python3 scripts/news_fetcher.py --raw              # 不去重，输出原始全量
"""

import requests
import json
import re
import argparse
from datetime import datetime, timedelta
from collections import defaultdict


def fetch_news(pages: int = 4) -> list:
    """拉取东财快讯，支持翻页"""
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102",
        "sortEnd": "",
        "pageSize": "200",
        "req_trace": "1710315450384",
    }

    all_items = []
    for page in range(pages):
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            items = data["data"]["fastNewsList"]
            all_items.extend(items)
            params["sortEnd"] = data["data"]["sortEnd"]
        except Exception as e:
            print(f"  [警告] 第{page+1}页拉取失败: {e}")
            break

    return all_items


def filter_by_time(items: list, start_time: str, end_time: str, date: str = None) -> list:
    """按时间段过滤。start_time/end_time 格式 'HH:MM'，date 格式 'YYYY-MM-DD'"""
    result = []
    for item in items:
        show_time = item["showTime"]  # 格式: "2026-06-12 18:30:00"
        if date and not show_time.startswith(date):
            continue
        time_part = show_time[11:16]
        if start_time <= time_part <= end_time:
            result.append(item)
    return result


def filter_by_session(items: list, session: str) -> list:
    """按交易时段过滤。自动检测数据中最近的交易日（而非当前日期）"""
    # 从数据中推断最近交易日：找最新一条在08:00~15:00之间的，那天就是交易日
    trade_date = None
    for item in items:
        t = item["showTime"]
        if "09:00" <= t[11:16] <= "15:00":
            trade_date = t[:10]
            break
    if not trade_date:
        # fallback: 用最新条目的日期
        trade_date = items[0]["showTime"][:10] if items else datetime.now().strftime("%Y-%m-%d")

    today = trade_date
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    if session == "morning":
        # 隔夜：昨天18:30 ~ 今天08:30
        part1 = [i for i in items if i["showTime"].startswith(yesterday) and i["showTime"][11:16] >= "18:30"]
        part2 = [i for i in items if i["showTime"].startswith(today) and i["showTime"][11:16] <= "08:30"]
        return part1 + part2
    elif session == "noon":
        return filter_by_time(items, "08:30", "12:00", today)
    elif session == "after":
        return filter_by_time(items, "15:00", "18:30", today)
    elif session == "full":
        # 全天：今天08:00 ~ 明天00:00
        part1 = [i for i in items if i["showTime"].startswith(today) and i["showTime"][11:16] >= "08:00"]
        tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        part2 = [i for i in items if i["showTime"].startswith(tomorrow) and i["showTime"][11:16] <= "00:30"]
        return part1 + part2
    else:
        return items


def filter_by_hours(items: list, hours: int) -> list:
    """过滤出过去N小时内的快讯（不受session时段限制）"""
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    return [i for i in items if i["showTime"] >= cutoff_str]


def dedup_news(items: list) -> list:
    """
    去重合并：
    1. 同一事件多条播报 → 合并（基于标题相似度）
    2. 盘中价格刷新 → 只保留最新一条
    """
    # 价格刷新模式：标题只有数字/百分比变化的
    price_patterns = [
        r"^(标普500|纳斯达克|道指|恒指|沪指|创业板|科创50).*[涨跌]",
        r"^(WTI|布伦特|现货黄金|现货白银|美元指数).*[涨跌]",
        r"^(SpaceX).*(预[示计]开盘|股票预计|IPO)",
    ]

    # 按主题分组
    price_groups = defaultdict(list)  # key -> [items]
    normal_items = []

    for item in items:
        title = item["title"]
        matched = False
        for pattern in price_patterns:
            match = re.match(pattern, title)
            if match:
                key = match.group(1)
                price_groups[key].append(item)
                matched = True
                break
        if not matched:
            normal_items.append(item)

    # 每组只保留最新一条（items已按时间倒序）
    deduped = []
    for key, group in price_groups.items():
        # 保留最新的那条（第一条）
        deduped.append(group[0])

    # 对normal_items做标题相似去重（简单版：前10字相同 → 保留更详细的）
    seen_prefixes = {}
    for item in normal_items:
        title = item["title"]
        prefix = title[:10]
        if prefix in seen_prefixes:
            # 保留更长/更详细的那条
            existing = seen_prefixes[prefix]
            if len(title) > len(existing["title"]):
                seen_prefixes[prefix] = item
        else:
            seen_prefixes[prefix] = item

    deduped.extend(seen_prefixes.values())

    # 按时间排序（最新在前）
    deduped.sort(key=lambda x: x["showTime"], reverse=True)
    return deduped


def format_output(items: list) -> str:
    """格式化输出"""
    lines = []
    for item in items:
        t = item["showTime"][11:16]
        title = item["title"]
        summary = item.get("summary", "")
        # 如果摘要比标题长很多且有实质内容，附上
        if summary and len(summary) > len(title) + 20:
            lines.append(f"{t} | {title}")
            # 摘要截取前150字
            short_summary = summary[:150] + "..." if len(summary) > 150 else summary
            lines.append(f"     └ {short_summary}")
        else:
            lines.append(f"{t} | {title}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="东财快讯拉取器")
    parser.add_argument("--session", choices=["morning", "noon", "after", "full"],
                        default="after", help="交易时段 (default: after)")
    parser.add_argument("--hours", type=int, default=None,
                        help="拉取过去N小时的快讯（覆盖--session）")
    parser.add_argument("--pages", type=int, default=None,
                        help="翻页数 (默认根据session自动决定)")
    parser.add_argument("--raw", action="store_true",
                        help="不去重，输出原始全量")
    parser.add_argument("--json", action="store_true",
                        help="输出JSON格式（供其他脚本使用）")
    args = parser.parse_args()

    # 根据模式决定翻页数（每页~200条，~30条/小时 → 每小时约0.15页）
    if args.pages:
        pages = args.pages
    elif args.hours:
        pages = max(1, (args.hours * 35) // 200 + 1)
    else:
        pages_map = {"morning": 3, "noon": 1, "after": 1, "full": 4}
        pages = pages_map[args.session]

    session_names = {
        "morning": "盘前(隔夜18:30~今早08:30)",
        "noon": "午盘(08:30~12:00)",
        "after": "盘后(15:00~18:30)",
        "full": "全天",
    }

    print(f"📡 拉取东财快讯... ({pages}页)")
    all_items = fetch_news(pages)
    print(f"   获取 {len(all_items)} 条原始快讯")

    # 按时段/小时过滤
    if args.hours:
        filtered = filter_by_hours(all_items, args.hours)
        display_name = f"过去{args.hours}小时"
    else:
        filtered = filter_by_session(all_items, args.session)
        display_name = session_names[args.session]
    print(f"   {display_name} 共 {len(filtered)} 条")

    if not filtered:
        print("   ⚠️ 该时段无数据（可能还没到该时段，或需要增加翻页数）")
        return

    # 去重
    if args.raw:
        output_items = filtered
    else:
        output_items = dedup_news(filtered)
        if len(output_items) < len(filtered):
            print(f"   去重后 {len(output_items)} 条（合并了 {len(filtered) - len(output_items)} 条重复）")

    print(f"\n{'='*60}")
    print(f"  {display_name} | {output_items[0]['showTime'][:10]}")
    print(f"{'='*60}\n")

    if args.json:
        # JSON输出供其他脚本使用
        output = [{
            "time": item["showTime"],
            "title": item["title"],
            "summary": item.get("summary", ""),
        } for item in output_items]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(format_output(output_items))

    print(f"\n{'='*60}")
    print(f"  共 {len(output_items)} 条 | 供 theme-discovery skill 分析")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
