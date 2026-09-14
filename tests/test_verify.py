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
import pathlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "scripts" / "da_verify.py"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    if not condition:
        # pytest 只把异常当失败；不抛的话断言失败会被静默吞掉
        raise AssertionError(f"{name}" + (f" — {detail}" if detail else ""))


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
        {"delta_pp": -0.116},
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
        {"evidence": [{"id": "E001", "kind": "computation", "value": 0.826, "verified": True}]},
    )
    check("既有门禁 合规结论通过", clean["status"] == "pass", f"status={clean['status']}")
    check("既有门禁 报告证据数量", clean.get("evidence_summary", {}).get("numbers_collected", 0) >= 1)




# --------------------------------------------------- 漏洞五：数字张冠李戴


def test_scoped_evidence_binding() -> None:
    """结论只能用它自己 evidence_ids 指向的那条证据里的数字。

    0.6.0 把所有证据数字并成一个「数字袋」，于是「渠道A 贡献 900」可以拿
    「渠道B = 900」来溯源并判 pass。
    """
    evidence = {
        "evidence": [
            {"id": "E_A", "kind": "computation", "metric": "channel_A", "value": 632, "verified": True},
            {"id": "E_B", "kind": "computation", "metric": "channel_B", "value": 900, "verified": True},
        ]
    }
    borrowed = run_verify(
        [{
            "claim_id": "C001",
            "statement": "渠道A 贡献了 900 单的缺口",
            "level": "L1",
            "evidence_ids": ["E_A"],
            "limitations": ["口径单一"],
        }],
        evidence,
    )
    check("漏洞5 借用他人证据的数字被拦截",
          "untraceable_number" in codes_of(borrowed) and borrowed["status"] == "fail",
          f"status={borrowed['status']}")

    own = run_verify(
        [{
            "claim_id": "C001",
            "statement": "渠道A 贡献了 632 单的缺口",
            "level": "L1",
            "evidence_ids": ["E_A"],
            "limitations": ["口径单一"],
        }],
        evidence,
    )
    check("漏洞5 绑定到自己的证据可通过",
          "untraceable_number" not in codes_of(own) and own["status"] == "pass",
          f"status={own['status']}")

    unresolved = run_verify(
        [{
            "claim_id": "C001",
            "statement": "渠道A 贡献了 632 单的缺口",
            "level": "L1",
            "evidence_ids": ["E_NOT_EXIST"],
            "limitations": ["口径单一"],
        }],
        evidence,
    )
    strict_ids = run_verify(
        [{
            "claim_id": "C001",
            "statement": "渠道A 贡献了 632 单的缺口",
            "level": "L1",
            "evidence_ids": ["E_NOT_EXIST"],
            "limitations": ["口径单一"],
        }],
        evidence,
        extra=["--require-evidence-ids"],
    )
    check("漏洞5 引用不存在的条目默认只提示",
          "unresolved_evidence_ids" in codes_of(unresolved) and unresolved["status"] == "pass",
          f"status={unresolved['status']}")
    check("漏洞5 --require-evidence-ids 下直接失败",
          strict_ids["status"] == "fail", f"status={strict_ids['status']}")

    legacy = run_verify(
        [{
            "claim_id": "C001",
            "statement": "转化率为 0.5",
            "level": "L0",
            "evidence_ids": ["E001"],
            "limitations": ["单日观测"],
        }],
        {"rate": 0.5},
    )
    check("漏洞5 自由结构证据标注弱模式",
          "unscoped_evidence" in codes_of(legacy), f"status={legacy['status']}")


# --------------------------------------------------- 漏洞六：方向写反 / 符号丢失


