from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from da_common import (
    choose_date_field,
    choose_main_table,
    infer_roles,
    load_tables,
    metric_field,
    parse_date_series,
    robust_stats,
    source_ref,
    to_numeric,
    write_json,
)


KEY_ROLES = [
    "visitors",
    "registered",
    "browse",
    "cart",
    "pay_start",
    "pay_success",
    "pay_fail",
    "success_rate",
    "register_rate",
    "browse_rate",
    "cart_rate",
    "pay_start_rate",
    "gateway_availability",
    "inventory_availability",
    "peak_index",
    "delay_minutes",
    "missing_rate",
    "risk_block_rate",
]


def safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def fmt_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def baseline_for(values: pd.DataFrame, date_field: str, metric_field_name: str, target: pd.Timestamp) -> dict:
    dates = values[date_field]
    metric = to_numeric(values[metric_field_name])
    history = values[(dates < target) & (dates >= target - pd.Timedelta(days=56))]
    same_weekday = history[dates.loc[history.index].dt.dayofweek == target.dayofweek]
    chosen = same_weekday if len(same_weekday) >= 2 else history.tail(28)
    stats = robust_stats(metric.loc[chosen.index]) if len(chosen) else robust_stats(pd.Series(dtype=float))
    baseline = stats["median"]
    if baseline is None:
        return {"value": None, "n": 0, "method": "unavailable", "mad": None, "std": None}
    return {"value": baseline, "n": int(stats["n"]), "method": "same_weekday" if len(same_weekday) >= 2 else "rolling_window", "mad": stats["mad"], "std": stats["std"]}


def deviation(value: float | None, baseline: dict) -> dict:
    base = baseline.get("value")
    if value is None or base is None:
        return {"delta": None, "relative": None, "robust_z": None}
    delta = value - base
    scale = max(float(baseline.get("mad") or 0), float(baseline.get("std") or 0) / 3, abs(base) * 0.01, 1e-12)
    return {"delta": delta, "relative": delta / base if base else None, "robust_z": delta / (1.4826 * scale)}


def make_evidence(evidence_id: str, sheet: str, header_row: int, row_number: int, field: str, value: Any, detail: str, extra: dict | None = None) -> dict:
    payload = {
        "evidence_id": evidence_id,
        "type": "calculation",
        "source": source_ref(sheet, header_row, row_number),
        "field": field,
        "value": safe_float(value) if isinstance(value, (int, float, np.number)) else value,
        "detail": detail,
    }
    if extra:
        payload.update(extra)
    return payload


def find_environment_table(tables: dict[str, dict[str, Any]], exclude: str) -> str | None:
    scored = []
    for name, table in tables.items():
        if name == exclude:
            continue
        date = choose_date_field(table["frame"])
        gateway = metric_field(table, "gateway_availability")
        delay = metric_field(table, "delay_minutes")
        score = (4 if date else 0) + (3 if gateway else 0) + (2 if delay else 0)
        if score:
            scored.append((score, name))
    return sorted(scored, reverse=True)[0][1] if scored else None


def aggregate_daily(frame: pd.DataFrame, date_field: str, roles: dict[str, str | None]) -> pd.DataFrame:
    work = frame.copy()
    work["__date"] = parse_date_series(work[date_field]).dt.normalize()
    work = work.dropna(subset=["__date"])
    rows = []
    for date, group in work.groupby("__date", sort=True):
        row: dict[str, Any] = {"date": fmt_date(date), "__date": date}
        for role, field in roles.items():
            if not field:
                continue
            values = to_numeric(group[field])
            if role.endswith("rate") or role in {"gateway_availability", "inventory_availability", "peak_index", "delay_minutes", "missing_rate", "risk_block_rate"}:
                row[role] = safe_float(values.mean())
            else:
                row[role] = safe_float(values.sum())
        rows.append(row)
    return pd.DataFrame(rows)


def build_funnel(daily: pd.DataFrame, roles: dict[str, str | None]) -> dict:
    stage_roles = ["visitors", "registered", "browse", "cart", "pay_start", "pay_success"]
    available = [role for role in stage_roles if role in daily.columns]
    if len(available) < 2:
        return {"available": False, "reason": "少于两个可识别阶段计数字段"}
    current = daily.iloc[-1]
    stages = []
    previous_value = None
    for role in available:
        value = safe_float(current.get(role))
        rate = value / previous_value if value is not None and previous_value else None
        stages.append({"stage": role, "count": value, "rate_from_previous": rate, "loss_from_previous": previous_value - value if value is not None and previous_value is not None else None})
        previous_value = value
    return {"available": True, "reference_date": current.get("date"), "stages": stages}


