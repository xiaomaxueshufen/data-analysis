from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from statistics import NormalDist

from da_common import choose_date_field, choose_main_table, load_tables, parse_date_series, to_numeric, write_json


def baseline_for(
    values: pd.DataFrame,
    date_field: str,
    metric_field_name: str,
    target: pd.Timestamp,
    window_days: int = 56,
    min_same_weekday: int = 2,
    fallback_rows: int = 28,
) -> dict:
    dates = values[date_field]
    metric = to_numeric(values[metric_field_name])
    history = values[(dates < target) & (dates >= target - pd.Timedelta(days=window_days))]
    same_weekday = history[dates.loc[history.index].dt.dayofweek == target.dayofweek]
    chosen = same_weekday if len(same_weekday) >= min_same_weekday else history.tail(fallback_rows)
    series = metric.loc[chosen.index] if len(chosen) else metric
    if series.empty:
        return {"value": None, "n": 0, "method": "unavailable", "mad": None, "std": None}
    median = float(series.median())
    deviation_series = (series - median).abs()
    mad = float(deviation_series.median()) if not deviation_series.empty else None
    return {
        "value": median,
        "n": int(len(series)),
        "method": "same_weekday" if len(same_weekday) >= min_same_weekday else "rolling_window",
        "mad": mad,
        "std": float(series.std()) if len(series) > 1 else None,
    }


def deviation(value: float | None, baseline: dict, minimum_relative_scale: float = 0.01) -> dict:
    base = baseline.get("value")
    if value is None or base is None:
        return {"delta": None, "relative": None, "robust_z": None}
    delta = value - base
    scale = max(float(baseline.get("mad") or 0), float(baseline.get("std") or 0) / 3, abs(base) * minimum_relative_scale, 1e-12)
    return {"delta": delta, "relative": delta / base if base else None, "robust_z": delta / (1.4826 * scale)}


def load_frame(data_path: str, config: dict) -> tuple[pd.DataFrame, str]:
    tables = load_tables(data_path)
    name = config.get("sheet") or choose_main_table(tables)
    if name not in tables:
        raise ValueError(f"找不到 sheet：{name}")
    return tables[name]["frame"].copy(), name


def apply_filter(frame: pd.DataFrame, filter_spec: dict | None) -> pd.DataFrame:
    if not filter_spec:
        return frame
    result = frame
    for field, expected in filter_spec.items():
        if field not in result.columns:
            raise ValueError(f"过滤字段不存在：{field}")
        if isinstance(expected, list):
            result = result[result[field].isin(expected)]
        else:
            result = result[result[field] == expected]
    return result


