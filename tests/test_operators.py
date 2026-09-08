"""新增算子的自检脚本：用合成数据跑通所有算子，并断言关键性质。

不依赖外部测试框架。运行：python3 tests/test_operators.py
合成数据在内存构造，不落盘，不需要示例数据文件。

依赖检查：本脚本依赖 numpy / pandas / 项目内 da_growth / da_stats。
缺少 numpy 或 pandas 时，下面的 `_ensure_dependencies()` 会给出可执行
的安装指引（包括 PEP 668 系统的 venv / --break-system-packages 两种
解法），不会直接抛 ModuleNotFoundError。
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_MODULES = ("numpy", "pandas")
REQUIREMENTS_FILE = "requirements.txt"


def _ensure_dependencies() -> None:
    missing = [name for name in REQUIRED_MODULES if _try_import(name) is None]
    if not missing:
        return
    print("=" * 64, file=sys.stderr)
    print(f"[test_operators] 缺少依赖: {', '.join(missing)}", file=sys.stderr)
    print("本测试需要 numpy 和 pandas，请按下面任一方式安装：", file=sys.stderr)
    print("", file=sys.stderr)
    print("  方式一：使用项目根目录的 requirements.txt（推荐）", file=sys.stderr)
    print(f"    pip install -r {REQUIREMENTS_FILE}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  方式二：在虚拟环境里安装（推荐，避免污染系统 Python）", file=sys.stderr)
    print("    python3 -m venv .venv", file=sys.stderr)
    print("    source .venv/bin/activate", file=sys.stderr)
    print(f"    pip install -r {REQUIREMENTS_FILE}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  方式三：受 PEP 668 限制的系统 Python，可显式覆盖", file=sys.stderr)
    print(f"    pip install --break-system-packages -r {REQUIREMENTS_FILE}", file=sys.stderr)
    print("=" * 64, file=sys.stderr)
    sys.exit(2)


def _try_import(name: str):
    try:
        return __import__(name)
    except ImportError:
        return None


_ensure_dependencies()

import numpy as np  # noqa: E402  (import after dependency check)
import pandas as pd  # noqa: E402  (import after dependency check)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from da_growth import (  # noqa: E402
    op_attribution,
    op_cohort_retention,
    op_path_analysis,
    op_price_elasticity,
    op_rfm,
    op_survival,
)
from da_stats import (  # noqa: E402
    chi_square_p,
    op_changepoint_scan,
    op_cuped,
    op_multiple_testing,
    op_power_mde,
    op_srm_check,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))


# ---------------------------------------------------------------- 分布函数


def test_chi_square() -> None:
    # 已知值：df=1 时 p(3.841) ≈ 0.05；df=2 时 p(5.991) ≈ 0.05
    check("chi_square df=1", abs(chi_square_p(3.8415, 1) - 0.05) < 0.001, f"{chi_square_p(3.8415, 1):.5f}")
    check("chi_square df=2", abs(chi_square_p(5.9915, 2) - 0.05) < 0.001, f"{chi_square_p(5.9915, 2):.5f}")
    check("chi_square df=3", abs(chi_square_p(7.8147, 3) - 0.05) < 0.001, f"{chi_square_p(7.8147, 3):.5f}")
    check("chi_square 零统计量", chi_square_p(0.0, 1) == 1.0)


# ---------------------------------------------------------------- 实验设计


def test_power_mde() -> None:
    # 教科书对照：p=0.5, MDE=0.05 绝对, alpha=0.05, power=0.8 → 每组约 1570
    result = op_power_mde(None, {
        "metric_type": "binary",
        "baseline_rate": 0.5,
        "mde_absolute": 0.05,
        "alpha": 0.05,
        "power": 0.8,
        "daily_traffic_per_arm": 500,
    })
    n = result["given_mde"]["n_control"]
    check("power_mde 二元样本量量级", 1500 <= n <= 1650, f"n_control={n}")
    check("power_mde 天数", result["given_mde"]["days_needed"] == -(-n // 500))
    check("power_mde 功效曲线单调", all(
        result["power_curve"][i]["n_control"] >= result["power_curve"][i + 1]["n_control"]
        for i in range(len(result["power_curve"]) - 1)
    ), "效应越大所需样本越少")

    reverse = op_power_mde(None, {
        "metric_type": "binary",
        "baseline_rate": 0.5,
        "n_per_arm": n,
        "alpha": 0.05,
        "power": 0.8,
    })
    detectable = reverse["given_sample_size"]["detectable_absolute_effect"]
    check("power_mde 反解 MDE 自洽", abs(detectable - 0.05) < 0.005, f"detectable={detectable:.4f}")

    continuous = op_power_mde(None, {
        "metric_type": "continuous",
        "baseline_mean": 100.0,
        "baseline_sd": 30.0,
        "mde_relative": 0.05,
        "alpha": 0.05,
        "power": 0.8,
    })
    check("power_mde 连续指标", continuous["given_mde"]["n_control"] > 0,
          f"n={continuous['given_mde']['n_control']}")


def test_srm() -> None:
    rng = np.random.default_rng(7)
    balanced = pd.DataFrame({
        "uid": range(20000),
        "variant": rng.choice(["A", "B"], size=20000),
    })
    ok = op_srm_check(balanced, {"variant_field": "variant", "unit_field": "uid"})
    check("srm 均衡分流通过", ok["status"] == "pass" and ok["srm_detected"] is False,
          f"p={ok['p_value']:.4f}")

    skewed = pd.DataFrame({
        "uid": range(20000),
        "variant": ["A"] * 10800 + ["B"] * 9200,
    })
    bad = op_srm_check(skewed, {"variant_field": "variant", "unit_field": "uid"})
    check("srm 失衡被阻断", bad["status"] == "block" and bad["srm_detected"] is True,
          f"p={bad['p_value']:.2e}")

    # 一个单位跨组必须被发现并阻断
    cross = pd.DataFrame({"uid": [1, 1, 2, 3, 4, 5] * 200, "variant": ["A", "B", "A", "B", "A", "B"] * 200})
    crossed = op_srm_check(cross, {"variant_field": "variant", "unit_field": "uid"})
    check("srm 跨组单位被发现", crossed["cross_assigned_units"] > 0 and crossed["status"] == "block",
          f"cross={crossed['cross_assigned_units']}")

    # 非等比分流：提供 expected_ratio 后应通过
    unequal = pd.DataFrame({"uid": range(10000), "variant": ["A"] * 9000 + ["B"] * 1000})
    with_ratio = op_srm_check(unequal, {
        "variant_field": "variant",
        "unit_field": "uid",
        "expected_ratio": {"A": 0.9, "B": 0.1},
    })
    check("srm 非等比分流", with_ratio["status"] == "pass", f"p={with_ratio['p_value']:.4f}")


def test_multiple_testing() -> None:
    tests = [
        {"label": "primary", "p_value": 0.002, "prespecified": True},
        {"label": "seg_a", "p_value": 0.011},
        {"label": "seg_b", "p_value": 0.03},
        {"label": "seg_c", "p_value": 0.04},
        {"label": "seg_d", "p_value": 0.20},
    ]
    bh = op_multiple_testing(None, {"tests": tests, "method": "bh", "alpha": 0.05})
    bonf = op_multiple_testing(None, {"tests": tests, "method": "bonferroni", "alpha": 0.05})
    holm = op_multiple_testing(None, {"tests": tests, "method": "holm", "alpha": 0.05})

    check("multiple_testing 校正后不增多",
          bh["significant_after_correction"] <= bh["significant_before_correction"],
          f"{bh['significant_before_correction']} → {bh['significant_after_correction']}")
    check("multiple_testing Bonferroni 最保守",
          bonf["significant_after_correction"] <= bh["significant_after_correction"],
          f"bonf={bonf['significant_after_correction']} bh={bh['significant_after_correction']}")
    check("multiple_testing Holm 介于两者之间",
          bonf["significant_after_correction"] <= holm["significant_after_correction"] <= bh["significant_after_correction"])
    check("multiple_testing 调整值单调",
          all(
              item["adjusted_p"] >= item["p_value"] - 1e-12
              for item in bh["tests"]
          ), "调整后 p 不小于原始 p")
    check("multiple_testing 标记探索性检验",
          "seg_a" in bh["exploratory_significant_labels"] or bh["significant_after_correction"] == 1,
          str(bh["exploratory_significant_labels"]))


def test_cuped() -> None:
    rng = np.random.default_rng(11)
    n = 4000
    pre = rng.normal(100, 20, n)
    variant = rng.choice(["A", "B"], size=n)
    lift = np.where(variant == "B", 3.0, 0.0)
    post = 0.8 * pre + lift + rng.normal(0, 10, n)
    frame = pd.DataFrame({"variant": variant, "post": post, "pre": pre})
    result = op_cuped(frame, {
        "variant_field": "variant",
        "metric_field": "post",
        "covariate_field": "pre",
        "control": "A",
        "treatment": "B",
    })
    check("cuped 降低方差", result["variance_reduction"] > 0.5,
          f"reduction={result['variance_reduction']:.3f}")
    check("cuped 收窄置信区间",
          (result["adjusted_effect"]["ci"][1] - result["adjusted_effect"]["ci"][0])
          < (result["raw_effect"]["ci"][1] - result["raw_effect"]["ci"][0]),
          "调整后 CI 更窄")
    check("cuped 效应估计不偏", abs(result["adjusted_effect"]["effect"] - 3.0) < 1.0,
          f"effect={result['adjusted_effect']['effect']:.3f}")
    check("cuped 处理前均衡检查", result["pre_period_balance"]["balanced"] is True,
          f"pre p={result['pre_period_balance']['p_value']:.3f}")


def test_changepoint() -> None:
    rng = np.random.default_rng(3)
    dates = pd.date_range("2026-01-01", periods=90, freq="D")
    values = np.concatenate([rng.normal(1000, 30, 50), rng.normal(880, 30, 40)])
    frame = pd.DataFrame({"date": dates, "orders": values})
    result = op_changepoint_scan(frame, {"date_field": "date", "metric_field": "orders", "min_segment_days": 10})
    detected = pd.Timestamp(result["level_shift"]["date"])
    truth = dates[50]
    check("changepoint 定位准确", abs((detected - truth).days) <= 3,
          f"detected={result['level_shift']['date']} truth={truth.date()}")
    check("changepoint 方向正确", result["level_shift"]["shift"] < 0,
          f"shift={result['level_shift']['shift']:.1f}")
    check("changepoint CUSUM 报警", len(result["cusum"]["alarms"]) > 0,
          f"alarms={len(result['cusum']['alarms'])}")

    # 无断点数据不应给出强统计量
    flat = pd.DataFrame({"date": dates, "orders": rng.normal(1000, 30, 90)})
    quiet = op_changepoint_scan(flat, {"date_field": "date", "metric_field": "orders", "min_segment_days": 10})
    check("changepoint 平稳序列不误报",
          quiet["level_shift"]["approximate_p_value"] > 0.01,
          f"p={quiet['level_shift']['approximate_p_value']:.3f}")


# ---------------------------------------------------------------- 增长算子


def test_attribution() -> None:
    rows = []
    base = pd.Timestamp("2026-03-01")
    # 200 条 SEM → 社交 → 直接 的三触点转化路径
    for uid in range(200):
        for offset, channel in enumerate(["sem", "social", "direct"]):
            rows.append({"uid": uid, "channel": channel, "ts": base + pd.Timedelta(days=offset), "converted": 0, "value": 0})
        rows[-1]["converted"] = 1
        rows[-1]["value"] = 100
    frame = pd.DataFrame(rows)
    result = op_attribution(frame, {
        "id_field": "uid",
        "channel_field": "channel",
        "timestamp_field": "ts",
        "conversion_field": "converted",
        "value_field": "value",
        "half_life_days": 7,
    })
    by_channel = {item["channel"]: item for item in result["channels"]}
    check("attribution first_touch 全给首触点",
          abs(by_channel["sem"]["first_touch_share"] - 1.0) < 1e-9,
          f"sem={by_channel['sem']['first_touch_share']:.3f}")
    check("attribution last_touch 全给末触点",
          abs(by_channel["direct"]["last_touch_share"] - 1.0) < 1e-9,
          f"direct={by_channel['direct']['last_touch_share']:.3f}")
    check("attribution linear 均分",
          all(abs(by_channel[c]["linear_share"] - 1 / 3) < 1e-9 for c in ("sem", "social", "direct")))
    check("attribution 各模型总额对账",
          all(
              abs(item["credited_total"] - item["conversion_total"]) < 1e-6
              for item in result["reconciliation"].values()
          ), "分配总额等于转化总额")
    check("attribution time_decay 偏向近端",
          by_channel["direct"]["time_decay"] > by_channel["sem"]["time_decay"],
          f"direct={by_channel['direct']['time_decay']:.1f} sem={by_channel['sem']['time_decay']:.1f}")
    check("attribution 输出模型分歧度",
          by_channel["sem"]["model_disagreement"] is not None and by_channel["sem"]["model_disagreement"] > 0)


def test_cohort_retention() -> None:
    rng = np.random.default_rng(5)
    rows = []
    for cohort_week in range(6):
        cohort_start = pd.Timestamp("2026-01-05") + pd.Timedelta(weeks=cohort_week)
        for uid in range(200):
            entity = f"c{cohort_week}_u{uid}"
            rows.append({"uid": entity, "date": cohort_start})
            alive = True
            for week in range(1, 9):
                if not alive:
                    break
                if rng.random() < 0.7:  # 每周 70% 概率继续活跃
                    rows.append({"uid": entity, "date": cohort_start + pd.Timedelta(weeks=week)})
                else:
                    alive = False
    frame = pd.DataFrame(rows)
    result = op_cohort_retention(frame, {
        "id_field": "uid",
        "date_field": "date",
        "period": "week",
        "max_periods": 8,
        "min_cohort_size": 30,
    })
    check("cohort 第0期留存为1",
          all(
              abs(item["periods"][0]["retention_rate"] - 1.0) < 1e-9
              for item in result["cohorts"]
          ))
    check("cohort 留存单调不增",
          all(
              all(
                  item["periods"][i]["retention_rate"] >= item["periods"][i + 1]["retention_rate"] - 1e-9
                  for i in range(len(item["periods"]) - 1)
              )
              for item in result["cohorts"]
          ), "同 cohort 的留存不应回升")
    check("cohort 标记未成熟", any(not item["mature"] for item in result["cohorts"]),
          f"cohorts={len(result['cohorts'])}")
    check("cohort 平均曲线仅用成熟组", len(result["mature_cohort_average_curve"]) > 0)
    check("cohort 披露左截断风险",
          any("左截断" in text for text in result["limitations"]))


def test_survival() -> None:
    rng = np.random.default_rng(13)
    # A 组风险高（存续短），B 组风险低
    fast = rng.exponential(20, 600)
    slow = rng.exponential(40, 600)
    horizon = 60
    frame = pd.DataFrame({
        "days": np.concatenate([np.minimum(fast, horizon), np.minimum(slow, horizon)]),
        "churned": np.concatenate([(fast <= horizon).astype(int), (slow <= horizon).astype(int)]),
        "plan": ["A"] * 600 + ["B"] * 600,
    })
    result = op_survival(frame, {
        "duration_field": "days",
        "event_field": "churned",
        "group_field": "plan",
        "survival_at_times": [7, 30],
    })
    check("survival 曲线单调不增",
          all(
              result["overall"]["curve"][i]["survival"] >= result["overall"]["curve"][i + 1]["survival"] - 1e-12
              for i in range(len(result["overall"]["curve"]) - 1)
          ))
    groups = {item["group"]: item for item in result["groups"]}
    check("survival 区分快慢流失组",
          groups["A"]["median_survival_time"] < groups["B"]["median_survival_time"],
          f"A={groups['A']['median_survival_time']} B={groups['B']['median_survival_time']}")
    check("survival log-rank 检出差异",
          result["log_rank"] is not None and result["log_rank"]["p_value"] < 0.01,
          f"p={result['log_rank']['p_value']:.2e}" if result["log_rank"] else "none")
    check("survival 记录删失", result["overall"]["censored"] > 0,
          f"censored={result['overall']['censored']}")
    check("survival 指定时点存活率", len(result["overall"]["survival_at_times"]) == 2)

    # 无 event_field 时必须披露全部按已流失处理
    no_event = op_survival(frame[["days"]], {"duration_field": "days"})
    check("survival 无事件字段时披露偏差",
          any("按已流失处理" in text for text in no_event["limitations"]))


def test_path_analysis() -> None:
    rows = []
    base = pd.Timestamp("2026-04-01 10:00:00")
    for uid in range(300):
        steps = ["home", "search", "detail", "cart", "pay"] if uid % 3 == 0 else ["home", "search", "detail", "detail", "exit"]
        for offset, step in enumerate(steps):
            rows.append({"uid": uid, "step": step, "ts": base + pd.Timedelta(minutes=offset * 2)})
    frame = pd.DataFrame(rows)
    result = op_path_analysis(frame, {
        "id_field": "uid",
        "step_field": "step",
        "timestamp_field": "ts",
        "terminal_steps": ["pay"],
        "session_gap_minutes": 30,
    })
    check("path 识别唯一入口",
          result["entries"][0]["step"] == "home" and abs(result["entries"][0]["share"] - 1.0) < 1e-9)
    check("path 识别自环", any(item["step"] == "detail" for item in result["self_loops"]),
          f"loops={result['self_loops']}")
    check("path 终点到达率合理",
          abs(result["terminal_reach_rate"] - 100 / 300) < 0.02,
          f"reach={result['terminal_reach_rate']:.3f}")
    check("path 转移份额归一",
          all(
              0 <= item["share_of_outgoing"] <= 1
              for item in result["transitions"]
              if item["share_of_outgoing"] is not None
          ))
    check("path 输出高频路径", len(result["top_paths"]) >= 2)


def test_rfm() -> None:
    rng = np.random.default_rng(17)
    rows = []
    reference = pd.Timestamp("2026-06-30")
    for uid in range(1000):
        purchases = rng.integers(1, 20)
        for _ in range(purchases):
            rows.append({
                "uid": f"u{uid}",
                "date": reference - pd.Timedelta(days=int(rng.integers(1, 300))),
                "amount": float(rng.gamma(2, 50)),
            })
    frame = pd.DataFrame(rows)
    result = op_rfm(frame, {
        "id_field": "uid",
        "date_field": "date",
        "value_field": "amount",
        "bins": 5,
        "reference_date": "2026-06-30",
    })
    check("rfm 分层覆盖全部实体",
          abs(sum(item["size"] for item in result["segments"]) - result["entity_count"]) == 0,
          f"entities={result['entity_count']}")
    check("rfm 份额之和为1",
          abs(sum(item["share_of_entities"] for item in result["segments"]) - 1.0) < 1e-9)
    check("rfm 金额份额之和为1",
          abs(sum(item["share_of_monetary"] for item in result["segments"]) - 1.0) < 1e-9)
    check("rfm 披露不预测响应",
          any("不预测对具体动作的响应" in text for text in result["limitations"]))
    check("rfm 输出分位切点", len(result["score_cutoffs"]["monetary_quantiles"]) == 6)


def test_price_elasticity() -> None:
    rng = np.random.default_rng(19)
    price = rng.uniform(50, 150, 200)
    # 真实弹性 -1.5
    quantity = np.exp(10 - 1.5 * np.log(price) + rng.normal(0, 0.1, 200))
    frame = pd.DataFrame({"price": price, "qty": quantity, "sku": rng.choice(["s1", "s2"], 200)})
    result = op_price_elasticity(frame, {
        "price_field": "price",
        "quantity_field": "qty",
        "group_field": "sku",
    })
    check("elasticity 估计接近真值",
          abs(result["overall"]["elasticity"] + 1.5) < 0.15,
          f"elasticity={result['overall']['elasticity']:.3f}")
    check("elasticity 判定弹性需求", result["overall"]["demand_type"] == "elastic")
    check("elasticity 收入方向", result["overall"]["revenue_direction_of_price_increase"] == "revenue_falls")
    check("elasticity 观测口径上限为L1",
          result["identification"]["max_claim_level"] == "L1",
          "非随机化定价不得升到 L2")
    check("elasticity 分组估计", len(result["groups"]) == 2)

    # 正弹性必须被警告
    reversed_frame = pd.DataFrame({
        "price": price,
        "qty": np.exp(2 + 1.2 * np.log(price) + rng.normal(0, 0.1, 200)),
    })
    odd = op_price_elasticity(reversed_frame, {"price_field": "price", "quantity_field": "qty"})
    check("elasticity 正弹性被警告",
          any("与需求定律相反" in text for text in odd["limitations"]))


# ---------------------------------------------------------------- 错误路径


def test_error_paths() -> None:
    def expect_error(name: str, func, *args) -> None:
        try:
            func(*args)
        except (ValueError, KeyError) as error:
            check(name, True, f"正确报错：{str(error)[:40]}")
        else:
            check(name, False, "应当报错但返回了结果")

    frame = pd.DataFrame({"a": [1, 2, 3]})
    expect_error("错误处理 缺失字段", op_attribution, frame, {
        "id_field": "uid", "channel_field": "ch", "timestamp_field": "ts",
    })
    expect_error("错误处理 无时间字段的断点检测", op_changepoint_scan, frame, {"metric_field": "a"})
    expect_error("错误处理 零价格方差", op_price_elasticity,
                 pd.DataFrame({"p": [10.0] * 20, "q": list(range(1, 21))}),
                 {"price_field": "p", "quantity_field": "q"})
    expect_error("错误处理 MDE 缺参", op_power_mde, None, {"baseline_rate": 0.5})
    expect_error("错误处理 非法 alpha", op_power_mde, None,
                 {"baseline_rate": 0.5, "mde_absolute": 0.01, "alpha": 1.5})
    expect_error("错误处理 空 tests", op_multiple_testing, None, {"tests": []})
    expect_error("错误处理 越界 p 值", op_multiple_testing, None,
                 {"tests": [{"label": "x", "p_value": 1.4}]})
    expect_error("错误处理 cohort 缺实体字段", op_cohort_retention, frame,
                 {"id_field": "uid", "date_field": "date"})
    expect_error("错误处理 样本不足的弹性", op_price_elasticity,
                 pd.DataFrame({"p": [10.0, 20.0], "q": [5.0, 3.0]}),
                 {"price_field": "p", "quantity_field": "q"})


def main() -> int:
    for suite in (
        test_chi_square,
        test_power_mde,
        test_srm,
        test_multiple_testing,
        test_cuped,
        test_changepoint,
        test_attribution,
        test_cohort_retention,
        test_survival,
        test_path_analysis,
        test_rfm,
        test_price_elasticity,
        test_error_paths,
    ):
        try:
            suite()
        except Exception as error:  # noqa: BLE001
            check(f"{suite.__name__} 执行异常", False, f"{type(error).__name__}: {error}")

    failed = [item for item in RESULTS if not item[1]]
    for name, ok, detail in RESULTS:
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}" + (f" — {detail}" if detail else ""))
    print(f"\n共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