def candidate_events(daily: pd.DataFrame, metric_names: list[str], excluded_dates: set[str], contract: dict | None = None) -> tuple[list[dict], list[dict]]:
    contract = contract or {}
    materiality = contract.get("materiality", {}) if isinstance(contract, dict) else {}
    rate_delta_threshold = float(materiality.get("rate_delta", 0.02))
    count_relative_threshold = float(materiality.get("count_relative", 0.15))
    count_z_threshold = float(materiality.get("count_z", 4.0))
    evidence_rows = []
    scoring_metrics = [name for name in metric_names if name not in {"delay_minutes", "missing_rate", "missing_count"}]
    metric_records: dict[str, list[dict]] = {name: [] for name in metric_names}
    for metric_name in metric_names:
        for idx, row in daily.iterrows():
            date = row["__date"]
            baseline = baseline_for(daily, "__date", metric_name, date)
            value = safe_float(row.get(metric_name))
            metric_records[metric_name].append({"date": fmt_date(date), "value": value, "baseline": baseline, "deviation": deviation(value, baseline)})
    combined = {}
    for metric_name, records in metric_records.items():
        for record in records:
            date = record["date"]
            combined.setdefault(date, {"date": date, "metrics": [], "score": 0.0})
            z = record["deviation"].get("robust_z")
            if z is not None and metric_name in scoring_metrics:
                combined[date]["score"] = max(combined[date]["score"], abs(float(z)))
            if metric_name in scoring_metrics or date in excluded_dates:
                combined[date]["metrics"].append({"metric": metric_name, **record})
    primary_name = "success_rate" if "success_rate" in metric_records else next((name for name in metric_names if name.endswith("rate")), None)
    count_names = {"visitors", "registered", "browse", "cart", "pay_start", "pay_success", "pay_fail"}
    selected = []
    for item in combined.values():
        records = {record.get("metric"): record for record in item.get("metrics", [])}
        primary = records.get(primary_name) if primary_name else None
        primary_delta = primary.get("deviation", {}).get("delta") if primary else None
        primary_z = primary.get("deviation", {}).get("robust_z") if primary else None
        primary_material = primary_delta is not None and abs(float(primary_delta)) >= rate_delta_threshold
        count_material = any(
            record.get("metric") in count_names
            and record.get("deviation", {}).get("relative") is not None
            and abs(float(record["deviation"]["relative"])) >= count_relative_threshold
            and record.get("deviation", {}).get("robust_z") is not None
            and abs(float(record["deviation"]["robust_z"])) >= count_z_threshold
            for record in records.values()
        )
        stage_material = False
        pay_start_record = records.get("pay_start_rate")
        if pay_start_record and pay_start_record.get("deviation", {}).get("delta") is not None:
            stage_material = float(pay_start_record["deviation"]["delta"]) <= -rate_delta_threshold * 2.5
        traffic_material = False
        visitors_record = records.get("visitors")
        if visitors_record and primary_delta is not None and visitors_record.get("deviation", {}).get("relative") is not None:
            traffic_material = float(visitors_record["deviation"]["relative"]) >= 0.25 and float(primary_delta) <= -rate_delta_threshold * 0.75
        item["selection_reasons"] = []
        if item["date"] in excluded_dates:
            item["selection_reasons"].append("quality_exclusion")
        if primary_material:
            item["selection_reasons"].append("primary_metric_materiality")
        if primary_name is None and count_material:
            item["selection_reasons"].append("count_metric_materiality")
        if stage_material:
            item["selection_reasons"].append("funnel_stage_materiality")
        if traffic_material:
            item["selection_reasons"].append("traffic_quality_pattern")
        if item["selection_reasons"]:
            selected.append(item)
    ranked = sorted(selected, key=lambda item: item["score"], reverse=True)
    selected = ranked[:12]
    selected_dates = {item["date"] for item in selected}
    for item in ranked:
        if item["date"] in excluded_dates and item["date"] not in selected_dates:
            selected.append(item)
    return selected, evidence_rows