def test_direction_and_sign() -> None:
    """下降 / 上升必须与证据符号一致，显式负号必须能读出来。"""
    evidence = {"evidence": [{"id": "E001", "kind": "computation", "delta": -0.2045, "verified": True}]}

    def run(statement: str) -> dict:
        return run_verify(
            [{
                "claim_id": "C001",
                "statement": statement,
                "level": "L1",
                "evidence_ids": ["E001"],
                "limitations": ["单断点"],
            }],
            evidence,
        )

    down = run("3月1日起订单量下降了 20.45%")
    up = run("3月1日起订单量上升了 20.45%")
    explicit = run("3月1日起订单量变化 -20.45%")
    check("漏洞6 方向一致（下降 vs 负证据）可溯源",
          "untraceable_number" not in codes_of(down), f"codes={sorted(codes_of(down))}")
    check("漏洞6 方向写反（上升 vs 负证据）被拦截",
          "untraceable_number" in codes_of(up) and up["status"] == "fail",
          f"status={up['status']}")
    check("漏洞6 显式负号可正确匹配",
          "untraceable_number" not in codes_of(explicit), f"codes={sorted(codes_of(explicit))}")

    signed_evidence = {"evidence": [{"id": "E001", "kind": "computation", "delta": -200, "verified": True}]}
    absolute = run_verify(
        [{
            "claim_id": "C001",
            "statement": "该渠道减少了 200 单",
            "level": "L1",
            "evidence_ids": ["E001"],
            "limitations": ["单日观测"],
        }],
        signed_evidence,
    )
    check("漏洞6 绝对量方向匹配",
          "untraceable_number" not in codes_of(absolute), f"codes={sorted(codes_of(absolute))}")

    ambiguous = run("订单量先上升后下降，净变化 20.45%")
    check("漏洞6 上下行同时出现时不误报",
          "untraceable_number" not in codes_of(ambiguous), f"codes={sorted(codes_of(ambiguous))}")


def test_identification_strategy_required() -> None:
    """0.6.0 的条件写成 `if identification and ...`，漏填时整条检查被跳过。"""
    missing = run_verify(
        [{
            "claim_id": "C001",
            "statement": "推荐算法改版导致订单量下降",
            "level": "L2",
            "evidence_ids": ["E001", "E002"],
            "limitations": ["无对照"],
            "decomposition_closed": True,
        }],
        {"evidence": [
            {"id": "E001", "kind": "computation", "value": 900, "verified": True},
            {"id": "E002", "kind": "computation", "value": 800, "verified": True},
        ]},
    )
    check("漏洞7 漏填 identification_strategy 被拦截",
          "causal_language_without_identification" in codes_of(missing) and missing["status"] == "fail",
          f"status={missing['status']}")


def test_label_numbers_not_required() -> None:
    """「分组 3」这类序号不是数据，不应该逼模型改写措辞来绕开溯源。"""
    report = run_verify(
        [{
            "claim_id": "C001",
            "statement": "分组 3 的转化率为 0.5",
            "level": "L1",
            "evidence_ids": ["E001"],
            "limitations": ["单组观测"],
        }],
        {"evidence": [{"id": "E001", "kind": "computation", "rate": 0.5, "verified": True}]},
    )
    check("序号数字不参与溯源",
          "untraceable_number" not in codes_of(report), f"codes={sorted(codes_of(report))}")


def test_reconciliation_integration() -> None:
    """对账联动：引用表内已被证伪的数字必须被拦下。"""
    import tempfile

    reconciliation = {
        "op": "reconcile",
        "reconciliations": [
            {
                "id": "R003", "kind": "reconciliation", "scope": "全表明细", "column": "金额",
                "stated": 99000, "computed": 7000, "diff": -92000, "status": "inconsistent", "verified": False,
            },
            {
                "id": "R001", "kind": "reconciliation", "scope": "地区==华东", "column": "金额",
                "stated": 3000, "computed": 3000, "status": "consistent", "verified": True,
            },
        ],
        "master_check": {"status": "fail", "checked": 2, "failed": 1, "failed_ids": ["R003"]},
    }
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "reconcile.json"
        path.write_text(json.dumps(reconciliation, ensure_ascii=False), encoding="utf-8")

        bad = run_verify(
            [{
                "claim_id": "C001",
                "statement": "全表金额合计为 99,000",
                "level": "L1",
                "evidence_ids": ["R003"],
                "limitations": ["含小计行"],
            }],
            extra=["--reconciliation", str(path)],
        )
        check("对账 引用表内被证伪的数字被拦下",
              "reconciliation_mismatch" in codes_of(bad) and bad["status"] == "fail",
              f"status={bad['status']}")

        good = run_verify(
            [{
                "claim_id": "C001",
                "statement": "华东金额小计为 3,000",
                "level": "L1",
                "evidence_ids": ["R001"],
                "limitations": ["含小计行"],
            }],
            extra=["--reconciliation", str(path)],
        )
        check("对账 引用通过对账的条目可通过",
              "reconciliation_mismatch" not in codes_of(good) and good["status"] == "pass",
              f"status={good['status']}")

        disclosed = run_verify(
            [{
                "claim_id": "C001",
                "statement": "全表金额合计写 99,000，但按明细重算只有 7,000，差额 92,000",
                "level": "L1",
                "evidence_ids": ["R003"],
                "limitations": ["含小计行"],
            }],
            extra=["--reconciliation", str(path)],
        )
        check("对账 同时披露差额的结论不算掩盖",
              "reconciliation_mismatch" not in codes_of(disclosed)
              and "untraceable_number" not in codes_of(disclosed),
              f"codes={sorted(codes_of(disclosed))}")

        unbound = run_verify(
            [{
                "claim_id": "C001",
                "statement": "全表金额合计为 99,000",
                "level": "L1",
                "evidence_ids": ["R001"],
                "limitations": ["含小计行"],
            }],
            extra=["--reconciliation", str(path)],
        )
        check("对账 未绑定却引用被证伪数字给出警告",
              "reconciliation_conflict_unbound" in codes_of(unbound), f"codes={sorted(codes_of(unbound))}")


