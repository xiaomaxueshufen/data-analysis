"""da_verify 门禁的回归测试：确认三类漏洞已被堵住。

覆盖：
1. 不传 --evidence 时数字溯源不再被整段跳过；
2. percent / raw / 百分点 三种量纲不再互相误匹配；
3. L2 以上因果措辞必须提供合法 identification_strategy；
4. 探索性结论过多时给出多重比较警告。

运行：python3 tests/test_verify.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "scripts" / "da_verify.py"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))


def run_verify(claims: object, evidence: object | None = None, extra: list[str] | None = None) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        claims_path = base / "claims.json"
        claims_path.write_text(json.dumps(claims, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, str(VERIFY), "--claims", str(claims_path)]
        if evidence is not None:
            evidence_path = base / "evidence.json"
            evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
            command += ["--evidence", str(evidence_path)]
        command += extra or []
        completed = subprocess.run(command, capture_output=True, text=True)
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"status": "parse_error", "stdout": completed.stdout, "stderr": completed.stderr}


def codes_of(report: dict) -> set[str]:
    found: set[str] = set()
    for claim in report.get("claims", []):
        for issue in claim.get("issues", []):
            found.add(issue["code"])
    for issue in report.get("p_hacking_warnings", []):
        found.add(issue["code"])
    for issue in report.get("agent_issues", []):
        found.add(issue["code"])
    return found


# --------------------------------------------------- 漏洞一：evidence 可绕过


def test_evidence_required() -> None:
    claims = [{
        "claim_id": "C001",
        "statement": "支付成功率为 82.6%",
        "level": "L0",
        "evidence_ids": ["E001"],
        "limitations": [],
    }]
    without = run_verify(claims)
    check("漏洞1 不传 evidence 被拦截",
          "no_evidence_provided" in codes_of(without) and without["status"] == "fail",
          f"status={without['status']}")

    relaxed = run_verify(claims, extra=["--no-require-evidence"])
    check("漏洞1 显式放宽后不拦截",
          "no_evidence_provided" not in codes_of(relaxed),
          f"status={relaxed['status']}")

    with_evidence = run_verify(claims, {"success_rate": 0.826})
    check("漏洞1 传了 evidence 且可溯源时通过",
          with_evidence["status"] in {"pass", "warn"} and "untraceable_number" not in codes_of(with_evidence),
          f"status={with_evidence['status']}")


# --------------------------------------------------- 漏洞二：量纲混淆


def test_unit_confusion() -> None:
    # evidence 只有 0.116（比率），statement 写 11.6%（百分数）：应能匹配
    ok = run_verify(
        [{
            "claim_id": "C001",
            "statement": "转化率为 11.6%",
            "level": "L0",
            "evidence_ids": ["E001"],
            "limitations": [],
        }],
        {"conversion_rate": 0.116},
    )
    check("漏洞2 percent→raw 正确匹配",
          "untraceable_number" not in codes_of(ok),
          f"status={ok['status']}")

    # evidence 只有 11.6（裸数），statement 写 0.116（裸数）：不应匹配
    bad = run_verify(
        [{
            "claim_id": "C001",
            "statement": "偏离量为 0.116",
            "level": "L0",
            "evidence_ids": ["E001"],
            "limitations": [],
        }],
        {"deviation_percent_value": 11.6},
    )
    check("漏洞2 raw 不再反向匹配 percent",
          "untraceable_number" in codes_of(bad),
          f"codes={sorted(codes_of(bad))}")

    # 编造的数字必须被抓出
    fabricated = run_verify(
        [{
            "claim_id": "C001",
            "statement": "支付成功率为 95.0%",
            "level": "L0",
            "evidence_ids": ["E001"],
            "limitations": [],
        }],
        {"success_rate": 0.826},
    )
    check("漏洞2 编造数字被抓出",
          "untraceable_number" in codes_of(fabricated),
          f"codes={sorted(codes_of(fabricated))}")

    # 百分点与百分比不混用
    pp_claim = run_verify(
        [{
            "claim_id": "C001",
            "statement": "低于基线 11.6 个百分点",
            "level": "L1",
            "evidence_ids": ["E001"],
            "limitations": [],
        }],
        {"delta_pp": 0.116},
    )
    check("漏洞2 百分点量纲可识别",
          "untraceable_number" not in codes_of(pp_claim),
          f"status={pp_claim['status']}")

    strict = run_verify(
        [{
            "claim_id": "C001",
            "statement": "支付成功率为 95.0%",
            "level": "L0",
            "evidence_ids": ["E001"],
            "limitations": [],
        }],
        {"success_rate": 0.826},
        extra=["--strict"],
    )
    check("漏洞2 strict 模式升级为 fail", strict["status"] == "fail", f"status={strict['status']}")


# --------------------------------------------------- 漏洞三：因果识别策略


def test_causal_identification() -> None:
    no_strategy = run_verify(
        [{
            "claim_id": "C001",
            "statement": "新版本导致支付成功率下降",
            "level": "L2",
            "evidence_ids": ["E001", "E002"],
            "limitations": ["无对照"],
            "identification_strategy": "correlation",
        }],
        {"success_rate": 0.826},
    )
    check("漏洞3 无效识别策略被拦截",
          "causal_language_without_identification" in codes_of(no_strategy),
          f"codes={sorted(codes_of(no_strategy))}")

    valid = run_verify(
        [{
            "claim_id": "C001",
            "statement": "新版本导致支付成功率下降 11.6 个百分点",
            "level": "L2",
            "evidence_ids": ["E001", "E002"],
            "limitations": ["实验仅覆盖安卓端"],
            "identification_strategy": "randomized",
        }],
        {"delta_pp": 0.116},
    )
    check("漏洞3 合法识别策略通过",
          "causal_language_without_identification" not in codes_of(valid),
          f"status={valid['status']}")

    below_l2 = run_verify(
        [{
            "claim_id": "C001",
            "statement": "网关波动导致支付失败",
            "level": "L1",
            "evidence_ids": ["E001"],
            "limitations": [],
        }],
        {"success_rate": 0.826},
    )
    check("漏洞3 L1 用因果措辞仍被拦截",
          "causal_language_below_l2" in codes_of(below_l2),
          f"codes={sorted(codes_of(below_l2))}")


# --------------------------------------------------- 漏洞四：P-hacking


def test_p_hacking() -> None:
    many = [
        {
            "claim_id": f"C{index:03d}",
            "statement": f"分组 {index} 的转化率为 0.5",
            "level": "L1",
            "status": "hypothesis",
            "evidence_ids": ["E001"],
            "limitations": [],
        }
        for index in range(8)
    ]
    report = run_verify(many, {"rate": 0.5})
    check("漏洞4 探索性结论过多被警告",
          "multiple_comparison_risk" in codes_of(report),
          f"codes={sorted(codes_of(report))}")

    few = many[:2]
    quiet = run_verify(few, {"rate": 0.5})
    check("漏洞4 少量探索性结论不误报",
          "multiple_comparison_risk" not in codes_of(quiet),
          f"status={quiet['status']}")

    windows = [
        {
            "claim_id": f"W{index:03d}",
            "statement": "该窗口转化率为 0.5",
            "level": "L1",
            "evidence_ids": ["E001"],
            "scope": {"date_window": "2026-07-20..2026-07-27"},
            "limitations": [],
        }
        for index in range(4)
    ]
    repeated = run_verify(windows, {"rate": 0.5})
    check("漏洞4 同窗口重复检验被警告",
          "repeated_window_checks" in codes_of(repeated),
          f"codes={sorted(codes_of(repeated))}")


# --------------------------------------------------- 既有门禁未被破坏


def test_existing_gates_intact() -> None:
    l2_thin = run_verify(
        [{
            "claim_id": "C001",
            "statement": "支付链路与网关可用率同步下降",
            "level": "L2",
            "evidence_ids": ["E001"],
            "limitations": ["无对照"],
        }],
        {"gateway": 0.912},
    )
    check("既有门禁 L2 单证据被拦截",
          "l2_insufficient_evidence" in codes_of(l2_thin),
          f"codes={sorted(codes_of(l2_thin))}")

    no_evidence_ids = run_verify(
        [{"claim_id": "C001", "statement": "成功率下降", "level": "L1", "evidence_ids": [], "limitations": []}],
        {"rate": 0.5},
    )
    check("既有门禁 缺 evidence_ids 被拦截",
          "missing_evidence" in codes_of(no_evidence_ids))

    agents_missing = run_verify(
        [{"claim_id": "C001", "statement": "成功率为 0.5", "level": "L1", "evidence_ids": ["E1"], "limitations": []}],
        {"rate": 0.5},
        extra=["--agents-dir", "/tmp/nonexistent_agents_dir_xyz", "--require-agent-manifest"],
    )
    check("既有门禁 缺角色工件被拦截",
          "missing_agent_artifact" in codes_of(agents_missing) and agents_missing["status"] == "fail",
          f"status={agents_missing['status']}")

    clean = run_verify(
        [{
            "claim_id": "C001",
            "statement": "2026-07-27 支付成功率为 82.6%",
            "level": "L0",
            "evidence_ids": ["E001"],
            "limitations": ["单日观测"],
        }],
        {"success_rate": 0.826},
    )
    check("既有门禁 合规结论通过", clean["status"] == "pass", f"status={clean['status']}")
    check("既有门禁 报告证据数量", clean.get("evidence_summary", {}).get("numbers_collected", 0) >= 1)


def main() -> int:
    for suite in (
        test_evidence_required,
        test_unit_confusion,
        test_causal_identification,
        test_p_hacking,
        test_existing_gates_intact,
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
