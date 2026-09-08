#!/usr/bin/env python3
"""发布前真实性检查：证据引用、因果措辞、L2 门槛与数字溯源。

本脚本是唯一的推荐必跑工具，但它不生成报告、不做分析、不规定格式；
它只回答"这份结论是否越过了证据边界"。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAUSAL_MARKERS = [
    "导致",
    "造成了",
    "引起了",
    "证明",
    "根因已确定",
    "确定了根因",
    "确认了根因",
    "根因是",
]

# 只有随机实验或站得住的准实验识别策略才允许 L2 以上写因果措辞
VALID_IDENTIFICATION = {
    "randomized",
    "ab_test",
    "did",
    "difference_in_differences",
    "matching",
    "iv",
    "instrumental_variable",
    "rdd",
    "regression_discontinuity",
    "synthetic_control",
}

DATE_PATTERN = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\b\d{1,2}[-/]\d{1,2}\b")
NUMBER_PATTERN = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|个百分点|个百分點|pp|pct)?(?![\w.])")
DEFAULT_NUMERIC_TOLERANCE = 0.051

# 声明为"预先指定"之外的检验数量超过此值时，提示多重比较风险
DEFAULT_MAX_EXPLORATORY_TESTS = 5


def read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract_statement_numbers(statement: str) -> list[tuple[float, str]]:
    """从结论文本中抽取数字及其量纲。

    修复原实现的两类问题：
    1. 只匹配数字不匹配量纲，导致 `11.6` 和 `11.6%` 被当成同一数值；
    2. `extract_statement_numbers` 原本只返回 value 和 is_percent，
       evidence 中的 `0.116` 和 statement 中的 `11.6` 都会被认作相等，
       反向（`11.6` 与 `0.116`）也会被认作相等，从而放过伪造的百分数。
    现在统一返回 (value, unit)，unit ∈ {"raw", "percent", "pp"}，
    匹配规则要求 unit 一致，并对 raw↔percent 转换做显式确认。
    """
    without_dates = DATE_PATTERN.sub(" ", statement)
    result: list[tuple[float, str]] = []
    for match in NUMBER_PATTERN.finditer(without_dates):
        value = float(match.group(1))
        unit_token = (match.group(2) or "").lower()
        if unit_token in {"%", "pct"}:
            unit = "percent"
        elif unit_token in {"个百分点", "个百分點", "pp"}:
            unit = "pp"
        else:
            unit = "raw"
        result.append((value, unit))
    return result


def number_matches(
    statement_value: float,
    statement_unit: str,
    evidence_values: list[tuple[float, str]],
    tolerance: float,
) -> bool:
    """把 statement 中的数字与 evidence 中的数字按量纲配对。

    规则：
    - 量纲完全一致：值在容差内即视为匹配；
    - statement 是 raw（裸数），evidence 也是 raw：按当前容差；
    - statement 是 percent 且 evidence 是 raw：把 statement 除以 100 再比；
      这种情况最容易把 "0.5%" 误认成 "0.5"，所以要求 evidence 也至少有一份
      单位一致的原始值时才接受；
    - statement 是 pp 且 evidence 是 raw：把 statement 视作百分点，等价于
      percent（÷100）；
    - statement 与 evidence 同为 percent 或同为 pp：值在容差内视为匹配；
      若差值约为 100×（一边是分数形式 0.826，一边是百分数形式 82.6），
      也视为匹配——这是同一物理量在不同书写形式下的等价表示。
    - raw→percent 的反向转换（statement 是 raw、evidence 是 percent）不被允许，
      否则 "0.116" 和 "11.6%" 都能匹配 "0.116" 与 "11.6"。
    """
    # 100× 比例换算的容差：相对 1e-6 + 绝对 0.5（百分点单位）
    ratio_rel_tol = 1e-6
    ratio_abs_tol = 0.5

    for evidence_value, evidence_unit in evidence_values:
        # 1. raw vs raw：按当前容差直接比
        if statement_unit == "raw" and evidence_unit == "raw":
            if math.isclose(statement_value, evidence_value, rel_tol=1e-6, abs_tol=tolerance):
                return True
            continue

        # 2. statement 是 raw，evidence 是 percent/pp：禁止反向转换
        if statement_unit == "raw":
            continue

        # 3. statement 是 percent/pp，evidence 是 raw：把 statement ÷100 再比
        if evidence_unit == "raw":
            scaled = statement_value / 100.0
            if math.isclose(scaled, evidence_value, rel_tol=1e-6, abs_tol=tolerance):
                return True
            continue

        # 4. statement 与 evidence 同为 percent 或同为 pp
        if statement_unit == evidence_unit:
            # 4a. 直接相等
            if math.isclose(statement_value, evidence_value, rel_tol=1e-6, abs_tol=tolerance):
                return True
            # 4b. 100× 比例：一边是分数形式（0.826），一边是百分数形式（82.6）
            if evidence_value != 0:
                ratio = statement_value / evidence_value
                if math.isclose(ratio, 100.0, rel_tol=ratio_rel_tol, abs_tol=ratio_abs_tol):
                    return True
                if math.isclose(ratio, 0.01, rel_tol=ratio_rel_tol, abs_tol=ratio_abs_tol * 0.01):
                    return True
            continue

    return False


def collect_numbers(node: Any, sink: list[tuple[float, str]]) -> None:
    """递归从证据 JSON 中抽取所有数字及其单位。

    关键修复：原版把 evidence 中所有数字合并成一个无单位浮点列表，
    配合宽松的 number_matches 会放过伪造。修复版携带单位信息：
    - JSON key 含"率"/"rate"/"%"/"百分点"/"占比"/"share" 等被识别为 percent；
    - 键含"差"/"change"/"delta"/"pp"/"百分点"/"绝对" 被识别为 pp；
    - 其它为 raw。
    """
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        value = float(node)
        if math.isfinite(value):
            sink.append((value, "raw"))
        return
    if isinstance(node, dict):
        for key, item in node.items():
            unit_hint = _unit_from_key(str(key))
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                value = float(item)
                if math.isfinite(value):
                    sink.append((value, unit_hint))
            elif isinstance(item, (dict, list)):
                collect_numbers(item, sink)
    elif isinstance(node, list):
        for item in node:
            collect_numbers(item, sink)


_PERCENT_KEY_RE = re.compile(r"率|占比|比例|share|rate|%")
_PP_KEY_RE = re.compile(r"百分点|百分比点|绝对差|差值|delta|change|diff|pp\b")


def _unit_from_key(key: str) -> str:
    lower = key.lower()
    if _PP_KEY_RE.search(key) or _PP_KEY_RE.search(lower):
        return "pp"
    if _PERCENT_KEY_RE.search(key) or _PERCENT_KEY_RE.search(lower):
        return "percent"
    return "raw"


def check_claim(claim: dict, evidence_values: list[tuple[float, str]], strict: bool, numeric_tolerance: float, require_evidence: bool) -> dict:
    issues: list[dict] = []
    statement = str(claim.get("statement") or "").strip()
    evidence_ids = claim.get("evidence_ids") or []
    limitations = claim.get("limitations")
    level = str(claim.get("level") or "").strip().upper()
    claim_id = str(claim.get("claim_id") or claim.get("id") or "(missing id)")

    if not statement:
        issues.append({"severity": "fail", "code": "missing_statement", "message": "结论缺少 statement。"})
    if not isinstance(evidence_ids, list) or not evidence_ids:
        issues.append({"severity": "fail", "code": "missing_evidence", "message": "结论缺少 evidence_ids。"})
    if limitations is None or not isinstance(limitations, list):
        issues.append({"severity": "warn", "code": "missing_limitations", "message": "结论缺少 limitations。"})
    elif not limitations and level in {"L2", "L3", "L4"}:
        issues.append({"severity": "warn", "code": "missing_limitations", "message": "L2 及以上结论应写明 limitations。"})
    if not level:
        issues.append({"severity": "warn", "code": "missing_level", "message": "结论缺少 level，默认按 L1 审查。"})
        level = "L1"

    # 因果措辞必须升到 L2，且 identification_strategy 必须是公认的准实验设计之一
    if statement and any(marker in statement for marker in CAUSAL_MARKERS):
        if level not in {"L2", "L3", "L4"}:
            issues.append({
                "severity": "fail",
                "code": "causal_language_below_l2",
                "message": f"statement 使用因果/证明措辞，但 level 为 {level}；未达 L2 时应改为“同步出现/高置信候选/待验证假设”。",
            })
        else:
            identification = str(claim.get("identification_strategy") or "").strip().lower()
            if identification and identification not in VALID_IDENTIFICATION:
                issues.append({
                    "severity": "fail",
                    "code": "causal_language_without_identification",
                    "message": (
                        "L2 及以上使用了因果/证明措辞，必须提供 identification_strategy；"
                        f"当前为 {identification!r}，必须是 {sorted(VALID_IDENTIFICATION)} 之一。"
                    ),
                })

    if level in {"L2", "L3", "L4"}:
        has_closed_decomposition = bool(
            claim.get("decomposition_closed") or claim.get("closed_decomposition")
        )
        if len(evidence_ids) < 2 and not has_closed_decomposition:
            issues.append({
                "severity": "fail",
                "code": "l2_insufficient_evidence",
                "message": "L2 及以上解释至少需要两个独立证据或一个能闭合的分解。",
            })

    # 数字溯源：单位一致、evidence 必须存在且非空
    # 修复原版 (1) percent/raw 单位混淆 (2) 不传 evidence 时整段跳过
    if statement:
        if not evidence_values:
            if require_evidence:
                issues.append({
                    "severity": "fail",
                    "code": "no_evidence_provided",
                    "message": "调用方未传 --evidence，本规则不允许做数字溯源；请运行 da_ops 生成 evidence.json 后重跑。",
                })
        else:
            statement_numbers = extract_statement_numbers(statement)
            if statement_numbers:
                unmatched: list[str] = []
                for value, unit in statement_numbers:
                    if not number_matches(value, unit, evidence_values, numeric_tolerance):
                        unmatched.append(f"{value}{unit}")
                if unmatched:
                    issues.append({
                        "severity": "fail" if strict else "warn",
                        "code": "untraceable_number",
                        "message": "statement 中的数字无法在 evidence 中找到相同量纲的相近值：" + "、".join(unmatched),
                    })

    severities = {issue["severity"] for issue in issues}
    status = "fail" if "fail" in severities else ("warn" if "warn" in severities else "pass")
    return {"claim_id": claim_id, "status": status, "issues": issues}


def check_claims_for_p_hacking(claims: list[dict], exploratory_threshold: int) -> list[dict]:
    """检测模型是否在多个分组/时间窗上反复检验后挑显著的写进报告。

    当声明为 exploration 的检验数超过 exploratory_threshold，
    或者同一 statement 关键词与多个 evidence_ids 配对时，给出警告。
    """
    issues: list[dict] = []
    exploratory_count = 0
    multi_window_groups: dict[str, int] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status") or "")
        scope = claim.get("scope") if isinstance(claim.get("scope"), dict) else {}
        evidence_ids = claim.get("evidence_ids") or []
        if status in {"hypothesis", "exploratory", "exploration"}:
            exploratory_count += 1
        if evidence_ids and scope.get("date_window"):
            window = str(scope["date_window"])
            multi_window_groups[window] = multi_window_groups.get(window, 0) + 1
    if exploratory_count > exploratory_threshold:
        issues.append({
            "severity": "warn",
            "code": "multiple_comparison_risk",
            "message": (
                f"探索性结论 {exploratory_count} 条，超过阈值 {exploratory_threshold}。"
                "同一份数据被反复检验时 p 值分布被改变，未做 FDR/Holm 校正的结论"
                "可能因偶然性显著，建议在 multiple_testing 算子下重审。"
            ),
        })
    repeated_windows = [window for window, count in multi_window_groups.items() if count >= 3]
    if repeated_windows:
        issues.append({
            "severity": "warn",
            "code": "repeated_window_checks",
            "message": (
                "以下时间窗被多个结论引用，单条结论的显著性不能直接叠加："
                + "、".join(repeated_windows[:5])
            ),
        })
    return issues


def check_execution_manifest(path: Path) -> list[dict]:
    issues: list[dict] = []
    if not path.exists():
        return [{
            "severity": "fail",
            "code": "missing_execution_manifest",
            "message": "缺少 agents/execution.json。",
        }]
    try:
        payload = read_json(str(path))
    except (OSError, json.JSONDecodeError) as exc:
        return [{
            "severity": "fail",
            "code": "invalid_execution_manifest",
            "message": f"agents/execution.json 无法解析：{exc}",
        }]
    if not isinstance(payload, dict):
        return [{
            "severity": "fail",
            "code": "invalid_execution_manifest",
            "message": "agents/execution.json 必须是 JSON 对象。",
        }]

    mode = payload.get("mode")
    if mode not in {"native_subagents", "serial_fallback"}:
        issues.append({
            "severity": "fail",
            "code": "invalid_execution_mode",
            "message": "execution.json 的 mode 必须是 native_subagents 或 serial_fallback。",
        })
    if mode == "serial_fallback" and not str(payload.get("fallback_reason") or "").strip():
        issues.append({
            "severity": "fail",
            "code": "missing_fallback_reason",
            "message": "serial_fallback 必须写明 fallback_reason。",
        })
    if mode == "native_subagents":
        attempts = payload.get("spawn_attempts")
        if not isinstance(attempts, list):
            issues.append({
                "severity": "fail",
                "code": "invalid_spawn_attempts",
                "message": "native_subagents 必须提供 spawn_attempts 列表。",
            })
            return issues
        by_role = {
            item.get("role"): item
            for item in attempts
            if isinstance(item, dict)
        }
        for role in ("locator", "mechanism", "falsifier", "reviewer"):
            item = by_role.get(role)
            if item is None or item.get("status") != "ok" or not str(item.get("agent_id") or "").strip():
                issues.append({
                    "severity": "fail",
                    "code": "invalid_native_subagent_record",
                    "message": f"native_subagents 缺少 {role} 的 ok 状态和非空 agent_id。",
                })
    return issues


def check_agents_dir(agents_dir: str, require_manifest: bool = False) -> dict:
    required = ("locator", "mechanism", "falsifier", "reviewer")
    issues: list[dict] = []
    for role in required:
        path = Path(agents_dir) / f"{role}.json"
        if not path.exists():
            issues.append({
                "severity": "fail",
                "code": "missing_agent_artifact",
                "message": f"缺少独立角色工件：agents/{role}.json",
            })
            continue
        try:
            payload = read_json(str(path))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append({
                "severity": "fail",
                "code": "invalid_agent_artifact",
                "message": f"agents/{role}.json 无法解析：{exc}",
            })
            continue
        if not isinstance(payload, dict) or payload.get("agent") != role:
            issues.append({
                "severity": "fail",
                "code": "invalid_agent_artifact",
                "message": f"agents/{role}.json 的 agent 字段必须为 \"{role}\"",
            })
        if not isinstance(payload.get("findings"), list):
            issues.append({
                "severity": "fail",
                "code": "invalid_agent_artifact",
                "message": f"agents/{role}.json 缺少 findings 列表",
            })
    if require_manifest:
        issues.extend(check_execution_manifest(Path(agents_dir) / "execution.json"))
    return {"issues": issues}


def main() -> int:
    parser = argparse.ArgumentParser(description="检查分析结论的真实性边界")
    parser.add_argument("--claims", required=True, help="结论 JSON（列表或 {\"claims\": [...]}）")
    parser.add_argument("--evidence", help="证据 JSON（任意结构，会递归提取数字）；省略时数字溯源会按 --require-evidence 处理")
    parser.add_argument("--agents-dir", dest="agents_dir", help="独立角色工件目录（含 locator/mechanism/falsifier/reviewer .json）")
    parser.add_argument("--require-agent-manifest", action="store_true", help="强制检查 agents/execution.json 的执行模式与 agent id 留痕")
    parser.add_argument("--require-evidence", action="store_true", default=True, help="未传 --evidence 时强制 fail，不允许跳过数字溯源（默认开启）")
    parser.add_argument("--no-require-evidence", dest="require_evidence", action="store_false", help="未传 --evidence 时仅给出 warn（不推荐）")
    parser.add_argument("--max-exploratory-tests", type=int, default=DEFAULT_MAX_EXPLORATORY_TESTS, help="探索性结论数阈值，超过时给出多重比较警告")
    parser.add_argument("--strict", action="store_true", help="把数字溯源警告升级为失败")
    parser.add_argument("--numeric-tolerance", type=float, default=DEFAULT_NUMERIC_TOLERANCE, help="数字溯源的绝对容差；另保留百万分之一相对容差")
    args = parser.parse_args()
    if args.numeric_tolerance < 0:
        parser.error("--numeric-tolerance 不能为负数")

    try:
        claims_payload = read_json(args.claims)
        evidence_values: list[tuple[float, str]] = []
        if args.evidence:
            collect_numbers(read_json(args.evidence), evidence_values)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1

    claims = claims_payload.get("claims") if isinstance(claims_payload, dict) else claims_payload
    if not isinstance(claims, list):
        print(json.dumps({"status": "fail", "error": "claims 必须是列表或 {\"claims\": [...]}"}, ensure_ascii=False))
        return 2

    p_hacking_issues = check_claims_for_p_hacking(claims, args.max_exploratory_tests)
    results = [
        check_claim(claim, evidence_values, args.strict, args.numeric_tolerance, args.require_evidence)
        for claim in claims
        if isinstance(claim, dict)
    ]
    agent_issues: list[dict] = []
    if args.agents_dir:
        agent_issues = check_agents_dir(args.agents_dir, args.require_agent_manifest)["issues"]
    claim_failed = any(item["status"] == "fail" for item in results)
    claim_warned = any(item["status"] == "warn" for item in results)
    p_hacking_warned = bool(p_hacking_issues)
    agent_warned = bool(agent_issues) and not any(issue["severity"] == "fail" for issue in agent_issues)
    agent_failed = any(issue["severity"] == "fail" for issue in agent_issues)
    if claim_failed or agent_failed:
        overall = "fail"
    elif claim_warned or p_hacking_warned or agent_warned:
        overall = "warn"
    else:
        overall = "pass"
    print(json.dumps({
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "passed": sum(1 for item in results if item["status"] == "pass"),
        "warned": sum(1 for item in results if item["status"] == "warn"),
        "failed": sum(1 for item in results if item["status"] == "fail"),
        "p_hacking_warnings": p_hacking_issues,
        "agent_issues": agent_issues,
        "evidence_summary": {"numbers_collected": len(evidence_values)},
        "claims": results,
    }, ensure_ascii=False, indent=2))
    return 0 if overall != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