def make_mechanism_candidates(event: dict, excluded: bool, contract: dict | None = None) -> list[dict]:
    contract = contract or {}
    materiality = contract.get("materiality", {}) if isinstance(contract, dict) else {}
    rate_delta_threshold = float(materiality.get("rate_delta", 0.02))
    values = {item["metric"]: item for item in event.get("metrics", [])}
    candidates = []
    success = values.get("success_rate")
    gateway = values.get("gateway_availability")
    visitors = values.get("visitors")
    pay_start = values.get("pay_start_rate")
    inventory = values.get("inventory_availability")
    peak = values.get("peak_index")
    risk = values.get("risk_block_rate")
    delay = values.get("delay_minutes")
    missing = values.get("missing_rate")
    if excluded:
        candidates.append({"statement": "数据延迟或字段缺失与当前日期同步异常，业务指标变化应先按数据质量事故处理。", "status": "supported_candidate", "confidence": "high", "evidence_ids": []})
        return candidates
    success_delta = success.get("deviation", {}).get("delta") if success else None
    gateway_delta = gateway.get("deviation", {}).get("delta") if gateway else None
    if success and gateway and success_delta is not None and gateway_delta is not None and success_delta <= -rate_delta_threshold and gateway_delta <= -0.01:
        candidates.append({"statement": "支付成功率与支付网关可用率在同日向下偏离，支付链路是高置信机制候选，但仍需核对网关日志与路由明细。", "status": "supported_candidate", "confidence": "high", "evidence_roles": ["success_rate", "gateway_availability"], "evidence_ids": []})
    if success and pay_start and inventory and peak and success_delta is not None and pay_start["deviation"]["delta"] is not None and inventory["deviation"]["delta"] is not None and peak["deviation"]["delta"] is not None and success_delta <= -rate_delta_threshold * 0.75 and pay_start["deviation"]["delta"] <= -rate_delta_threshold * 2.5 and inventory["deviation"]["delta"] <= -rate_delta_threshold * 2.5 and peak["deviation"]["delta"] >= 0.2:
        candidates.append({"statement": "支付发起率、库存可售率与订单峰值指数同日变化，履约或库存压力是待验证候选；网关指标应作为排除项。", "status": "supported_candidate", "confidence": "medium", "evidence_roles": ["success_rate", "pay_start_rate", "inventory_availability", "peak_index"], "evidence_ids": []})
    if success and risk and success_delta is not None and risk["deviation"]["delta"] is not None and success_delta <= -rate_delta_threshold and risk["deviation"]["delta"] >= max(rate_delta_threshold, 0.01):
        candidates.append({"statement": "风控拦截率上升与支付成功率下降同步出现，风控策略或规则变化是待验证候选，不能仅凭共现确认因果。", "status": "supported_candidate", "confidence": "medium", "evidence_roles": ["success_rate", "risk_block_rate"], "evidence_ids": []})
    if success and visitors and success_delta is not None and visitors["deviation"]["relative"] is not None and success_delta <= -rate_delta_threshold * 0.75 and visitors["deviation"]["relative"] >= 0.25 and (not gateway or gateway["deviation"]["delta"] is None or abs(gateway["deviation"]["delta"]) < 0.01):
        candidates.append({"statement": "访问量放大但支付成功率下降，流量结构或低意向流量是待验证候选，需要按渠道和新老用户拆解。", "status": "supported_candidate", "confidence": "medium", "evidence_roles": ["visitors", "success_rate", "gateway_availability"], "evidence_ids": []})
    return candidates


