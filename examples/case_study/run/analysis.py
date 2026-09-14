#!/usr/bin/env python3
"""案例的一次性分析代码（对应 SKILL.md「模型可现场写代码，算子只做单点复核」）。

只读 `../data/retail_daily.csv`（已提交的日 × 区域聚合表，含合计行），
输出两类东西：
1. stdout 的 JSON：报告里每个数字的来源；
2. `window_table.csv` + `contribution_config.json`：给 da_ops 的
   `contribution` 算子准备窗口过滤（算子只支持等值/列表过滤，不支持日期区间，
   所以这里把「基线月均窗口 / 当前月窗口」显式落到一列，不猜）。

用法：python examples/case_study/run/analysis.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

RUN_DIR = Path(__file__).resolve().parent
DATA = RUN_DIR.parent / "data" / "retail_daily.csv"
TRUNCATION_DAY = "2011-12-09"
CURRENT_WINDOW = ("2011-11-01", "2011-11-30")
BASELINE_WINDOW = ("2011-08-01", "2011-10-31")
BASELINE_MONTHS = 3


def main() -> None:
    raw = pd.read_csv(DATA, dtype={"日期": str})
    total_row = raw[raw["日期"] == "合计"].iloc[0]
    detail = raw[raw["日期"] != "合计"].copy()
    detail["日期"] = pd.to_datetime(detail["日期"])

    def window(start: str, end: str) -> pd.DataFrame:
        return detail[(detail["日期"] >= start) & (detail["日期"] <= end)]

    current = window(*CURRENT_WINDOW)
    baseline = window(*BASELINE_WINDOW)
    nov_2010 = window("2010-11-01", "2010-11-30")
    dec_2010 = window("2010-12-01", "2010-12-31")
    y2011 = window("2011-01-01", TRUNCATION_DAY)

    daily = detail.groupby("日期", as_index=False)["净收入"].sum()
    monthly = detail.assign(月=detail["日期"].dt.strftime("%Y-%m")).groupby("月")["净收入"].sum()
    region_total = detail.groupby("区域")["净收入"].sum()
    region_current = current.groupby("区域")["净收入"].sum()
    region_baseline_monthly = baseline.groupby("区域")["净收入"].sum() / BASELINE_MONTHS

    trading_days = sorted(detail["日期"].dt.strftime("%Y-%m-%d").unique())
    calendar = pd.date_range(detail["日期"].min(), detail["日期"].max())
    missing_days = sorted(set(d.strftime("%Y-%m-%d") for d in calendar) - set(trading_days))
    saturdays = [d for d in missing_days if pd.Timestamp(d).dayofweek == 5]

    # 滑窗窗口表：给 da_ops contribution 用（基线月均 vs 当前月）
    frames = []
    for label, source, divisor in (("基线", baseline, BASELINE_MONTHS), ("当前", current, 1)):
        part = source.groupby("区域", as_index=False)["净收入"].sum()
        # 基线必须换算成「月均」再和当前月比：3 个月总额 vs 1 个月总额的差额
        # 是窗口长度差，不是业务变化，contribution 会把这种假缺口原样对账出来。
        part["净收入"] = part["净收入"] / divisor
        part["期间"] = label
        frames.append(part)
    window_table = pd.concat(frames, ignore_index=True)[["期间", "区域", "净收入"]]
    window_table.to_csv(RUN_DIR / "window_table.csv", index=False, encoding="utf-8")
    (RUN_DIR / "contribution_config.json").write_text(
        json.dumps({
            "group_field": "区域",
            "value_field": "净收入",
            "current_filter": {"期间": "当前"},
            "baseline_filter": {"期间": "基线"},
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    out = {
        "source_file": str(DATA.name),
        "window": {"start": str(detail["日期"].min().date()), "end": str(detail["日期"].max().date())},
        "detail_rows": int(len(detail)),
        "grand_total": {
            "net_revenue": float(total_row["净收入"]),
            "sales_amount": float(total_row["销售金额"]),
            "returns_amount": float(total_row["退货金额"]),
            "returns_share_of_sales": float(total_row["退货金额"] / total_row["销售金额"]),
            "orders": int(total_row["订单数"]),
            "units": int(total_row["销售件数"]),
            "missing_customer_id_rows": int(total_row["缺客户ID行数"]),
        },
        "missing_customer_id_share": float(total_row["缺客户ID行数"] / 1_021_333),
        "net_revenue_2011_to_truncation": float(y2011["净收入"].sum()),
        "current_month": {
            "window": list(CURRENT_WINDOW),
            "net_revenue": float(current["净收入"].sum()),
        },
        "baseline_monthly_mean": {
            "window": list(BASELINE_WINDOW),
            "months": BASELINE_MONTHS,
            "net_revenue": float(baseline["净收入"].sum() / BASELINE_MONTHS),
        },
        "nov_2011_vs_baseline_monthly_mean": float(
            current["净收入"].sum() / (baseline["净收入"].sum() / BASELINE_MONTHS) - 1
        ),
        "nov_2010": float(nov_2010["净收入"].sum()),
        "nov_2011_vs_nov_2010": float(current["净收入"].sum() / nov_2010["净收入"].sum() - 1),
        "dec_2010": {"net_revenue": float(dec_2010["净收入"].sum()), "days": int(dec_2010["日期"].nunique())},
        "region_share_total": {k: float(v / region_total.sum()) for k, v in region_total.items()},
        "region_current": {k: float(v) for k, v in region_current.items()},
        "region_baseline_monthly": {k: float(v) for k, v in region_baseline_monthly.items()},
        "region_delta_vs_baseline": {
            k: float(region_current[k] - region_baseline_monthly[k]) for k in region_current.index
        },
        "top_months": [{"month": m, "net_revenue": float(v)} for m, v in monthly.sort_values(ascending=False).head(6).items()],
        "top_days": [
            {"date": r["日期"].strftime("%Y-%m-%d"), "net_revenue": float(r["净收入"])}
            for _, r in daily.sort_values("净收入", ascending=False).head(6).iterrows()
        ],
        "truncation_day": {
            "date": TRUNCATION_DAY,
            "net_revenue": float(detail[detail["日期"] == TRUNCATION_DAY]["净收入"].sum()),
            "orders": int(detail[detail["日期"] == TRUNCATION_DAY]["订单数"].sum()),
            "prev_day": float(detail[detail["日期"] == "2011-12-08"]["净收入"].sum()),
        },
        "calendar_gaps": {
            "missing_days": len(missing_days),
            "calendar_days": int(len(calendar)),
            "saturdays_missing": len(saturdays),
            "first_missing": missing_days[:5],
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
