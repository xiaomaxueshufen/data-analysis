#!/usr/bin/env python3
"""复核「大单解释掉多少异动」需要原始明细，聚合表里看不到单笔订单。

这个检查不参与 skill 运行，只在有人想复核报告里的大单结论时用：
    python examples/case_study/check_top_orders.py --raw /path/to/online_retail_II.csv --date 2011-12-09

原始明细不在仓库里（约 90MB），获取方式与 sha256 见 build_dataset.py。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="按日期打印原始明细里最大的单笔订单")
    parser.add_argument("--raw", required=True, help="原始 online_retail_II.csv 路径")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    raw = Path(args.raw).expanduser()
    if not raw.is_file():
        print(f"读不到原始明细：{raw}（获取方式见 build_dataset.py）", file=sys.stderr)
        return 2

    frame = pd.read_csv(raw, parse_dates=["InvoiceDate"])
    frame["金额"] = frame["Quantity"] * frame["Price"]
    day = frame[frame["InvoiceDate"].dt.strftime("%Y-%m-%d") == args.date]
    if day.empty:
        print(f"{args.date} 没有明细")
        return 1

    top = day.nlargest(args.top, "金额")[["Invoice", "StockCode", "Description", "Quantity", "Price", "金额"]]
    print(f"{args.date}：明细 {len(day)} 行，订单 {day['Invoice'].nunique()} 个，金额合计 {day['金额'].sum():,.2f}")
    print(top.to_string(index=False))
    cancelled = frame[(frame["Invoice"].isin(day["Invoice"])) & (frame["Quantity"] < 0)]
    print(f"同发票号在全部日期里的负数量行：{len(cancelled)} 行，金额 {cancelled['金额'].sum():,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