def test_lenient_numbers_switch() -> None:
    fabricated = [{
        "claim_id": "C001",
        "statement": "支付成功率为 95.0%",
        "level": "L0",
        "evidence_ids": ["E001"],
        "limitations": ["单日观测"],
    }]
    evidence = {"evidence": [{"id": "E001", "kind": "computation", "value": 0.826, "verified": True}]}
    default = run_verify(fabricated, evidence)
    lenient = run_verify(fabricated, evidence, extra=["--lenient-numbers"])
    check("编造数字默认直接 fail", default["status"] == "fail", f"status={default['status']}")
    check("--lenient-numbers 退回警告", lenient["status"] == "warn", f"status={lenient['status']}")


def test_calendar_labels_not_required() -> None:
    """日历写法（2011-11、11 月、2011 年 11 月 14 日）不是结论数字。

    回归目标：DATE_PATTERN 只认 YYYY-MM-DD，导致「2011-11」「11 月」里的
    2011 / 11 被当成待溯源数字，逼模型把「11 月」改写成完整日期才能过闸。
    """
    evidence = {"evidence": [{"id": "E001", "kind": "metric", "value": 1426587.54, "verified": True}]}
    for statement in (
        "2011-11 净收入 1,426,587.54",
        "11 月净收入 1,426,587.54",
        "2011 年 11 月净收入 1,426,587.54",
    ):
        report = run_verify(
            [{"claim_id": "C001", "statement": statement, "level": "L0",
              "evidence_ids": ["E001"], "limitations": []}],
            evidence,
        )
        check(f"日历写法不参与溯源：{statement}",
              "untraceable_number" not in codes_of(report), f"codes={sorted(codes_of(report))}")


def test_agent_manifest_requires_agents_dir() -> None:
    """--require-agent-manifest 不带 --agents-dir 时必须硬失败，不能静默通过。"""
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        claims_path = base / "claims.json"
        claims_path.write_text(json.dumps({"claims": []}, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, str(VERIFY), "--claims", str(claims_path), "--require-agent-manifest"]
        completed = subprocess.run(command, capture_output=True, text=True)
        check("缺 --agents-dir 时退出码为 2", completed.returncode == 2, f"rc={completed.returncode}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {}
        check("缺 --agents-dir 时给出结构化错误",
              payload.get("status") == "fail" and "agents-dir" in str(payload.get("error", "")),
              str(payload)[:120])


def main() -> int:
    for suite in (
        test_evidence_required,
        test_unit_confusion,
        test_causal_identification,
        test_p_hacking,
        test_existing_gates_intact,
        test_scoped_evidence_binding,
        test_direction_and_sign,
        test_identification_strategy_required,
        test_label_numbers_not_required,
        test_reconciliation_integration,
        test_calendar_labels_not_required,
        test_agent_manifest_requires_agents_dir,
        test_lenient_numbers_switch,
    ):
        before = len(RESULTS)
        try:
            suite()
        except AssertionError:
            if len(RESULTS) == before:
                RESULTS.append((f"{suite.__name__} 断言失败", False, "未记录的 AssertionError"))
        except Exception as error:  # noqa: BLE001
            RESULTS.append((f"{suite.__name__} 执行异常", False, f"{type(error).__name__}: {error}"))

    failed = [item for item in RESULTS if not item[1]]
    for name, ok, detail in RESULTS:
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}" + (f" — {detail}" if detail else ""))
    print(f"\n共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