def analyze(data_path: str, profile: dict, contract: dict, quality: dict, plan: dict) -> dict:
    tables = load_tables(data_path)
    main_name = profile.get("main_table") or choose_main_table(tables)
    main = tables[main_name]
    date_field = choose_date_field(main["frame"])
    if not date_field:
        return {"status": "BLOCK", "reason": "没有可识别的时间列", "events": [], "evidence": []}
    roles = {role: metric_field(main, role, contract) for role in KEY_ROLES}
    daily = aggregate_daily(main["frame"], date_field, roles)
    metric_names = [role for role, field in roles.items() if field and role in daily.columns]
    primary = "success_rate" if "success_rate" in metric_names else next((name for name in metric_names if name.endswith("rate")), metric_names[0] if metric_names else None)
    excluded_dates = set(quality.get("excluded_dates", []))
    events, _ = candidate_events(daily, metric_names, excluded_dates, contract)
    environment_name = find_environment_table(tables, main_name)
    environment = []
    environment_daily = None
    if environment_name:
        env = tables[environment_name]
        env_date = choose_date_field(env["frame"])
        env_roles = {role: metric_field(env, role, contract) for role in ["gateway_availability", "delay_minutes", "missing_rate", "activity", "route"]}
        if env_date:
            env_daily = aggregate_daily(env["frame"], env_date, env_roles)
            environment_daily = env_daily
            environment = [
                {key: value for key, value in row.items() if key != "__date"}
                for row in env_daily.to_dict(orient="records")
            ]
    evidence = []
    evidence_counter = 1
    for idx, row in main["frame"].iterrows():
        date = fmt_date(parse_date_series(main["frame"][date_field]).iloc[idx])
        if not date:
            continue
        for role in metric_names:
            field = roles[role]
            if field and field in main["frame"].columns:
                evidence.append(make_evidence(f"E{evidence_counter:03d}", main_name, main["header_row"], idx, field, row[field], f"{date} 的 {role} 原始字段值", {"date": date, "role": role}))
                evidence_counter += 1
    support_series = {}
    for support_name, support_table in tables.items():
        if support_name == main_name:
            continue
        support_date = choose_date_field(support_table["frame"])
        if not support_date:
            continue
        support_roles = {role: metric_field(support_table, role, contract) for role in ["gateway_availability", "inventory_availability", "peak_index", "delay_minutes", "missing_rate", "risk_block_rate"]}
        if not any(support_roles.values()):
            continue
        support_daily = aggregate_daily(support_table["frame"], support_date, support_roles)
        for _, support_row in support_daily.iterrows():
            for role in support_roles:
                if role not in support_daily.columns:
                    continue
                value = safe_float(support_row.get(role))
                if value is None:
                    continue
                baseline = baseline_for(support_daily, "__date", role, support_row["__date"])
                support_series.setdefault((support_row["date"], role), {"metric": role, "value": value, "baseline": baseline, "deviation": deviation(value, baseline), "source_table": support_name})
    for event in events:
        if environment_daily is not None:
            env_match = environment_daily[environment_daily["date"] == event["date"]]
            if not env_match.empty:
                env_row = env_match.iloc[0]
                for role in ["gateway_availability", "inventory_availability", "delay_minutes", "missing_rate", "risk_block_rate"]:
                    if role not in env_daily.columns:
                        continue
                    value = safe_float(env_row.get(role))
                    baseline = baseline_for(environment_daily, "__date", role, env_row["__date"])
                    event["metrics"].append({"metric": role, "value": value, "baseline": baseline, "deviation": deviation(value, baseline), "source_table": environment_name})
        existing_metrics = {item.get("metric") for item in event.get("metrics", [])}
        for (date, role), item in support_series.items():
            if date == event["date"] and role not in existing_metrics:
                event["metrics"].append(item)
        event["excluded_by_quality"] = event["date"] in excluded_dates
        event["evidence_ids"] = [item["evidence_id"] for item in evidence if item.get("date") == event["date"]][:12]
        event["mechanism_candidates"] = make_mechanism_candidates(event, event["excluded_by_quality"], contract)
        evidence_by_role = {}
        for item in evidence:
            if item.get("date") == event["date"]:
                evidence_by_role.setdefault(item.get("role"), []).append(item.get("evidence_id"))
        for candidate in event["mechanism_candidates"]:
            candidate["evidence_ids"] = [evidence_id for role in candidate.pop("evidence_roles", []) for evidence_id in evidence_by_role.get(role, [])]
        event["limitations"] = ["机制候选来自可观测字段同步关系，不能替代实验或业务事件确认。"]
    time_series = []
    for _, row in daily.iterrows():
        item = {"date": row["date"]}
        if primary:
            baseline = baseline_for(daily, "__date", primary, row["__date"])
            item.update({"value": safe_float(row.get(primary)), "baseline": baseline.get("value"), "robust_z": deviation(safe_float(row.get(primary)), baseline).get("robust_z")})
        time_series.append(item)
    return {
        "schema_version": "1.0",
        "status": "DEGRADED" if quality.get("status") != "PASS" else "PASS",
        "main_table": main_name,
        "main_date_field": date_field,
        "primary_metric": {"role": primary, "field": roles.get(primary) if primary else None},
        "recognized_fields": {role: field for role, field in roles.items() if field},
        "daily": [{key: value for key, value in row.items() if key != "__date"} for row in daily.to_dict(orient="records")],
        "time_series": time_series,
        "events": events,
        "funnel": build_funnel(daily, roles),
        "environment_table": environment_name,
        "environment": environment,
        "quality_excluded_dates": sorted(excluded_dates),
        "evidence": evidence,
        "auto_claims": [
            {
                "claim_id": f"AC{index:03d}",
                "statement": f"{event['date']} 是需要复核的候选日期，异常评分为 {event['score']:.2f}。",
                "level": "L1",
                "status": "data_quality" if event["excluded_by_quality"] else "comparison",
                "limitations": event["limitations"],
            }
            for index, event in enumerate(events, start=1)
        ],
        "notes": [
            "事件和机制候选由可观测字段与稳健基线计算生成，不包含生成数据时的模拟真值。",
            "报告模型应根据用户问题和语义合同补充维度贡献、实验或因果检验，并保持候选/假设措辞。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="通用数据分析基础算子")
    parser.add_argument("--data", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--contract", required=False)
    parser.add_argument("--quality", required=False)
    parser.add_argument("--plan", required=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8")) if args.contract and Path(args.contract).exists() else {}
    quality = json.loads(Path(args.quality).read_text(encoding="utf-8")) if args.quality and Path(args.quality).exists() else {}
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8")) if args.plan and Path(args.plan).exists() else {}
    write_json(args.out, analyze(args.data, profile, contract, quality, plan))


if __name__ == "__main__":
    main()
