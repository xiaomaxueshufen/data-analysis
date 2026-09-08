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

DATE_PATTERN = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\b\d{1,2}[-/]\d{1,2}\b")
NUMBER_PATTERN = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%?)(?![\w.])")
DEFAULT_NUMERIC_TOLERANCE = 0.051


def read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def collect_numbers(node: Any, sink: list[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        value = float(node)
        if math.isfinite(value):
            sink.append(value)
    elif isinstance(node, dict):
        for item in node.values():
            collect_numbers(item, sink)
    elif isinstance(node, list):
        for item in node:
            collect_numbers(item, sink)


def extract_statement_numbers(statement: str) -> list[tuple[float, bool]]:
    without_dates = DATE_PATTERN.sub(" ", statement)
    result: list[tuple[float, bool]] = []
    for match in NUMBER_PATTERN.finditer(without_dates):
        value = float(match.group(1))
        is_percent = match.group(2) == "%"
        result.append((value, is_percent))
    return result


def number_matches(value: float, evidence_values: list[float], tolerance: float) -> bool:
    for evidence_value in evidence_values:
        candidates = [evidence_value]
        if evidence_value != 0:
            candidates.append(evidence_value * 100.0)
            candidates.append(evidence_value / 100.0)
        for candidate in candidates:
            if math.isclose(value, candidate, rel_tol=1e-6, abs_tol=tolerance):
                return True
    return False


def check_claim(claim: dict, evidence_values: list[float], strict: bool, numeric_tolerance: float) -> dict:
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

    if statement and any(marker in statement for marker in CAUSAL_MARKERS):
        if level not in {"L2", "L3", "L4"}:
            issues.append({
                "severity": "fail",
                "code": "causal_language_below_l2",
                "message": f"statement 使用因果/证明措辞，但 level 为 {level}；未达 L2 时应改为“同步出现/高置信候选/待验证假设”。",
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

    if statement and evidence_values:
        for value, _is_percent in extract_statement_numbers(statement):
            if not number_matches(value, evidence_values, numeric_tolerance):
                issues.append({
                    "severity": "fail" if strict else "warn",
                    "code": "untraceable_number",
                    "message": f"statement 中的数字 {value} 未能在 evidence 中找到相近值。",
                })

    severities = {issue["severity"] for issue in issues}
    status = "fail" if "fail" in severities else ("warn" if "warn" in severities else "pass")
    return {"claim_id": claim_id, "status": status, "issues": issues}


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
    parser.add_argument("--evidence", help="证据 JSON（任意结构，会递归提取数字）")
    parser.add_argument("--agents-dir", dest="agents_dir", help="独立角色工件目录（含 locator/mechanism/falsifier/reviewer .json）")
    parser.add_argument("--require-agent-manifest", action="store_true", help="强制检查 agents/execution.json 的执行模式与 agent id 留痕")
    parser.add_argument("--strict", action="store_true", help="把数字溯源警告升级为失败")
    parser.add_argument("--numeric-tolerance", type=float, default=DEFAULT_NUMERIC_TOLERANCE, help="数字溯源的绝对容差；另保留百万分之一相对容差")
    args = parser.parse_args()
    if args.numeric_tolerance < 0:
        parser.error("--numeric-tolerance 不能为负数")

    try:
        claims_payload = read_json(args.claims)
        evidence_values: list[float] = []
        if args.evidence:
            collect_numbers(read_json(args.evidence), evidence_values)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1

    claims = claims_payload.get("claims") if isinstance(claims_payload, dict) else claims_payload
    if not isinstance(claims, list):
        print(json.dumps({"status": "fail", "error": "claims 必须是列表或 {\"claims\": [...]}"}, ensure_ascii=False))
        return 1

    results = [
        check_claim(claim, evidence_values, args.strict, args.numeric_tolerance)
        for claim in claims
        if isinstance(claim, dict)
    ]
    agent_issues: list[dict] = []
    if args.agents_dir:
        agent_issues = check_agents_dir(args.agents_dir, args.require_agent_manifest)["issues"]
    overall = "fail" if any(item["status"] == "fail" for item in results) else (
        "warn" if any(item["status"] == "warn" for item in results) else "pass"
    )
    if any(issue["severity"] == "fail" for issue in agent_issues):
        overall = "fail"
    elif agent_issues and overall == "pass":
        overall = "warn"
    print(json.dumps({
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "passed": sum(1 for item in results if item["status"] == "pass"),
        "warned": sum(1 for item in results if item["status"] == "warn"),
        "failed": sum(1 for item in results if item["status"] == "fail"),
        "agent_issues": agent_issues,
        "claims": results,
    }, ensure_ascii=False, indent=2))
    return 0 if overall != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
