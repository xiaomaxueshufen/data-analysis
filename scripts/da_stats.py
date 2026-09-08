"""实验与统计类算子：功效/MDE、SRM、多重比较、CUPED、断点检测。

本模块只依赖 pandas/numpy 与标准库，不引入 scipy/sklearn。
所有函数在样本不足、方差为零或分母缺失时返回结构化错误，不返回伪造数字。
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from da_common import parse_date_series, to_numeric


NORMAL = NormalDist()


# ---------------------------------------------------------------- 分布工具


def normal_two_sided_p(z: float | None) -> float | None:
    """双侧正态 p 值。"""
    if z is None or not math.isfinite(z):
        return None
    return math.erfc(abs(z) / math.sqrt(2))


def _gammaln(x: float) -> float:
    return math.lgamma(x)


def _lower_gamma_series(s: float, x: float, iterations: int = 500) -> float:
    """规范化下不完全 gamma P(s, x)，级数展开，适用 x < s + 1。"""
    total = 1.0 / s
    term = total
    for n in range(1, iterations):
        term *= x / (s + n)
        total += term
        if abs(term) < abs(total) * 1e-14:
            break
    return total * math.exp(-x + s * math.log(x) - _gammaln(s))


def _upper_gamma_cf(s: float, x: float, iterations: int = 500) -> float:
    """规范化上不完全 gamma Q(s, x)，连分式展开，适用 x >= s + 1。"""
    tiny = 1e-300
    b = x + 1.0 - s
    c = 1.0 / tiny
    d = 1.0 / b if b != 0 else 1.0 / tiny
    h = d
    for i in range(1, iterations):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h * math.exp(-x + s * math.log(x) - _gammaln(s))


def chi_square_p(statistic: float | None, degrees_of_freedom: int) -> float | None:
    """卡方上尾概率 P(X > statistic)。df >= 1，纯标准库实现。"""
    if statistic is None or not math.isfinite(statistic) or degrees_of_freedom < 1:
        return None
    if statistic <= 0:
        return 1.0
    s = degrees_of_freedom / 2.0
    x = statistic / 2.0
    if x < s + 1.0:
        return max(0.0, min(1.0, 1.0 - _lower_gamma_series(s, x)))
    return max(0.0, min(1.0, _upper_gamma_cf(s, x)))


# ---------------------------------------------------------------- 实验设计


def _resolve_effect(config: dict, baseline: float) -> tuple[float, str]:
    """把 mde 配置解析为绝对效应。"""
    if "mde_absolute" in config:
        return float(config["mde_absolute"]), "absolute"
    if "mde_relative" in config:
        return float(config["mde_relative"]) * baseline, "relative"
    raise ValueError("需要提供 mde_absolute 或 mde_relative 之一")


def op_power_mde(frame: pd.DataFrame | None, config: dict) -> dict:
    """实验设计：给定 MDE 求样本量，或给定样本量求 MDE，并输出功效曲线。

    二元指标使用 baseline_rate；连续指标使用 baseline_mean + baseline_sd。
    这是实验开跑之前的设计算子，不解读任何已发生的实验结果。
    """
    metric_type = config.get("metric_type", "binary")
    alpha = float(config.get("alpha", 0.05))
    power = float(config.get("power", 0.8))
    ratio = float(config.get("ratio", 1.0))
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha 与 power 必须位于 0 和 1 之间")
    if ratio <= 0:
        raise ValueError("ratio 必须为正数")
    if "n_per_arm" not in config and "mde_absolute" not in config and "mde_relative" not in config:
        raise ValueError("必须提供 n_per_arm 或 mde_absolute 或 mde_relative 之一")
    two_sided = bool(config.get("two_sided", True))
    z_alpha = NORMAL.inv_cdf(1 - alpha / 2) if two_sided else NORMAL.inv_cdf(1 - alpha)
    z_power = NORMAL.inv_cdf(power)

    if metric_type == "binary":
        baseline = float(config["baseline_rate"])
        if not 0 < baseline < 1:
            raise ValueError("baseline_rate 必须位于 0 和 1 之间（开区间）")
        variance_of = lambda p: p * (1 - p)  # noqa: E731
    else:
        baseline = float(config["baseline_mean"])
        sd = float(config["baseline_sd"])
        if sd <= 0:
            raise ValueError("baseline_sd 必须为正数")
        variance_of = lambda _p: sd**2  # noqa: E731

    def required_n(effect: float) -> float | None:
        if effect == 0:
            return None
        treatment = baseline + effect
        if metric_type == "binary" and not 0 < treatment < 1:
            return None
        var_c = variance_of(baseline)
        var_t = variance_of(treatment)
        return (z_alpha + z_power) ** 2 * (var_c + var_t / ratio) / effect**2

    def achieved_power(effect: float, n_control: float) -> float | None:
        if effect == 0 or n_control <= 0:
            return None
        treatment = baseline + effect
        if metric_type == "binary" and not 0 < treatment < 1:
            return None
        se = math.sqrt(variance_of(baseline) / n_control + variance_of(treatment) / (n_control * ratio))
        if se <= 0:
            return None
        return float(NORMAL.cdf(abs(effect) / se - z_alpha))

    result: dict[str, Any] = {
        "op": "power_mde",
        "metric_type": metric_type,
        "design": {
            "alpha": alpha,
            "target_power": power,
            "two_sided": two_sided,
            "treatment_to_control_ratio": ratio,
            "baseline": baseline,
        },
        "limitations": [
            "样本量按正态近似计算，极低事件率或强偏态指标需要改用精确方法或模拟。",
            "本算子只做设计，不代表实验已经取得该效应。",
        ],
    }

    if "n_per_arm" in config:
        n_control = float(config["n_per_arm"])
        if n_control <= 0:
            raise ValueError("n_per_arm 必须为正数")
        low, high = 1e-12, abs(baseline) if metric_type == "binary" else abs(baseline) + 10 * float(config["baseline_sd"])
        high = max(high, 1e-6)
        for _ in range(200):
            mid = (low + high) / 2
            got = achieved_power(mid, n_control)
            if got is None or got < power:
                low = mid
            else:
                high = mid
        result["given_sample_size"] = {
            "n_control": n_control,
            "n_treatment": n_control * ratio,
            "detectable_absolute_effect": high,
            "detectable_relative_effect": high / baseline if baseline else None,
        }

    if "mde_absolute" in config or "mde_relative" in config:
        effect, effect_kind = _resolve_effect(config, baseline)
        n_control = required_n(effect)
        result["given_mde"] = {
            "effect_input": effect_kind,
            "absolute_effect": effect,
            "relative_effect": effect / baseline if baseline else None,
            "n_control": math.ceil(n_control) if n_control else None,
            "n_treatment": math.ceil(n_control * ratio) if n_control else None,
            "n_total": math.ceil(n_control) + math.ceil(n_control * ratio) if n_control else None,
        }
        daily = config.get("daily_traffic_per_arm")
        if n_control and daily:
            result["given_mde"]["days_needed"] = math.ceil(n_control / float(daily))

    curve = []
    grid = config.get("power_curve_effects")
    if grid is None and ("mde_absolute" in config or "mde_relative" in config):
        effect, _ = _resolve_effect(config, baseline)
        grid = [effect * scale for scale in (0.5, 0.75, 1.0, 1.5, 2.0)]
    for effect in grid or []:
        effect = float(effect)
        n_control = required_n(effect)
        entry = {
            "absolute_effect": effect,
            "relative_effect": effect / baseline if baseline else None,
            "n_control": math.ceil(n_control) if n_control else None,
        }
        if "n_per_arm" in config:
            entry["power_at_given_n"] = achieved_power(effect, float(config["n_per_arm"]))
        curve.append(entry)
    if curve:
        result["power_curve"] = curve
    return result


def op_srm_check(frame: pd.DataFrame, config: dict) -> dict:
    """样本比例失衡（SRM）检验：卡方拟合优度。

    SRM 显著说明分流本身有问题，此时任何效应解读都必须阻断，
    不能因为"主指标显著"就跳过这一步。
    """
    variant_field = config["variant_field"]
    if variant_field not in frame.columns:
        raise ValueError(f"分流字段不存在：{variant_field}")
    unit_field = config.get("unit_field")
    if unit_field:
        if unit_field not in frame.columns:
            raise ValueError(f"分流单位字段不存在：{unit_field}")
        pairs = frame[[unit_field, variant_field]].dropna()
        cross_assigned = int((pairs.groupby(unit_field)[variant_field].nunique() > 1).sum())
        counts = pairs.drop_duplicates(subset=[unit_field])[variant_field].value_counts()
    else:
        cross_assigned = None
        counts = frame[variant_field].dropna().value_counts()

    observed = {str(key): int(value) for key, value in counts.items()}
    total = sum(observed.values())
    if total == 0:
        raise ValueError("分流字段没有有效样本")
    expected_ratio = config.get("expected_ratio")
    if expected_ratio:
        ratio_map = {str(key): float(value) for key, value in expected_ratio.items()}
        missing = set(observed) - set(ratio_map)
        if missing:
            raise ValueError(f"expected_ratio 缺少分组：{sorted(missing)}")
        ratio_total = sum(ratio_map.values())
        if ratio_total <= 0:
            raise ValueError("expected_ratio 之和必须为正数")
        ratio_map = {key: value / ratio_total for key, value in ratio_map.items()}
        ratio_source = "user_specified"
    else:
        ratio_map = {key: 1.0 / len(observed) for key in observed}
        ratio_source = "assumed_equal_split"

    groups = []
    statistic = 0.0
    low_expected = False
    for key in sorted(observed):
        expected_count = ratio_map[key] * total
        if expected_count < 5:
            low_expected = True
        contribution = (observed[key] - expected_count) ** 2 / expected_count if expected_count else None
        if contribution is not None:
            statistic += contribution
        groups.append({
            "variant": key,
            "observed": observed[key],
            "expected": expected_count,
            "observed_share": observed[key] / total,
            "expected_share": ratio_map[key],
            "delta": observed[key] - expected_count,
            "chi_square_contribution": contribution,
        })

    degrees_of_freedom = max(len(observed) - 1, 1)
    p_value = chi_square_p(statistic, degrees_of_freedom)
    alpha = float(config.get("alpha", 0.001))
    passed = p_value is not None and p_value >= alpha

    limitations = [
        "SRM 检验只能发现分流比例异常，不能定位是分流服务、埋点还是过滤条件造成的。",
    ]
    if ratio_source == "assumed_equal_split":
        limitations.append("未提供 expected_ratio，按等比分流假设检验；若实验本身不是等比，结论无效。")
    if low_expected:
        limitations.append("存在期望频数小于 5 的分组，卡方近似不可靠。")
    if unit_field is None:
        limitations.append("未提供 unit_field，未检查一个单位是否被分到多个组。")
    elif cross_assigned:
        limitations.append(f"有 {cross_assigned} 个分流单位出现在多个组，必须先修分流再解读效应。")

    return {
        "op": "srm_check",
        "variant_field": variant_field,
        "unit_field": unit_field,
        "total_units": total,
        "expected_ratio_source": ratio_source,
        "groups": groups,
        "chi_square": statistic,
        "degrees_of_freedom": degrees_of_freedom,
        "p_value": p_value,
        "alpha": alpha,
        "srm_detected": (not passed) if p_value is not None else None,
        "cross_assigned_units": cross_assigned,
        "status": "pass" if passed and not cross_assigned else "block",
        "verdict": (
            "分流比例与预期一致，可继续解读效应"
            if passed and not cross_assigned
            else "分流存在问题，效应解读必须阻断"
        ),
        "limitations": limitations,
    }


def op_multiple_testing(frame: pd.DataFrame | None, config: dict) -> dict:
    """多重比较校正：Bonferroni / Holm / Benjamini-Hochberg。

    在多个分群、多个指标或多个时间窗上反复检验时，
    未校正的 p 值会系统性高估显著性数量。
    """
    raw_tests = config.get("tests")
    if not raw_tests:
        raise ValueError("需要提供 tests 列表，每项含 label 与 p_value")
    method = str(config.get("method", "bh")).lower()
    if method not in {"bh", "holm", "bonferroni"}:
        raise ValueError("method 必须是 bh、holm 或 bonferroni")
    alpha = float(config.get("alpha", 0.05))
    if not 0 < alpha < 1:
        raise ValueError("alpha 必须位于 0 和 1 之间")

    tests = []
    for index, item in enumerate(raw_tests):
        p_value = item.get("p_value")
        if p_value is None or not math.isfinite(float(p_value)):
            raise ValueError(f"第 {index + 1} 个检验缺少有效 p_value")
        p_value = float(p_value)
        if not 0 <= p_value <= 1:
            raise ValueError(f"p_value 必须位于 0 和 1 之间：{p_value}")
        tests.append({
            "label": str(item.get("label") or f"test_{index + 1}"),
            "p_value": p_value,
            "prespecified": bool(item.get("prespecified", False)),
            "order": index,
        })

    count = len(tests)
    ordered = sorted(tests, key=lambda item: item["p_value"])
    if method == "bonferroni":
        for item in ordered:
            item["adjusted_p"] = min(1.0, item["p_value"] * count)
    elif method == "holm":
        running = 0.0
        for rank, item in enumerate(ordered, start=1):
            running = max(running, min(1.0, item["p_value"] * (count - rank + 1)))
            item["adjusted_p"] = running
    else:
        running = 1.0
        for rank in range(count, 0, -1):
            item = ordered[rank - 1]
            running = min(running, min(1.0, item["p_value"] * count / rank))
            item["adjusted_p"] = running

    for item in ordered:
        item["rejected_raw"] = item["p_value"] < alpha
        item["rejected_adjusted"] = item["adjusted_p"] < alpha

    exploratory = [item["label"] for item in ordered if not item["prespecified"] and item["rejected_adjusted"]]
    limitations = [
        "校正后仍显著不等于因果；它只说明该差异不容易由多重比较的随机性解释。",
    ]
    if any(not item["prespecified"] for item in tests):
        limitations.append("存在未预先声明的检验，其结论只能作为探索性发现，需要独立样本复现。")
    if method == "bh":
        limitations.append("BH 控制的是错误发现率（FDR），不是族错误率（FWER）；单条结论的确定性弱于 Holm。")

    return {
        "op": "multiple_testing",
        "method": method,
        "alpha": alpha,
        "test_count": count,
        "significant_before_correction": sum(1 for item in ordered if item["rejected_raw"]),
        "significant_after_correction": sum(1 for item in ordered if item["rejected_adjusted"]),
        "exploratory_significant_labels": exploratory,
        "tests": [
            {key: item[key] for key in ("label", "p_value", "adjusted_p", "prespecified", "rejected_raw", "rejected_adjusted")}
            for item in sorted(ordered, key=lambda item: item["order"])
        ],
        "limitations": limitations,
    }


def op_cuped(frame: pd.DataFrame, config: dict) -> dict:
    """CUPED 方差缩减：用处理前协变量降低实验指标方差。

    协变量必须是处理发生之前的观测值；用处理后的变量做 CUPED 会引入偏差。
    """
    variant_field = config["variant_field"]
    metric_field_name = config["metric_field"]
    covariate_field = config["covariate_field"]
    for field in (variant_field, metric_field_name, covariate_field):
        if field not in frame.columns:
            raise ValueError(f"字段不存在：{field}")
    control_label = str(config.get("control", "A"))
    treatment_label = str(config.get("treatment", "B"))
    confidence_level = float(config.get("confidence_level", 0.95))
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level 必须位于 0 和 1 之间")
    z_critical = NORMAL.inv_cdf(0.5 + confidence_level / 2)

    work = frame[[variant_field, metric_field_name, covariate_field]].copy()
    work[variant_field] = work[variant_field].astype(str)
    work[metric_field_name] = to_numeric(work[metric_field_name])
    work[covariate_field] = to_numeric(work[covariate_field])
    work = work.dropna()
    work = work[work[variant_field].isin([control_label, treatment_label])]
    if work.empty:
        raise ValueError("处理组或对照组没有同时具备指标与协变量的有效样本")

    y = work[metric_field_name].to_numpy(dtype=float)
    x = work[covariate_field].to_numpy(dtype=float)
    if len(y) < 4:
        raise ValueError("CUPED 至少需要 4 条有效样本")
    x_variance = float(np.var(x, ddof=1))
    if x_variance <= 0:
        raise ValueError("协变量方差为 0，无法做 CUPED 调整")
    theta = float(np.cov(y, x, ddof=1)[0, 1] / x_variance)
    x_mean = float(np.mean(x))
    work["__adjusted"] = y - theta * (x - x_mean)

    def arm_summary(label: str, column: str) -> dict:
        values = work.loc[work[variant_field] == label, column].to_numpy(dtype=float)
        if len(values) < 2:
            raise ValueError(f"分组 {label} 有效样本不足 2 条")
        return {"label": label, "n": int(len(values)), "mean": float(values.mean()), "variance": float(np.var(values, ddof=1))}

    def effect_of(column: str) -> dict:
        control = arm_summary(control_label, column)
        treatment = arm_summary(treatment_label, column)
        se = math.sqrt(control["variance"] / control["n"] + treatment["variance"] / treatment["n"])
        effect = treatment["mean"] - control["mean"]
        z = effect / se if se > 0 else None
        return {
            "control": control,
            "treatment": treatment,
            "effect": effect,
            "standard_error": se,
            "ci": [effect - z_critical * se, effect + z_critical * se] if se > 0 else [None, None],
            "z": z,
            "p_value": normal_two_sided_p(z),
        }

    raw = effect_of(metric_field_name)
    adjusted = effect_of("__adjusted")
    pre_control = arm_summary(control_label, covariate_field)
    pre_treatment = arm_summary(treatment_label, covariate_field)
    pre_se = math.sqrt(pre_control["variance"] / pre_control["n"] + pre_treatment["variance"] / pre_treatment["n"])
    pre_diff = pre_treatment["mean"] - pre_control["mean"]
    pre_z = pre_diff / pre_se if pre_se > 0 else None
    pre_p = normal_two_sided_p(pre_z)
    correlation = float(np.corrcoef(y, x)[0, 1]) if np.var(y, ddof=1) > 0 else None
    variance_reduction = (
        1 - float(np.var(work["__adjusted"].to_numpy(dtype=float), ddof=1)) / float(np.var(y, ddof=1))
        if float(np.var(y, ddof=1)) > 0
        else None
    )

    limitations = [
        "协变量必须来自处理前窗口；使用处理后变量会把效应本身吸收进调整项。",
        "CUPED 只降低方差，不修正分流问题；SRM 未通过时结果无效。",
    ]
    if pre_p is not None and pre_p < 0.01:
        limitations.append(
            f"处理前协变量在两组间已存在显著差异（p={pre_p:.4f}），随机化可能失败，效应估计不可信。"
        )
    if correlation is not None and abs(correlation) < 0.2:
        limitations.append("协变量与指标相关性较弱，CUPED 收益有限。")

    return {
        "op": "cuped",
        "metric_field": metric_field_name,
        "covariate_field": covariate_field,
        "theta": theta,
        "covariate_metric_correlation": correlation,
        "variance_reduction": variance_reduction,
        "confidence_level": confidence_level,
        "raw_effect": raw,
        "adjusted_effect": adjusted,
        "pre_period_balance": {
            "control_mean": pre_control["mean"],
            "treatment_mean": pre_treatment["mean"],
            "difference": pre_diff,
            "z": pre_z,
            "p_value": pre_p,
            "balanced": pre_p is None or pre_p >= 0.01,
        },
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 断点检测


def _seasonal_adjust(series: pd.Series, dates: pd.Series) -> tuple[pd.Series, dict]:
    """按星期中位数做轻量季节调整，返回残差与季节因子。"""
    weekday = dates.dt.dayofweek
    overall = float(series.median())
    factors: dict[str, float] = {}
    adjusted = series.copy()
    for day in sorted(weekday.unique()):
        mask = weekday == day
        if int(mask.sum()) < 2:
            factors[str(int(day))] = 0.0
            continue
        offset = float(series[mask].median()) - overall
        factors[str(int(day))] = offset
        adjusted[mask] = series[mask] - offset
    return adjusted, factors


def op_changepoint_scan(frame: pd.DataFrame, config: dict) -> dict:
    """结构断点检测：水平漂移、趋势断点与 CUSUM 累积偏移。

    与 anomaly_scan 的区别：anomaly_scan 回答"哪一天是离群点"，
    本算子回答"指标是否在某个时点整体换了一个水平或斜率"。
    """
    date_field = config.get("date_field")
    metric_field_name = config["metric_field"]
    if metric_field_name not in frame.columns:
        raise ValueError(f"指标字段不存在：{metric_field_name}")
    if not date_field or date_field not in frame.columns:
        raise ValueError("changepoint_scan 需要存在于数据中的 date_field")

    work = frame[[date_field, metric_field_name]].copy()
    work[date_field] = parse_date_series(work[date_field]).dt.normalize()
    work[metric_field_name] = to_numeric(work[metric_field_name])
    work = work.dropna().groupby(date_field, as_index=False)[metric_field_name].sum().sort_values(date_field)
    min_segment = int(config.get("min_segment_days", 7))
    if len(work) < min_segment * 2:
        raise ValueError(f"有效日期数 {len(work)} 少于 min_segment_days 的两倍，无法检测断点")

    dates = work[date_field].reset_index(drop=True)
    values = work[metric_field_name].reset_index(drop=True)
    seasonality = str(config.get("seasonality", "weekly")).lower()
    if seasonality == "weekly" and len(work) >= 14:
        adjusted, seasonal_factors = _seasonal_adjust(values, dates)
    else:
        adjusted, seasonal_factors = values.copy(), {}
    series = adjusted.to_numpy(dtype=float)

    # 水平漂移：穷举单断点，取 Welch t 统计量最大的切点
    best: dict[str, Any] | None = None
    for index in range(min_segment, len(series) - min_segment + 1):
        before, after = series[:index], series[index:]
        var_before = float(np.var(before, ddof=1)) if len(before) > 1 else 0.0
        var_after = float(np.var(after, ddof=1)) if len(after) > 1 else 0.0
        se = math.sqrt(var_before / len(before) + var_after / len(after))
        if se <= 0:
            continue
        shift = float(after.mean() - before.mean())
        statistic = abs(shift) / se
        if best is None or statistic > best["t_statistic"]:
            best = {
                "index": index,
                "date": dates.iloc[index].strftime("%Y-%m-%d"),
                "mean_before": float(before.mean()),
                "mean_after": float(after.mean()),
                "shift": shift,
                "relative_shift": shift / float(before.mean()) if before.mean() else None,
                "standard_error": se,
                "t_statistic": statistic,
                "days_before": int(len(before)),
                "days_after": int(len(after)),
            }
    if best is not None:
        best["approximate_p_value"] = normal_two_sided_p(best["t_statistic"])
        best["ci_of_shift"] = [
            best["shift"] - 1.96 * best["standard_error"],
            best["shift"] + 1.96 * best["standard_error"],
        ]

    # 趋势断点：前后段最小二乘斜率差
    trend: dict[str, Any] | None = None
    if best is not None:
        index = best["index"]
        x_before = np.arange(index, dtype=float)
        x_after = np.arange(len(series) - index, dtype=float)
        if len(x_before) > 2 and len(x_after) > 2:
            slope_before = float(np.polyfit(x_before, series[:index], 1)[0])
            slope_after = float(np.polyfit(x_after, series[index:], 1)[0])
            trend = {
                "at_date": best["date"],
                "slope_before_per_day": slope_before,
                "slope_after_per_day": slope_after,
                "slope_change_per_day": slope_after - slope_before,
                "direction": "steeper" if abs(slope_after) > abs(slope_before) else "flatter",
            }

    # CUSUM：标准化残差的累积偏移
    median = float(np.median(series))
    mad = float(np.median(np.abs(series - median)))
    scale = max(mad * 1.4826, float(np.std(series, ddof=1)) / 3 if len(series) > 1 else 0.0, 1e-12)
    standardized = (series - median) / scale
    drift = float(config.get("cusum_drift", 0.5))
    threshold = float(config.get("cusum_threshold", 5.0))
    positive = negative = 0.0
    alarms = []
    for position, value in enumerate(standardized):
        positive = max(0.0, positive + value - drift)
        negative = max(0.0, negative - value - drift)
        if positive > threshold or negative > threshold:
            alarms.append({
                "date": dates.iloc[position].strftime("%Y-%m-%d"),
                "direction": "up" if positive > threshold else "down",
                "cusum": positive if positive > threshold else negative,
            })
            positive = negative = 0.0

    limitations = [
        "本算子只搜索单个断点；多次改版或多次事故需要按已知事件日期分段后分别检测。",
        "断点是统计结构变化，不说明原因；把断点日与已知发版、投放、口径变更对齐后才能提出机制候选。",
        "p 值按正态近似给出，且断点位置是数据挑选出来的，实际显著性弱于该数值。",
    ]
    if seasonal_factors:
        limitations.append("已做按星期的中位数季节调整；若业务存在月内周期或节假日效应，需要额外处理。")
    else:
        limitations.append("未做季节调整（日期数不足或已关闭），周内波动可能被误读为水平漂移。")

    return {
        "op": "changepoint_scan",
        "metric": metric_field_name,
        "date_field": date_field,
        "observation_window": {
            "start": dates.iloc[0].strftime("%Y-%m-%d"),
            "end": dates.iloc[-1].strftime("%Y-%m-%d"),
            "days": int(len(series)),
        },
        "seasonality": {"mode": seasonality if seasonal_factors else "none", "weekday_offsets": seasonal_factors},
        "level_shift": best,
        "trend_break": trend,
        "cusum": {"drift": drift, "threshold": threshold, "alarms": alarms, "scale": scale},
        "limitations": limitations,
    }


STAT_OPERATORS = {
    "power_mde": op_power_mde,
    "srm_check": op_srm_check,
    "multiple_testing": op_multiple_testing,
    "cuped": op_cuped,
    "changepoint_scan": op_changepoint_scan,
}

# 不需要读取数据文件的算子（纯设计/纯 p 值输入）
DATA_FREE_OPERATORS = {"power_mde", "multiple_testing"}
