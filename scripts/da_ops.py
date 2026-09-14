from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# 允许 `python scripts/da_ops.py ...` 直接运行（不再依赖 cwd）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from da_envcheck import ensure_dependencies  # noqa: E402

# 依赖自检必须在 pandas 之前：缺依赖时给安装指引，而不是 traceback
ensure_dependencies()

import pandas as pd  # noqa: E402
from statistics import NormalDist  # noqa: E402

from da_common import (  # noqa: E402
    DataError,
    choose_date_field,
    choose_main_table,
    cli_guard,
    load_tables,
    parse_date_series,
    quiet_numeric,
    to_numeric,
    write_json,
)
from da_growth import GROWTH_OPERATORS
from da_stats import DATA_FREE_OPERATORS as STATS_DATA_FREE, STAT_OPERATORS


def baseline_for(
    values: pd.DataFrame,
    date_field: str,
    metric_field_name: str,
    target: pd.Timestamp,
    window_days: int = 56,
    min_same_weekday: int = 2,
    fallback_rows: int = 28,
    min_points_for_weekday: int = 8,
) -> dict:
    dates = values[date_field]
    metric = to_numeric(values[metric_field_name])
    history = values[(dates < target) & (dates >= target - pd.Timedelta(days=window_days))]
    same_weekday = history[dates.loc[history.index].dt.dayofweek == target.dayofweek]
    # 同星期基线只有在「整 8 周」时才用：2–3 个同星期点的中位数配上 1% 的相对尺度
    # 下限，能在纯噪声里造出 |z| > 10 的假异动，把真正的异动挤出榜首。
    weekday_points_needed = max(min_same_weekday, min_points_for_weekday)
    use_weekday = len(same_weekday) >= weekday_points_needed
    chosen = same_weekday if use_weekday else history.tail(fallback_rows)
    series = metric.loc[chosen.index] if len(chosen) else metric
    if series.empty:
        return {"value": None, "n": 0, "method": "unavailable", "mad": None, "std": None, "history_n": int(len(history))}
    median = float(series.median())
    deviation_series = (series - median).abs()
    mad = float(deviation_series.median()) if not deviation_series.empty else None
    return {
        "value": median,
        "n": int(len(series)),
        # history_n 是基线窗口内可用的天数（同星期子集最多 8 天，因为窗口是 56 天）。
        # 门禁按 history_n 判「有没有足够历史」，不按同星期子集大小判。
        "history_n": int(len(history)),
        "method": "same_weekday" if use_weekday else "rolling_window",
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
    limitations = [
        "阶段计数按字段直接相加：这里假设每个字段都是同一实体、同一时间窗的去重计数；如果字段是次数或未去重，阶段率会被重复计数放大。",
        "阶段率的分母是上一阶段：阶段顺序写错（例如浏览排在注册之前）会得到大于 1 的比率，必须先用数据口径确认顺序。",
        "只做算术重算，不做显著性检验：样本量小时阶段率差异可能完全由随机性解释。",
    ]
    if any(item["rate_from_previous"] is not None and item["rate_from_previous"] > 1 for item in values):
        limitations.append("存在大于 100% 的阶段转化率，通常说明阶段顺序与数据口径不一致，先修口径再读结论。")
    return {"op": "funnel_rates", "stages": values, "rows": len(frame), "limitations": limitations}


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
    limitations = [
        "只对总量缺口做加总对账，不解释缺口原因：贡献度大不等于「责任大」，它只是缺口在分组间的分配。",
        "share_of_gap 在正负抵消时不可读：缺口接近 0 时分母不稳，此时只看 delta 绝对值，不要比 share。",
        "分组必须可加总：如果同一实体（订单、用户）被重复计入多个组，缺口会被重复计算。",
        "baseline 与 current 的过滤条件必须口径一致，否则贡献度里会混入口径切换的效果。",
    ]
    if gap and abs(gap) > 0 and any(item["delta"] > 0 for item in result) and any(item["delta"] < 0 for item in result):
        limitations.append("存在正负抵消的分组，缺口的一部分被相互抵消；不要用单个分组的 delta 解释整段缺口。")
    return {"op": "contribution", "group_field": group, "value_field": value_field, "total": {"baseline": total_baseline, "current": total_current, "gap": gap}, "groups": sorted(result, key=lambda item: abs(item["delta"]), reverse=True), "limitations": limitations}


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
    limitations = [
        "组内/结构分解是恒等式变形，不是因果分解：结构变化往往也是业务动作的结果，不能读成「结构变化导致的损失」。",
        "分解只在给定的分组粒度内成立：换一个分组维度会得到完全不同的组内/结构切分。",
        "分组多、单组样本小时，组内项会被小样本噪声主导；组内项接近 0 时不要写成「该组没有问题」。",
        "interaction_residual 不为 0 说明两组权重与比率同时变化，剩余项不可归给任何单一机制。",
    ]
    return {"op": "ratio_decomp", "ratio": {"numerator": numerator, "denominator": denominator, "baseline": baseline_rate, "current": current_rate, "delta": delta}, "components": {"within_group": within_total, "mix_shift": mix_total, "interaction_residual": delta - within_total - mix_total if delta is not None else None}, "groups": sorted(rows, key=lambda item: abs(item["contribution"]), reverse=True), "limitations": limitations}


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
    limitations = [
        "没有做 SRM 检验、没有检查分流单位是否重复：先跑 srm_check，分流有问题时本结果不可解读。",
        "这是无协变量调整的两样本比较；CUPED 或分层能提高精度，但都不能修复分流问题。",
        "p 值与区间按正态近似：极低事件率、强偏态金额指标或极小样本需要更稳健的方法。",
        "只比较了处理与对照，没有覆盖护栏指标与异质性；单看一个指标的显著性不足以支撑上线决策。",
    ]
    if metric_type == "binary":
        limitations.append("binary 指标按合并比例池化标准误（pooled），要求两组样本独立；同一样本重复出现在两行会低估标准误。")
    return {"op": "ab_effect", "control": {"label": control, "n": len(control_values), "mean": control_mean}, "treatment": {"label": treatment, "n": len(treatment_values), "mean": treatment_mean}, "effect": effect, "ci": ci, "confidence_level": confidence_level, "z": z, "p_value": normal_pvalue(z) if z is not None else None, "metric_type": metric_type, "limitations": limitations}


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
    limitations = [
        "分层是描述性的：只报告规模与指标分布，不做任何显著性检验，分群差异可能只反映样本量差异。",
        "按维度直接分组会让同一实体出现在多个组里，size 之和可能大于去重实体数。",
        "如果分层字段本身是结果变量（例如按当前状态、当前等级分组），它不能用来解释同期变化。",
    ]
    covered = sum(item["size"] for item in output)
    if covered == total and len(output) > 1:
        limitations.append("各分层 size 之和等于行数，说明分组字段是单值字段；若为多值字段，规模会被重复计数。")
    return {"op": "segment_profile", "segment_field": segment, "segments": sorted(output, key=lambda item: item["size"], reverse=True), "limitations": limitations}


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
    # 基线的尺度下限是 |base| * 1%，所以基线样本只有 1–2 天时，序列开头几天的
    # robust z 会被人为放大到 10 以上，霸占按 |z| 排序的榜首。两条门禁把这类
    # 「没有基线可言的日期」从判定里剔除，而不是让模型自己发现。
    # min_baseline_n 判的是「基线窗口内有多少天历史」，不是同星期子集的大小：
    # 56 天窗口里同星期最多 8 天，用子集大小做门禁会让 14 这个默认值永远无法满足。
    min_baseline_n = int(config.get("min_baseline_n", 14))
    warmup_days = int(config.get("warmup_days", 14))
    if min_baseline_n < 0 or warmup_days < 0:
        raise ValueError("min_baseline_n 与 warmup_days 不能为负数")

    rows = []
    excluded = []
    for position, (_, row) in enumerate(work.iterrows()):
        baseline = baseline_for(
            work,
            "__date",
            metric,
            row["__date"],
            window_days=baseline_window_days,
            min_same_weekday=int(config.get("min_same_weekday", 2)),
            fallback_rows=int(config.get("baseline_fallback_rows", 28)),
            min_points_for_weekday=int(config.get("min_points_for_weekday", 8)),
        )
        deviation_result = deviation(float(row[metric]), baseline, minimum_relative_scale)
        entry = {"date": row[date_field].strftime("%Y-%m-%d"), "value": float(row[metric]), "baseline": baseline, "deviation": deviation_result}
        if position < warmup_days:
            excluded.append({**entry, "exclusion_reason": "warmup_period", "exclusion_detail": f"序列第 {position + 1} 天，位于 warmup_days={warmup_days} 的观察期外"})
        elif baseline.get("history_n", baseline["n"]) < min_baseline_n:
            excluded.append({**entry, "exclusion_reason": "insufficient_baseline", "exclusion_detail": f"基线窗口内只有 {baseline.get('history_n', baseline['n'])} 天历史，少于 min_baseline_n={min_baseline_n}"})
        elif baseline["n"] < 3:
            excluded.append({**entry, "exclusion_reason": "insufficient_baseline_points", "exclusion_detail": f"进入基线计算的点只有 {baseline['n']} 个，中位数与 MAD 不可用"})
        else:
            rows.append(entry)

    warmup_excluded = sum(1 for item in excluded if item["exclusion_reason"] == "warmup_period")
    baseline_excluded = len(excluded) - warmup_excluded
    limitations = [
        "基线是中位数（同星期优先）：一次水平位移之后基线会被位移后的数据污染，位移后前几周的偏离会被系统性低估。",
        "robust z 只描述偏离幅度，不说明原因，也没有做多重比较校正；按 |z| 取前几名本质上是在同一序列上反复挑选最大值。",
        "前 warmup_days 天不做判定，基线窗口内历史少于 min_baseline_n 天的日期也不做判定（两者口径不同：前者按位置，后者按可用历史），理由逐条写在 excluded_rows；代价是序列开头几天的真实事故不会被报出来。",
        "周内效应只按「同星期中位数」处理，且要求同星期点达到 min_points_for_weekday（默认 8，即整 8 周）才启用，否则回退到滚动窗口中位数：月内周期、节假日和促销档期都不会被这套基线吸收。",
        "日期是按天聚合后计算的：单日缺失会被跳过，不会补 0，因此缺口和真实低值在这里看起来一样。",
    ]
    if warmup_excluded and not rows:
        limitations.append("全部日期都被 warmup_days 或 min_baseline_n 排除，本次没有可判定的异动日；请给更长的序列或下调门禁。")
    if len(rows) < 5:
        limitations.append(f"可判定日期只有 {len(rows)} 天，排名极不稳定，不要按名次解读。")
    return {
        "op": "anomaly_scan",
        "metric": metric,
        "date_field": date_field,
        "gates": {"min_baseline_n": min_baseline_n, "min_baseline_n_means": "基线窗口内可用历史天数下限", "warmup_days": warmup_days, "baseline_window_days": baseline_window_days, "min_same_weekday": int(config.get("min_same_weekday", 2)), "min_points_for_weekday": int(config.get("min_points_for_weekday", 8)), "min_points_for_weekday_means": "同星期基线要求的最少同星期点；不足则回退到滚动窗口"},
        "coverage": {"total_days": int(len(work)), "judged_days": len(rows), "excluded_days": len(excluded), "excluded_warmup": warmup_excluded, "excluded_insufficient_baseline": baseline_excluded, "excluded_insufficient_baseline_points": len(excluded) - warmup_excluded - baseline_excluded},
        "rows": sorted(rows, key=lambda item: abs(item["deviation"].get("robust_z") or 0), reverse=True),
        "excluded_rows": excluded,
        "limitations": limitations,
    }


OPERATORS = {"funnel_rates": op_funnel, "contribution": op_contribution, "ratio_decomp": op_ratio_decomp, "ab_effect": op_ab_effect, "segment_profile": op_segment_profile, "anomaly_scan": op_anomaly_scan}
for _name, _func in STAT_OPERATORS.items():
    OPERATORS[_name] = _func
for _name, _func in GROWTH_OPERATORS.items():
    OPERATORS[_name] = _func

DATA_FREE_OPERATORS = set(STATS_DATA_FREE)


def execute(operator: str, data_path: str | None, config: dict) -> dict:
    """跑一个算子并返回结果；输入问题统一抛 DataError。

    main() 和测试都走这里，保证「CLI 里不崩」＝「这个函数不崩」。
    """
    if operator not in OPERATORS:
        raise DataError(f"未知算子：{operator}")
    if not isinstance(config, dict):
        raise DataError("算子配置必须是 JSON 对象")
    with quiet_numeric():
        return _execute(operator, data_path, config)


def _execute(operator: str, data_path: str | None, config: dict) -> dict:
    try:
        if operator in DATA_FREE_OPERATORS:
            result = OPERATORS[operator](None, config)
        else:
            if not data_path:
                raise DataError(f"算子 {operator} 需要数据文件")
            frame, sheet = load_frame(data_path, config)
            result = OPERATORS[operator](frame, config)
            if not isinstance(result, dict):
                raise DataError(f"算子 {operator} 返回了非对象结果")
            result["sheet"] = sheet
    except DataError:
        raise
    except (KeyError, ValueError, TypeError) as error:
        # 算子对「配置缺字段 / 样本不足 / 分母为 0」的报错属于输入问题，
        # 统一转成结构化失败，而不是把内部栈甩给用户。
        raise DataError(f"算子 {operator} 无法执行：{type(error).__name__}: {error}") from error
    result["config"] = config
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="通用数据分析算子入口")
    parser.add_argument("operator", choices=sorted(OPERATORS))
    parser.add_argument("--data", help="数据文件路径；纯设计算子（power_mde / multiple_testing）可省略")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    write_json(args.out, execute(args.operator, args.data, config))
    return 0


if __name__ == "__main__":
    sys.exit(cli_guard(main))
