from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from da_common import (
    choose_date_field,
    choose_main_table,
    file_sha256,
    infer_roles,
    is_numeric_series,
    load_tables,
    parse_date_series,
    robust_stats,
    source_ref,
    write_json,
)


def field_profile(series: pd.Series) -> dict:
    parsed_dates = parse_date_series(series)
    numeric = is_numeric_series(series)
    item = {
        "name": str(series.name),
        "dtype": str(series.dtype),
        "missing_count": int(series.isna().sum()),
        "missing_rate": float(series.isna().mean()) if len(series) else 0.0,
        "unique_count": int(series.nunique(dropna=True)),
        "sample_values": [value for value in series.dropna().head(5).tolist()],
        "is_numeric": bool(numeric),
        "is_date_candidate": bool(parsed_dates.notna().mean() >= 0.8),
    }
    if numeric:
        stats = robust_stats(series)
        item["numeric"] = {
            "min": float(pd.to_numeric(series, errors="coerce").min()),
            "max": float(pd.to_numeric(series, errors="coerce").max()),
            **stats,
        }
    if item["is_date_candidate"]:
        item["date_range"] = {
            "min": parsed_dates.min(),
            "max": parsed_dates.max(),
            "unique_days": int(parsed_dates.dt.normalize().nunique()),
        }
    return item


def profile_data(path: str) -> dict:
    source = Path(path)
    tables = load_tables(source)
    sheet_profiles = []
    for name, table in tables.items():
        frame = table["frame"]
        columns = [str(column) for column in frame.columns]
        date_field = choose_date_field(frame)
        profile = {
            "name": name,
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "header_row_zero_based": int(table["header_row"]),
            "header_status": "detected" if table["header_row"] >= 0 else "header_uncertain",
            "date_field": date_field,
            "roles": {role: values for role, values in infer_roles(columns).items() if values},
            "fields": [field_profile(frame[column]) for column in frame.columns],
            "duplicate_rows": int(frame.duplicated().sum()),
            "source_ref": source_ref(name, table["header_row"]),
        }
        if date_field:
            dates = parse_date_series(frame[date_field]).dropna().dt.normalize()
            profile["date_range"] = {
                "min": dates.min(),
                "max": dates.max(),
                "unique_days": int(dates.nunique()),
                "missing_days_in_span": int(
                    max(0, (dates.max() - dates.min()).days + 1 - dates.nunique())
                ) if not dates.empty else None,
            }
        sheet_profiles.append(profile)
    main = choose_main_table(tables)
    return {
        "schema_version": "1.0",
        "file": {
            "path": str(source.resolve()),
            "name": source.name,
            "suffix": source.suffix.lower(),
            "size_bytes": source.stat().st_size,
            "sha256": file_sha256(source),
        },
        "main_table": main,
        "sheets": sheet_profiles,
        "notes": [
            "字段角色是基于名称和类型的候选识别，必须在语义合同中确认。",
            "画像不包含业务判断，所有异常结论需要进入后续计算步骤。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Excel/CSV 数据结构画像")
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    write_json(args.out, profile_data(args.data))


if __name__ == "__main__":
    main()