def normal_pvalue(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def op_funnel(frame: pd.DataFrame, config: dict) -> dict:
    stages = config.get("stages", [])
    if len(stages) < 2:
        raise ValueError("funnel_rates 至少需要两个阶段")
    values = []
    previous = None
    for item in stages:
        field = item if isinstance(item, str) else item.get("field")
        name = field if isinstance(item, str) else item.get("name", field)
        if field not in frame.columns:
            raise ValueError(f"阶段字段不存在：{field}")
        count = float(pd.to_numeric(frame[field], errors="coerce").sum())
        values.append({"stage": name, "field": field, "count": count, "rate_from_previous": count / previous if previous else None, "loss_from_previous": previous - count if previous is not None else None})
        previous = count
    return {"op": "funnel_rates", "stages": values, "rows": len(frame)}


def op_contribution(frame: pd.DataFrame, config: dict) -> dict:
    group = config["group_field"]
    value_field = config["value_field"]
    current = apply_filter(frame, config.get("current_filter"))
    baseline = apply_filter(frame, config.get("baseline_filter"))
    current_group = current.groupby(group, dropna=False)[value_field].sum()
    baseline_group = baseline.groupby(group, dropna=False)[value_field].sum()
    groups = sorted(set(current_group.index.tolist()) | set(baseline_group.index.tolist()), key=str)
    total_baseline = float(baseline_group.sum())
    total_current = float(current_group.sum())
    gap = total_current - total_baseline
    result = []
    for value in groups:
        before = float(baseline_group.get(value, 0))
        after = float(current_group.get(value, 0))
        delta = after - before
        result.append({"group": str(value), "baseline": before, "current": after, "delta": delta, "share_of_gap": delta / gap if gap else None, "evidence_id": f"C-{len(result)+1:03d}"})
    return {"op": "contribution", "group_field": group, "value_field": value_field, "total": {"baseline": total_baseline, "current": total_current, "gap": gap}, "groups": sorted(result, key=lambda item: abs(item["delta"]), reverse=True)}


def op_ratio_decomp(frame: pd.DataFrame, config: dict) -> dict:
    group = config["group_field"]
    numerator = config["numerator_field"]
    denominator = config["denominator_field"]
    current = apply_filter(frame, config.get("current_filter"))
    baseline = apply_filter(frame, config.get("baseline_filter"))
    current_group = current.groupby(group, dropna=False)[[numerator, denominator]].sum()
    baseline_group = baseline.groupby(group, dropna=False)[[numerator, denominator]].sum()
    all_groups = sorted(set(current_group.index.tolist()) | set(baseline_group.index.tolist()), key=str)
    total_current_n = float(current[numerator].sum())
    total_current_d = float(current[denominator].sum())
    total_baseline_n = float(baseline[numerator].sum())
    total_baseline_d = float(baseline[denominator].sum())
    current_rate = total_current_n / total_current_d if total_current_d else None
    baseline_rate = total_baseline_n / total_baseline_d if total_baseline_d else None
    rows = []
    for value in all_groups:
        bn = float(baseline_group[numerator].get(value, 0))
        bd = float(baseline_group[denominator].get(value, 0))
        cn = float(current_group[numerator].get(value, 0))
        cd = float(current_group[denominator].get(value, 0))
        br = bn / bd if bd else None
        cr = cn / cd if cd else None
        bw = bd / total_baseline_d if total_baseline_d else 0
        cw = cd / total_current_d if total_current_d else 0
        within = bw * (cr - br) if br is not None and cr is not None else 0
        mix = (cw - bw) * br if br is not None else 0
        rows.append({"group": str(value), "baseline_rate": br, "current_rate": cr, "baseline_weight": bw, "current_weight": cw, "within_group": within, "mix_shift": mix, "contribution": within + mix})
    within_total = sum(row["within_group"] for row in rows)
    mix_total = sum(row["mix_shift"] for row in rows)
    delta = (current_rate - baseline_rate) if current_rate is not None and baseline_rate is not None else None
    return {"op": "ratio_decomp", "ratio": {"numerator": numerator, "denominator": denominator, "baseline": baseline_rate, "current": current_rate, "delta": delta}, "components": {"within_group": within_total, "mix_shift": mix_total, "interaction_residual": delta - within_total - mix_total if delta is not None else None}, "groups": sorted(rows, key=lambda item: abs(item["contribution"]), reverse=True)}


def op_ab_effect(frame: pd.DataFrame, config: dict) -> dict:
    variant = config["variant_field"]
    metric = config["metric_field"]
    control = config.get("control", "A")
    treatment = config.get("treatment", "B")
    control_values = to_numeric(frame.loc[frame[variant] == control, metric]).dropna()
    treatment_values = to_numeric(frame.loc[frame[variant] == treatment, metric]).dropna()
    if control_values.empty or treatment_values.empty:
        raise ValueError("处理组或对照组没有有效样本")
    metric_type = config.get("metric_type", "binary")
    confidence_level = float(config.get("confidence_level", 0.95))
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level 必须位于 0 和 1 之间")
    z_critical = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    if metric_type == "binary":
        control_mean, treatment_mean = float(control_values.mean()), float(treatment_values.mean())
        pooled = (control_values.sum() + treatment_values.sum()) / (len(control_values) + len(treatment_values))
        se = math.sqrt(max(pooled * (1 - pooled) * (1 / len(control_values) + 1 / len(treatment_values)), 0))
    else:
        control_mean, treatment_mean = float(control_values.mean()), float(treatment_values.mean())
        se = math.sqrt(max(control_values.var(ddof=1) / len(control_values) + treatment_values.var(ddof=1) / len(treatment_values), 0))
    effect = treatment_mean - control_mean
    z = effect / se if se else None
    ci = [effect - z_critical * se, effect + z_critical * se] if se else [None, None]
    return {"op": "ab_effect", "control": {"label": control, "n": len(control_values), "mean": control_mean}, "treatment": {"label": treatment, "n": len(treatment_values), "mean": treatment_mean}, "effect": effect, "ci": ci, "confidence_level": confidence_level, "z": z, "p_value": normal_pvalue(z) if z is not None else None, "metric_type": metric_type}


def op_segment_profile(frame: pd.DataFrame, config: dict) -> dict:
    segment = config["segment_field"]
    output = []
    grouped = frame.groupby(segment, dropna=False)
    total = len(frame)
    for value, group in grouped:
        item = {"segment": str(value), "size": int(len(group)), "share": len(group) / total if total else None}
        for spec in config.get("metrics", []):
            field = spec["field"]
            agg = spec.get("agg", "mean")
            values = to_numeric(group[field])
            item[spec.get("name", field)] = float(values.sum() if agg == "sum" else values.mean() if agg == "mean" else values.count())
        output.append(item)
    return {"op": "segment_profile", "segment_field": segment, "segments": sorted(output, key=lambda item: item["size"], reverse=True)}


def op_anomaly_scan(frame: pd.DataFrame, config: dict) -> dict:
    date_field = config.get("date_field") or choose_date_field(frame)
    metric = config["metric_field"]
    if not date_field:
        raise ValueError("anomaly_scan 需要时间字段")
    work = frame[[date_field, metric]].copy()
    work[date_field] = parse_date_series(work[date_field]).dt.normalize()
    work[metric] = to_numeric(work[metric])
    work = work.dropna().groupby(date_field, as_index=False)[metric].sum().sort_values(date_field)
    work["__date"] = work[date_field]
    baseline_window_days = int(config.get("baseline_window_days", 56))
    minimum_relative_scale = float(config.get("minimum_relative_scale", 0.01))
    rows = []
    for _, row in work.iterrows():
        baseline = baseline_for(
            work,
            "__date",
            metric,
            row["__date"],
            window_days=baseline_window_days,
            min_same_weekday=int(config.get("min_same_weekday", 2)),
            fallback_rows=int(config.get("baseline_fallback_rows", 28)),
        )
        deviation_result = deviation(float(row[metric]), baseline, minimum_relative_scale)
        rows.append({"date": row[date_field].strftime("%Y-%m-%d"), "value": float(row[metric]), "baseline": baseline, "deviation": deviation_result})
    return {"op": "anomaly_scan", "metric": metric, "date_field": date_field, "rows": sorted(rows, key=lambda item: abs(item["deviation"].get("robust_z") or 0), reverse=True)}


OPERATORS = {"funnel_rates": op_funnel, "contribution": op_contribution, "ratio_decomp": op_ratio_decomp, "ab_effect": op_ab_effect, "segment_profile": op_segment_profile, "anomaly_scan": op_anomaly_scan}


def main() -> None:
    parser = argparse.ArgumentParser(description="通用数据分析算子入口")
    parser.add_argument("operator", choices=sorted(OPERATORS))
    parser.add_argument("--data", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    frame, sheet = load_frame(args.data, config)
    result = OPERATORS[args.operator](frame, config)
    result["sheet"] = sheet
    result["config"] = config
    write_json(args.out, result)


if __name__ == "__main__":
    main()
