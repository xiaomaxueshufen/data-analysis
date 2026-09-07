from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from da_common import (
    choose_date_field,
    choose_main_table,
    infer_roles,
    load_tables,
    metric_field,
    parse_date_series,
    robust_stats,
    write_json,
)


def date_values(frame: pd.DataFrame, field: str | None) -> pd.Series:
    if not field:
        return pd.Series(dtype="datetime64[ns]")
    return parse_date_series(frame[field]).dt.normalize()


def quality_gate(profile: dict, data_path: str) -> dict:
    tables = load_tables(data_path)
    main_name = profile.get("main_table") or choose_main_table(tables)
    main = tables[main_name]
    flags = []
    excluded_dates: set[str] = set()
    key_fields = []
    for sheet_name, table in tables.items():
        frame = table["frame"]
        roles = infer_roles([str(column) for column in frame.columns])
        date_field = choose_date_field(frame)
        dates = date_values(frame, date_field)
        if date_field and not dates.empty:
            duplicate_count = int(dates.duplicated().sum())
            if sheet_name == main_name and duplicate_count > 0:
                flags.append({
                    "type": "duplicate_date",
                    "severity": "warning",
                    "sheet": sheet_name,
                    "field": date_field,
                    "count": duplicate_count,
                    "message": "主表同一天有多行，需确认是否存在隐藏维度或重复写入。",
                })
            unique_dates = sorted(dates.dropna().unique())
            if len(unique_dates) > 1:
                expected = pd.date_range(unique_dates[0], unique_dates[-1], freq="D")
                missing = sorted(set(expected) - set(unique_dates))
                if missing:
                    flags.append({
                        "type": "date_gap",
                        "severity": "warning",
                        "sheet": sheet_name,
                        "field": date_field,
                        "dates": [date.strftime("%Y-%m-%d") for date in missing[:50]],
                        "count": len(missing),
                        "message": "日期区间存在缺口，不能默认缺口日为零。",
                    })
        for field in frame.columns:
            missing_rate = float(frame[field].isna().mean()) if len(frame) else 0.0
            if missing_rate >= 0.2:
                flags.append({
                    "type": "field_missing",
                    "severity": "warning" if missing_rate < 0.5 else "error",
                    "sheet": sheet_name,
                    "field": str(field),
                    "missing_rate": missing_rate,
                    "message": "字段缺失比例较高，相关指标需要降级或排除。",
                })
        for role in ["success_rate", "pay_start_rate", "gateway_availability", "inventory_availability", "delay_minutes", "missing_rate", "risk_block_rate"]:
            field = metric_field(table, role)
            if field:
                key_fields.append({"sheet": sheet_name, "role": role, "field": field})
                values = pd.to_numeric(frame[field], errors="coerce")
                stats = robust_stats(values)
                if stats["n"] >= 4 and stats["mad"] is not None:
                    scale = max(float(stats["mad"] or 0), float(stats["std"] or 0) / 3, 1e-12)
                    high = values[(values - float(stats["median"])) / (1.4826 * scale) > 4]
                    if len(high):
                        high_dates = dates.loc[high.index] if len(dates) else pd.Series(dtype="datetime64[ns]")
                        rows = [value.strftime("%Y-%m-%d") for value in high_dates.dropna().unique()]
                        flags.append({
                            "type": "metric_outlier",
                            "severity": "warning",
                            "sheet": sheet_name,
                            "role": role,
                            "field": field,
                            "dates": rows[:50],
                            "count": len(rows),
                            "message": "字段存在稳健统计意义上的极端值，需结合业务与数据链路判断。",
                        })
                if role in {"delay_minutes", "missing_rate"}:
                    if values.notna().any() and stats["median"] is not None:
                        scale = max(float(stats["mad"] or 0), float(stats["std"] or 0) / 3, 1e-12)
                        if role == "delay_minutes":
                            threshold = float(stats["median"]) + 3 * 1.4826 * scale
                        else:
                            threshold = max(0.05, float(stats["median"]) + 3 * 1.4826 * scale)
                        unusual = values[values > threshold]
                        unusual_dates = dates.loc[unusual.index] if len(dates) else pd.Series(dtype="datetime64[ns]")
                        should_exclude = role == "missing_rate" or (role == "delay_minutes" and threshold >= 120)
                        if should_exclude:
                            for date in unusual_dates.dropna().unique():
                                excluded_dates.add(date.strftime("%Y-%m-%d"))
    for field_role in ["success_rate", "pay_start_rate", "gateway_availability"]:
        field = metric_field(main, field_role)
        if field:
            key_fields.append({"sheet": main_name, "role": field_role, "field": field})
            missing = main["frame"][field].isna()
            date_field = choose_date_field(main["frame"])
            dates = date_values(main["frame"], date_field)
            for date in dates.loc[missing].dropna().unique():
                excluded_dates.add(date.strftime("%Y-%m-%d"))
    if not any(flag["severity"] == "error" for flag in flags):
        status = "DEGRADED" if flags else "PASS"
    else:
        status = "BLOCK" if not key_fields else "DEGRADED"
    return {
        "schema_version": "1.0",
        "status": status,
        "main_table": main_name,
        "key_fields": key_fields,
        "flags": flags,
        "excluded_dates": sorted(excluded_dates),
        "policy": {
            "excluded_dates_are_not_used_for_business_anomaly": True,
            "ratio_is_recomputed_from_numerator_denominator_when_available": True,
        },
        "summary": {
            "flag_count": len(flags),
            "excluded_date_count": len(excluded_dates),
            "message": "质量门禁完成；请在语义合同确认字段角色后再升级解释层级。",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="数据质量门禁")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import json

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    write_json(args.out, quality_gate(profile, args.data))


if __name__ == "__main__":
    main()
