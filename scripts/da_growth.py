"""增长分析类算子：多触点归因、同期群留存、生存/流失、路径、RFM、价格弹性。

本模块只依赖 pandas/numpy 与标准库。所有算子都要求明确的实体粒度和时间窗；
缺少必要字段时抛出结构化错误，不用行业常识补数。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from da_common import parse_date_series, to_numeric


# ---------------------------------------------------------------- 多触点归因

ATTRIBUTION_MODELS = ("first_touch", "last_touch", "linear", "time_decay", "position_based", "shapley")


def _shapley_weights(channels: list[str]) -> dict[str, float]:
    """单条路径内按 Shapley 值分配：等价于路径内去重渠道均分。

    严格 Shapley 需要所有子集的转化期望，单条已转化路径的
    对称解即为参与渠道均分，这是常用的可解释近似。
    """
    unique = list(dict.fromkeys(channels))
    share = 1.0 / len(unique) if unique else 0.0
    return {channel: share for channel in unique}


def op_attribution(frame: pd.DataFrame, config: dict) -> dict:
    """多触点归因：把转化价值按不同模型分配到触点渠道。

    归因是模型化的分配口径，不是因果增量。任何归因结果都不能
    写成"某渠道带来了 X 转化"，只能写成"按某模型口径记为 X"。
    """
    id_field = config["id_field"]
    channel_field = config["channel_field"]
    timestamp_field = config["timestamp_field"]
    for field in (id_field, channel_field, timestamp_field):
        if field not in frame.columns:
            raise ValueError(f"字段不存在：{field}")

    conversion_field = config.get("conversion_field")
    value_field = config.get("value_field")
    if conversion_field and conversion_field not in frame.columns:
        raise ValueError(f"转化标记字段不存在：{conversion_field}")
    if value_field and value_field not in frame.columns:
        raise ValueError(f"转化价值字段不存在：{value_field}")

    models = [str(model) for model in config.get("models", ["first_touch", "last_touch", "linear", "time_decay", "position_based", "shapley"])]
    unknown = set(models) - set(ATTRIBUTION_MODELS)
    if unknown:
        raise ValueError(f"不支持的归因模型：{sorted(unknown)}；可选：{list(ATTRIBUTION_MODELS)}")

    half_life_days = float(config.get("half_life_days", 7.0))
    if half_life_days <= 0:
        raise ValueError("half_life_days 必须为正数")
    lookback_days = config.get("lookback_days")
    position_first = float(config.get("position_first_weight", 0.4))
    position_last = float(config.get("position_last_weight", 0.4))
    if position_first + position_last > 1:
        raise ValueError("position_first_weight 与 position_last_weight 之和不能超过 1")

    work = frame[[id_field, channel_field, timestamp_field] + [f for f in (conversion_field, value_field) if f]].copy()
    work[timestamp_field] = parse_date_series(work[timestamp_field])
    work = work.dropna(subset=[id_field, channel_field, timestamp_field])
    work[channel_field] = work[channel_field].astype(str)
    if work.empty:
        raise ValueError("没有同时具备实体、渠道和时间戳的有效触点")

    totals = {model: {} for model in models}
    path_count = 0
    converted_paths = 0
    total_value = 0.0
    truncated_paths = 0
    single_touch_paths = 0
    path_lengths: list[int] = []

    for _entity, group in work.groupby(id_field, sort=False):
        path_count += 1
        group = group.sort_values(timestamp_field)
        if conversion_field is not None:
            converted_mask = to_numeric(group[conversion_field]).fillna(0) > 0
            if not bool(converted_mask.any()):
                continue
            conversion_index = int(np.flatnonzero(converted_mask.to_numpy())[-1])
            conversion_time = group[timestamp_field].iloc[conversion_index]
            touches = group.iloc[: conversion_index + 1]
        else:
            conversion_time = group[timestamp_field].iloc[-1]
            touches = group
        if lookback_days is not None:
            cutoff = conversion_time - pd.Timedelta(days=float(lookback_days))
            before = len(touches)
            touches = touches[touches[timestamp_field] >= cutoff]
            if len(touches) < before:
                truncated_paths += 1
        if touches.empty:
            continue

        converted_paths += 1
        channels = touches[channel_field].tolist()
        path_lengths.append(len(channels))
        if len(set(channels)) == 1:
            single_touch_paths += 1
        value = float(to_numeric(touches[value_field]).fillna(0).sum()) if value_field else 1.0
        total_value += value
        ages_days = [(conversion_time - stamp).total_seconds() / 86400.0 for stamp in touches[timestamp_field]]

        for model in models:
            weights: dict[str, float] = {}
            if model == "first_touch":
                weights[channels[0]] = 1.0
            elif model == "last_touch":
                weights[channels[-1]] = 1.0
            elif model == "linear":
                share = 1.0 / len(channels)
                for channel in channels:
                    weights[channel] = weights.get(channel, 0.0) + share
            elif model == "time_decay":
                decays = [0.5 ** (max(age, 0.0) / half_life_days) for age in ages_days]
                total_decay = sum(decays)
                if total_decay <= 0:
                    continue
                for channel, decay in zip(channels, decays):
                    weights[channel] = weights.get(channel, 0.0) + decay / total_decay
            elif model == "position_based":
                if len(channels) == 1:
                    weights[channels[0]] = 1.0
                else:
                    middle_total = max(1.0 - position_first - position_last, 0.0)
                    weights[channels[0]] = weights.get(channels[0], 0.0) + position_first
                    weights[channels[-1]] = weights.get(channels[-1], 0.0) + position_last
                    middle = channels[1:-1]
                    if middle:
                        share = middle_total / len(middle)
                        for channel in middle:
                            weights[channel] = weights.get(channel, 0.0) + share
                    else:
                        leftover = middle_total / 2
                        weights[channels[0]] += leftover
                        weights[channels[-1]] += leftover
            else:
                weights = _shapley_weights(channels)
            for channel, weight in weights.items():
                bucket = totals[model]
                bucket[channel] = bucket.get(channel, 0.0) + weight * value

    if converted_paths == 0:
        raise ValueError("没有任何已转化路径，无法做归因分配")

    all_channels = sorted({channel for bucket in totals.values() for channel in bucket})
    rows = []
    for channel in all_channels:
        entry: dict[str, Any] = {"channel": channel}
        for model in models:
            credited = totals[model].get(channel, 0.0)
            entry[model] = credited
            entry[f"{model}_share"] = credited / total_value if total_value else None
        model_values = [entry[model] for model in models]
        entry["model_spread"] = max(model_values) - min(model_values) if model_values else None
        entry["model_disagreement"] = (
            entry["model_spread"] / total_value if total_value and entry["model_spread"] is not None else None
        )
        rows.append(entry)
    rows.sort(key=lambda item: item.get(models[0], 0.0), reverse=True)

    reconciliation = {
        model: {"credited_total": sum(totals[model].values()), "conversion_total": total_value}
        for model in models
    }

    limitations = [
        "归因是价值分配口径，不是因果增量；没有对照或实验时不得写成某渠道带来增量。",
        "不同模型对同一渠道给出的份额差异（model_disagreement）越大，说明该渠道的贡献越依赖模型假设。",
        "路径只包含数据中已记录的触点；自然流量、线下触点和未埋点渠道会被系统性低估。",
    ]
    if conversion_field is None:
        limitations.append("未提供 conversion_field，按每个实体的最后一次触点作为转化时点，未转化实体无法区分。")
    if lookback_days is None:
        limitations.append("未设置 lookback_days，长历史触点会被计入，早期渠道份额可能被高估。")
    elif truncated_paths:
        limitations.append(f"有 {truncated_paths} 条路径因回溯窗被截断，窗外触点未参与分配。")
    if converted_paths and single_touch_paths / converted_paths > 0.6:
        limitations.append(
            f"{single_touch_paths / converted_paths:.0%} 的路径只有单一渠道，多触点模型之间的差异主要来自少数长路径。"
        )
    if "shapley" in models:
        limitations.append("shapley 采用单路径对称解（参与渠道均分），不是基于全子集转化期望的严格 Shapley 值。")

    return {
        "op": "attribution",
        "id_field": id_field,
        "channel_field": channel_field,
        "timestamp_field": timestamp_field,
        "models": models,
        "parameters": {
            "half_life_days": half_life_days,
            "lookback_days": lookback_days,
            "position_first_weight": position_first,
            "position_last_weight": position_last,
        },
        "path_summary": {
            "entities": path_count,
            "converted_paths": converted_paths,
            "single_channel_path_share": single_touch_paths / converted_paths if converted_paths else None,
            "median_path_length": float(np.median(path_lengths)) if path_lengths else None,
            "max_path_length": int(max(path_lengths)) if path_lengths else None,
            "conversion_value_total": total_value,
            "value_unit": value_field or "conversion_count",
        },
        "channels": rows,
        "reconciliation": reconciliation,
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 同期群留存


def op_cohort_retention(frame: pd.DataFrame, config: dict) -> dict:
    """同期群留存矩阵：按首次活跃期分群，观察后续各期留存。

    末期 cohort 观察窗不足时标记 immature，禁止与成熟 cohort 直接排名。
    """
    id_field = config["id_field"]
    date_field = config["date_field"]
    for field in (id_field, date_field):
        if field not in frame.columns:
            raise ValueError(f"字段不存在：{field}")
    period = str(config.get("period", "week")).lower()
    if period not in {"day", "week", "month"}:
        raise ValueError("period 必须是 day、week 或 month")
    max_periods = int(config.get("max_periods", 12))
    if max_periods < 1:
        raise ValueError("max_periods 必须为正整数")
    min_cohort_size = int(config.get("min_cohort_size", 30))
    value_field = config.get("value_field")
    if value_field and value_field not in frame.columns:
        raise ValueError(f"价值字段不存在：{value_field}")

    columns = [id_field, date_field] + ([value_field] if value_field else [])
    work = frame[columns].copy()
    work[date_field] = parse_date_series(work[date_field])
    work = work.dropna(subset=[id_field, date_field])
    if work.empty:
        raise ValueError("没有同时具备实体和日期的有效记录")

    if period == "day":
        bucket = work[date_field].dt.normalize()
        step = pd.Timedelta(days=1)
    elif period == "week":
        bucket = work[date_field].dt.to_period("W").dt.start_time
        step = pd.Timedelta(days=7)
    else:
        bucket = work[date_field].dt.to_period("M").dt.start_time
        step = None
    work["__bucket"] = bucket

    cohort_start = config.get("cohort_field")
    if cohort_start:
        if cohort_start not in frame.columns:
            raise ValueError(f"cohort 字段不存在：{cohort_start}")
        cohort_dates = parse_date_series(frame.loc[work.index, cohort_start])
        if period == "day":
            work["__cohort"] = cohort_dates.dt.normalize()
        elif period == "week":
            work["__cohort"] = cohort_dates.dt.to_period("W").dt.start_time
        else:
            work["__cohort"] = cohort_dates.dt.to_period("M").dt.start_time
        work = work.dropna(subset=["__cohort"])
        cohort_source = f"explicit:{cohort_start}"
    else:
        first_bucket = work.groupby(id_field)["__bucket"].transform("min")
        work["__cohort"] = first_bucket
        cohort_source = "first_observed_activity"

    if period == "month":
        work["__offset"] = (
            (work["__bucket"].dt.year - work["__cohort"].dt.year) * 12
            + (work["__bucket"].dt.month - work["__cohort"].dt.month)
        )
    else:
        work["__offset"] = ((work["__bucket"] - work["__cohort"]) / step).round().astype("Int64")
    work = work[(work["__offset"] >= 0) & (work["__offset"] <= max_periods)]
    if work.empty:
        raise ValueError("在 max_periods 范围内没有有效的留存记录")

    observation_end = work["__bucket"].max()
    cohorts = []
    for cohort_value, group in work.groupby("__cohort", sort=True):
        base_ids = set(group.loc[group["__offset"] == 0, id_field].unique())
        size = len(base_ids)
        if size == 0:
            continue
        if period == "month":
            elapsed = (observation_end.year - cohort_value.year) * 12 + (observation_end.month - cohort_value.month)
        else:
            elapsed = int(round((observation_end - cohort_value) / step))
        periods = []
        for offset in range(0, min(max_periods, elapsed) + 1):
            retained_frame = group[(group["__offset"] == offset) & (group[id_field].isin(base_ids))]
            retained = int(retained_frame[id_field].nunique())
            entry: dict[str, Any] = {
                "period_offset": offset,
                "retained_entities": retained,
                "retention_rate": retained / size if size else None,
            }
            if value_field:
                total = float(to_numeric(retained_frame[value_field]).fillna(0).sum())
                entry["value_total"] = total
                entry["value_per_base_entity"] = total / size if size else None
            periods.append(entry)
        cohorts.append({
            "cohort": cohort_value.strftime("%Y-%m-%d"),
            "base_size": size,
            "observed_periods": min(max_periods, elapsed),
            "mature": elapsed > max_periods,
            "below_min_size": size < min_cohort_size,
            "periods": periods,
        })

    mature = [item for item in cohorts if item["mature"] and not item["below_min_size"]]
    average_curve = []
    for offset in range(0, max_periods + 1):
        rates = [
            entry["retention_rate"]
            for item in mature
            for entry in item["periods"]
            if entry["period_offset"] == offset and entry["retention_rate"] is not None
        ]
        if rates:
            average_curve.append({
                "period_offset": offset,
                "mean_retention_rate": float(np.mean(rates)),
                "median_retention_rate": float(np.median(rates)),
                "cohort_count": len(rates),
            })

    limitations = [
        "留存率的分母是 cohort 期初实体数；不同 cohort 的分母不同，绝对人数不可直接比较。",
        "cohort 差异只是同步现象，产品改动、投放结构和季节都会同时变化，不能直接归因于单一动作。",
    ]
    immature = [item["cohort"] for item in cohorts if not item["mature"]]
    if immature:
        limitations.append(f"以下 cohort 观察窗未满 {max_periods} 期，不能与成熟 cohort 排名：{immature[:10]}")
    small = [item["cohort"] for item in cohorts if item["below_min_size"]]
    if small:
        limitations.append(f"以下 cohort 规模小于 {min_cohort_size}，留存率波动大：{small[:10]}")
    if cohort_source == "first_observed_activity":
        limitations.append("cohort 按数据中首次出现的活跃期推断；数据起点之前已活跃的老用户会被误分入首期 cohort（左截断）。")

    return {
        "op": "cohort_retention",
        "id_field": id_field,
        "date_field": date_field,
        "period": period,
        "cohort_source": cohort_source,
        "max_periods": max_periods,
        "observation_end": observation_end.strftime("%Y-%m-%d"),
        "value_field": value_field,
        "cohorts": cohorts,
        "mature_cohort_average_curve": average_curve,
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 生存分析


def op_survival(frame: pd.DataFrame, config: dict) -> dict:
    """Kaplan-Meier 生存曲线与分组 log-rank 检验。

    回答"用户在第几天流失风险最高""某分组的流失速度是否不同"，
    比单点留存率更适合处理观察窗未满的右删失数据。
    """
    duration_field = config["duration_field"]
    if duration_field not in frame.columns:
        raise ValueError(f"存续时长字段不存在：{duration_field}")
    event_field = config.get("event_field")
    if event_field and event_field not in frame.columns:
        raise ValueError(f"事件标记字段不存在：{event_field}")
    group_field = config.get("group_field")
    if group_field and group_field not in frame.columns:
        raise ValueError(f"分组字段不存在：{group_field}")

    columns = [duration_field] + [f for f in (event_field, group_field) if f]
    work = frame[columns].copy()
    work[duration_field] = to_numeric(work[duration_field])
    work = work.dropna(subset=[duration_field])
    work = work[work[duration_field] >= 0]
    if work.empty:
        raise ValueError("没有有效的非负存续时长记录")
    if event_field:
        work["__event"] = (to_numeric(work[event_field]).fillna(0) > 0).astype(int)
        censoring = "right_censored_from_event_field"
    else:
        work["__event"] = 1
        censoring = "all_treated_as_events"

    def kaplan_meier(subset: pd.DataFrame) -> dict:
        times = np.sort(subset.loc[subset["__event"] == 1, duration_field].unique())
        at_risk_total = len(subset)
        survival = 1.0
        variance_sum = 0.0
        curve = []
        for time_point in times:
            at_risk = int((subset[duration_field] >= time_point).sum())
            events = int(((subset[duration_field] == time_point) & (subset["__event"] == 1)).sum())
            if at_risk == 0:
                continue
            survival *= 1 - events / at_risk
            if at_risk > events:
                variance_sum += events / (at_risk * (at_risk - events))
            standard_error = survival * math.sqrt(variance_sum) if variance_sum > 0 else 0.0
            curve.append({
                "time": float(time_point),
                "at_risk": at_risk,
                "events": events,
                "hazard": events / at_risk,
                "survival": survival,
                "survival_ci": [
                    max(0.0, survival - 1.96 * standard_error),
                    min(1.0, survival + 1.96 * standard_error),
                ],
            })
        median_survival = next((point["time"] for point in curve if point["survival"] <= 0.5), None)
        return {
            "n": at_risk_total,
            "events": int(subset["__event"].sum()),
            "censored": int((subset["__event"] == 0).sum()),
            "median_survival_time": median_survival,
            "curve": curve,
            "highest_hazard": max(curve, key=lambda point: point["hazard"]) if curve else None,
        }

    overall = kaplan_meier(work)
    horizons = config.get("survival_at_times") or []
    overall["survival_at_times"] = [
        {
            "time": float(time_point),
            "survival": next(
                (point["survival"] for point in reversed(overall["curve"]) if point["time"] <= float(time_point)),
                1.0,
            ),
        }
        for time_point in horizons
    ]

    groups: list[dict] = []
    log_rank: dict[str, Any] | None = None
    if group_field:
        labels = [label for label in work[group_field].dropna().unique()]
        for label in labels:
            subset = work[work[group_field] == label]
            if len(subset) < 2:
                continue
            entry = kaplan_meier(subset)
            entry["group"] = str(label)
            groups.append(entry)
        if len(groups) == 2:
            first, second = [str(item["group"]) for item in groups]
            observed_first = 0.0
            expected_first = 0.0
            variance = 0.0
            all_times = np.sort(work.loc[work["__event"] == 1, duration_field].unique())
            for time_point in all_times:
                risk_first = int(((work[group_field].astype(str) == first) & (work[duration_field] >= time_point)).sum())
                risk_second = int(((work[group_field].astype(str) == second) & (work[duration_field] >= time_point)).sum())
                risk_total = risk_first + risk_second
                events_total = int(((work[duration_field] == time_point) & (work["__event"] == 1)).sum())
                events_first = int((
                    (work[group_field].astype(str) == first)
                    & (work[duration_field] == time_point)
                    & (work["__event"] == 1)
                ).sum())
                if risk_total < 2 or events_total == 0:
                    continue
                observed_first += events_first
                expected_first += events_total * risk_first / risk_total
                variance += (
                    events_total
                    * (risk_first / risk_total)
                    * (risk_second / risk_total)
                    * (risk_total - events_total)
                    / (risk_total - 1)
                )
            if variance > 0:
                from da_stats import chi_square_p

                statistic = (observed_first - expected_first) ** 2 / variance
                log_rank = {
                    "groups": [first, second],
                    "observed_events_first_group": observed_first,
                    "expected_events_first_group": expected_first,
                    "chi_square": statistic,
                    "degrees_of_freedom": 1,
                    "p_value": chi_square_p(statistic, 1),
                }

    limitations = [
        "生存曲线描述流失速度，不解释原因；分组差异需要处理前可比性才能升级为效应。",
        "Kaplan-Meier 假设删失与流失风险独立；如果观察窗结束方式与用户质量相关，曲线会有偏。",
    ]
    if censoring == "all_treated_as_events":
        limitations.append("未提供 event_field，所有记录按已流失处理；仍在存续的用户会被低估存续时长，曲线整体偏低。")
    if group_field and len(groups) > 2:
        limitations.append("分组超过两个，未做整体 log-rank 检验；两两比较需要多重比较校正（见 multiple_testing 算子）。")
    if overall["censored"] and overall["n"] and overall["censored"] / overall["n"] > 0.7:
        limitations.append(f"删失比例达 {overall['censored'] / overall['n']:.0%}，中位存续时长可能无法估计。")

    return {
        "op": "survival",
        "duration_field": duration_field,
        "event_field": event_field,
        "group_field": group_field,
        "censoring": censoring,
        "overall": overall,
        "groups": groups,
        "log_rank": log_rank,
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 路径分析


def op_path_analysis(frame: pd.DataFrame, config: dict) -> dict:
    """行为路径分析：节点间转移矩阵、高频路径、回环与流失出口。

    与 funnel_rates 的区别：漏斗假定阶段是串行的，
    本算子允许并行、回访、环路和多种退出方式。
    """
    id_field = config["id_field"]
    step_field = config["step_field"]
    timestamp_field = config["timestamp_field"]
    for field in (id_field, step_field, timestamp_field):
        if field not in frame.columns:
            raise ValueError(f"字段不存在：{field}")
    max_steps = int(config.get("max_steps", 10))
    if max_steps < 2:
        raise ValueError("max_steps 至少为 2")
    top_paths = int(config.get("top_paths", 20))
    terminal_steps = {str(value) for value in config.get("terminal_steps", [])}
    session_gap_minutes = config.get("session_gap_minutes")

    work = frame[[id_field, step_field, timestamp_field]].copy()
    work[timestamp_field] = parse_date_series(work[timestamp_field])
    work = work.dropna()
    work[step_field] = work[step_field].astype(str)
    if work.empty:
        raise ValueError("没有同时具备实体、步骤和时间戳的有效事件")
    work = work.sort_values([id_field, timestamp_field])

    if session_gap_minutes is not None:
        gap = pd.Timedelta(minutes=float(session_gap_minutes))
        elapsed = work.groupby(id_field)[timestamp_field].diff()
        work["__session"] = (elapsed.isna() | (elapsed > gap)).groupby(work[id_field]).cumsum()
        sequence_keys = [id_field, "__session"]
        sequence_unit = "session"
    else:
        sequence_keys = [id_field]
        sequence_unit = "entity"

    transitions: dict[tuple[str, str], int] = {}
    path_counter: dict[tuple[str, ...], int] = {}
    entry_counter: dict[str, int] = {}
    exit_counter: dict[str, int] = {}
    loop_counter: dict[str, int] = {}
    lengths: list[int] = []
    truncated = 0

    for _key, group in work.groupby(sequence_keys, sort=False):
        steps = group[step_field].tolist()
        if len(steps) > max_steps:
            truncated += 1
            steps = steps[:max_steps]
        if not steps:
            continue
        lengths.append(len(steps))
        entry_counter[steps[0]] = entry_counter.get(steps[0], 0) + 1
        exit_counter[steps[-1]] = exit_counter.get(steps[-1], 0) + 1
        path_counter[tuple(steps)] = path_counter.get(tuple(steps), 0) + 1
        for current, following in zip(steps, steps[1:]):
            transitions[(current, following)] = transitions.get((current, following), 0) + 1
            if current == following:
                loop_counter[current] = loop_counter.get(current, 0) + 1

    if not lengths:
        raise ValueError("没有可构成路径的序列")

    outgoing: dict[str, int] = {}
    for (source, _target), count in transitions.items():
        outgoing[source] = outgoing.get(source, 0) + count
    transition_rows = [
        {
            "from": source,
            "to": target,
            "count": count,
            "share_of_outgoing": count / outgoing[source] if outgoing.get(source) else None,
            "is_self_loop": source == target,
        }
        for (source, target), count in transitions.items()
    ]
    transition_rows.sort(key=lambda item: item["count"], reverse=True)

    sequence_total = len(lengths)
    path_rows = [
        {
            "path": " → ".join(path),
            "steps": len(path),
            "count": count,
            "share": count / sequence_total,
            "ends_at_terminal": bool(terminal_steps) and path[-1] in terminal_steps,
        }
        for path, count in path_counter.items()
    ]
    path_rows.sort(key=lambda item: item["count"], reverse=True)

    exits = [
        {
            "step": step,
            "exit_count": count,
            "share_of_sequences": count / sequence_total,
            "is_declared_terminal": step in terminal_steps,
        }
        for step, count in sorted(exit_counter.items(), key=lambda item: item[1], reverse=True)
    ]
    reached_terminal = (
        sum(count for step, count in exit_counter.items() if step in terminal_steps) / sequence_total
        if terminal_steps
        else None
    )

    limitations = [
        "转移份额只描述观测到的顺序，不代表前一步造成了后一步。",
        "路径只包含已埋点的步骤；未埋点或采样丢失的事件会让路径看起来比实际更短更直。",
    ]
    if session_gap_minutes is None:
        limitations.append("未设置 session_gap_minutes，同一实体的全部历史被拼成一条路径，跨天回访会被误当作连续行为。")
    if truncated:
        limitations.append(f"有 {truncated} 条序列超过 max_steps={max_steps} 被截断，长路径的后段未参与统计。")
    if not terminal_steps:
        limitations.append("未声明 terminal_steps，无法区分“正常完成”与“中途流失”两种退出。")

    return {
        "op": "path_analysis",
        "id_field": id_field,
        "step_field": step_field,
        "timestamp_field": timestamp_field,
        "sequence_unit": sequence_unit,
        "sequence_count": sequence_total,
        "path_length": {
            "median": float(np.median(lengths)),
            "mean": float(np.mean(lengths)),
            "max": int(max(lengths)),
        },
        "entries": [
            {"step": step, "count": count, "share": count / sequence_total}
            for step, count in sorted(entry_counter.items(), key=lambda item: item[1], reverse=True)
        ],
        "exits": exits,
        "terminal_reach_rate": reached_terminal,
        "self_loops": [
            {"step": step, "count": count} for step, count in sorted(loop_counter.items(), key=lambda item: item[1], reverse=True)
        ],
        "transitions": transition_rows[: int(config.get("top_transitions", 50))],
        "top_paths": path_rows[:top_paths],
        "limitations": limitations,
    }


# ---------------------------------------------------------------- RFM 分层


def op_rfm(frame: pd.DataFrame, config: dict) -> dict:
    """RFM 分层：按最近一次、频次、金额分位打分并映射到动作分组。

    分位数分层只描述历史结构，不代表某层对某动作响应更好；
    要证明后者需要分层实验。
    """
    id_field = config["id_field"]
    date_field = config["date_field"]
    value_field = config["value_field"]
    for field in (id_field, date_field, value_field):
        if field not in frame.columns:
            raise ValueError(f"字段不存在：{field}")
    bins = int(config.get("bins", 5))
    if bins < 2:
        raise ValueError("bins 至少为 2")

    work = frame[[id_field, date_field, value_field]].copy()
    work[date_field] = parse_date_series(work[date_field])
    work[value_field] = to_numeric(work[value_field])
    work = work.dropna()
    if work.empty:
        raise ValueError("没有同时具备实体、日期和金额的有效记录")
    reference = (
        parse_date_series(pd.Series([config["reference_date"]])).iloc[0]
        if config.get("reference_date")
        else work[date_field].max()
    )
    if pd.isna(reference):
        raise ValueError("reference_date 无法解析")

    grouped = work.groupby(id_field).agg(
        last_seen=(date_field, "max"),
        frequency=(date_field, "count"),
        monetary=(value_field, "sum"),
    )
    grouped["recency_days"] = (reference - grouped["last_seen"]).dt.total_seconds() / 86400.0
    entity_count = len(grouped)
    if entity_count < bins:
        raise ValueError(f"实体数 {entity_count} 少于分箱数 {bins}")

    def score(series: pd.Series, ascending_is_better: bool) -> pd.Series:
        ranked = series.rank(method="first", ascending=ascending_is_better, pct=True)
        return np.ceil(ranked * bins).clip(1, bins).astype(int)

    grouped["r_score"] = score(grouped["recency_days"], ascending_is_better=True)
    grouped["f_score"] = score(grouped["frequency"], ascending_is_better=False)
    grouped["m_score"] = score(grouped["monetary"], ascending_is_better=False)
    grouped["rfm_total"] = grouped[["r_score", "f_score", "m_score"]].sum(axis=1)
    high = bins * 0.6
    low = bins * 0.4

    def label_of(row: pd.Series) -> str:
        r, f, m = row["r_score"], row["f_score"], row["m_score"]
        if r >= high and f >= high and m >= high:
            return "high_value_active"
        if r >= high and f < low:
            return "new_or_low_frequency"
        if r < low and f >= high and m >= high:
            return "at_risk_high_value"
        if r < low and f < low:
            return "dormant"
        if m >= high:
            return "high_spend_moderate_activity"
        return "mid_tier"

    grouped["segment"] = grouped.apply(label_of, axis=1)
    total_monetary = float(grouped["monetary"].sum())
    segments = []
    for label, subset in grouped.groupby("segment"):
        segments.append({
            "segment": label,
            "size": int(len(subset)),
            "share_of_entities": len(subset) / entity_count,
            "share_of_monetary": float(subset["monetary"].sum()) / total_monetary if total_monetary else None,
            "median_recency_days": float(subset["recency_days"].median()),
            "median_frequency": float(subset["frequency"].median()),
            "median_monetary": float(subset["monetary"].median()),
            "mean_monetary": float(subset["monetary"].mean()),
            "below_min_sample": len(subset) < int(config.get("min_segment_size", 30)),
        })
    segments.sort(key=lambda item: item["share_of_monetary"] or 0, reverse=True)

    limitations = [
        "RFM 只使用交易历史，不含动作前行为特征；它描述价值结构，不预测对具体动作的响应。",
        "分位数分层是相对的：整体活跃度下降时，各层规模不变但绝对水平已经改变，跨期比较需要固定切点。",
        "金额已按实体加总，未做退款、优惠和税的口径确认；口径未确认前不得写成利润贡献。",
    ]
    small = [item["segment"] for item in segments if item["below_min_sample"]]
    if small:
        limitations.append(f"以下分层样本不足，不参与排名：{small}")
    span_days = float((work[date_field].max() - work[date_field].min()).total_seconds() / 86400.0)
    if span_days < 90:
        limitations.append(f"数据仅覆盖 {span_days:.0f} 天，频次与最近一次的区分度有限。")

    return {
        "op": "rfm",
        "id_field": id_field,
        "reference_date": reference.strftime("%Y-%m-%d"),
        "bins": bins,
        "entity_count": entity_count,
        "observation_window": {
            "start": work[date_field].min().strftime("%Y-%m-%d"),
            "end": work[date_field].max().strftime("%Y-%m-%d"),
            "days": span_days,
        },
        "score_cutoffs": {
            "recency_days_quantiles": [float(value) for value in grouped["recency_days"].quantile(np.linspace(0, 1, bins + 1))],
            "frequency_quantiles": [float(value) for value in grouped["frequency"].quantile(np.linspace(0, 1, bins + 1))],
            "monetary_quantiles": [float(value) for value in grouped["monetary"].quantile(np.linspace(0, 1, bins + 1))],
        },
        "segments": segments,
        "monetary_total": total_monetary,
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 价格弹性


def op_price_elasticity(frame: pd.DataFrame, config: dict) -> dict:
    """价格弹性：对数-对数回归估计需求价格弹性与收入含义。

    观测价格与销量的相关是内生的（促销期同时降价和加投放），
    没有随机化定价或工具变量时只能作为关联描述。
    """
    price_field = config["price_field"]
    quantity_field = config["quantity_field"]
    for field in (price_field, quantity_field):
        if field not in frame.columns:
            raise ValueError(f"字段不存在：{field}")
    group_field = config.get("group_field")
    if group_field and group_field not in frame.columns:
        raise ValueError(f"分组字段不存在：{group_field}")

    columns = [price_field, quantity_field] + ([group_field] if group_field else [])
    work = frame[columns].copy()
    work[price_field] = to_numeric(work[price_field])
    work[quantity_field] = to_numeric(work[quantity_field])
    work = work.dropna(subset=[price_field, quantity_field])
    work = work[(work[price_field] > 0) & (work[quantity_field] > 0)]
    min_points = int(config.get("min_points", 10))
    if len(work) < min_points:
        raise ValueError(f"有效观测 {len(work)} 条少于 min_points={min_points}，无法估计弹性")

    def fit(subset: pd.DataFrame) -> dict:
        log_price = np.log(subset[price_field].to_numpy(dtype=float))
        log_quantity = np.log(subset[quantity_field].to_numpy(dtype=float))
        n = len(log_price)
        price_variation = float(np.std(log_price, ddof=1))
        if price_variation <= 1e-9:
            raise ValueError("价格没有变化（方差为零），无法估计弹性")
        slope, intercept = np.polyfit(log_price, log_quantity, 1)
        fitted = slope * log_price + intercept
        residuals = log_quantity - fitted
        residual_ss = float(np.sum(residuals**2))
        total_ss = float(np.sum((log_quantity - log_quantity.mean()) ** 2))
        degrees = n - 2
        standard_error = (
            math.sqrt(residual_ss / degrees / float(np.sum((log_price - log_price.mean()) ** 2)))
            if degrees > 0 and np.sum((log_price - log_price.mean()) ** 2) > 0
            else None
        )
        elasticity = float(slope)
        return {
            "n": n,
            "elasticity": elasticity,
            "standard_error": standard_error,
            "ci": [elasticity - 1.96 * standard_error, elasticity + 1.96 * standard_error] if standard_error else [None, None],
            "r_squared": 1 - residual_ss / total_ss if total_ss > 0 else None,
            "log_price_sd": price_variation,
            "price_range": [float(subset[price_field].min()), float(subset[price_field].max())],
            "demand_type": (
                "elastic" if elasticity < -1 else "inelastic" if elasticity > -1 and elasticity < 0 else "non_standard"
            ),
            "revenue_direction_of_price_increase": (
                "revenue_falls" if elasticity < -1 else "revenue_rises" if -1 < elasticity < 0 else "undetermined"
            ),
        }

    overall = fit(work)
    groups = []
    if group_field:
        for label, subset in work.groupby(group_field):
            if len(subset) < min_points:
                groups.append({"group": str(label), "n": int(len(subset)), "error": "样本不足，未估计"})
                continue
            try:
                entry = fit(subset)
            except ValueError as exc:
                groups.append({"group": str(label), "n": int(len(subset)), "error": str(exc), "log_price_sd": 0.0})
                continue
            entry["group"] = str(label)
            groups.append(entry)

    limitations = [
        "观测价格不是随机分配的：促销期通常同时降价、加投放并调整曝光，弹性估计包含这些混淆。",
        "对数-对数弹性只在观测价格区间内有解释力，不能外推到未出现过的价位。",
        "没有竞品价格、库存和季节控制变量时，本结果只能作为关联描述，不能作为定价决策的唯一依据。",
    ]
    if overall.get("elasticity") is not None and overall["elasticity"] > 0:
        limitations.append("估计弹性为正，与需求定律相反，通常说明存在反向因果（畅销品提价）或遗漏变量，不应直接使用。")
    if overall.get("log_price_sd") is not None and overall["log_price_sd"] < 0.05:
        limitations.append("价格波动很小，弹性估计的置信区间会很宽，方向性结论也不稳。")

    return {
        "op": "price_elasticity",
        "price_field": price_field,
        "quantity_field": quantity_field,
        "group_field": group_field,
        "overall": overall,
        "groups": groups,
        "identification": {
            "strategy": str(config.get("identification", "observational")),
            "randomized_pricing": bool(config.get("randomized_pricing", False)),
            "max_claim_level": "L2" if config.get("randomized_pricing") else "L1",
        },
        "limitations": limitations,
    }


GROWTH_OPERATORS = {
    "attribution": op_attribution,
    "cohort_retention": op_cohort_retention,
    "survival": op_survival,
    "path_analysis": op_path_analysis,
    "rfm": op_rfm,
    "price_elasticity": op_price_elasticity,
}
