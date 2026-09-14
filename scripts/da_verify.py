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

# 方向词用于把「下降了 20.45%」与「上升了 20.45%」区分开。
# 注意先判下行：「负增长」同时命中「增长」，下行优先才能正确归类。
DIRECTION_DOWN = ("下降", "下滑", "下跌", "减少", "降低", "回落", "走低", "负增长", "缩小", "下调", "损失")
DIRECTION_UP = ("上升", "上涨", "增长", "提升", "增加", "走高", "提高", "扩大", "上调", "正增长", "新增")

# 结构化证据条目里这些字段是溯源信息（行号、条目 id、范围描述），
# 不是结论引用的数字；把它们并入数字池会让「第 5 行」匹配上结论里的 5。
PROVENANCE_KEYS = {
    "id", "kind", "scope", "scope_type", "column", "sheet", "file", "path", "name", "sha256",
    "row", "rows", "row_number", "detail_rows", "detail_row_numbers", "header_row", "index",
    "label", "op", "status", "verified", "severity", "code", "message", "limitations", "tried",
    "unit", "schema_version", "reason", "detail", "source", "binding",
}

# 序号/标签语境里的数字（分组 0、第 1 章、阶段 2）是被引用的对象名，
# 不是数据结论。不排除它们会逼模型为了过闸改写措辞，反而降低可读性。
LABEL_CONTEXT_PATTERN = re.compile(
    r"(?:第|分组|组|阶段|步骤|序号|章节?|表|图|方案|选项)\s*(\d+(?:\.\d+)?)"
)

# 时间口语必须整体排除，否则「2011-11」「11 月」「2011 年」里的 2011 / 11
# 会被当成结论数字，逼模型把「11 月」改写成「2011-11-01 至 2011-11-30」才能过闸。
DATE_PATTERN = re.compile(
    r"\d{4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
    r"|\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?"
    r"|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"
    r"|\d{1,2}\s*季度"
    r"|\b\d{1,2}[-/]\d{1,2}\b"
)
# 捕获符号与千分位：-20.45% / −3.2 / 1,234.56 都要能读出来。
NUMBER_PATTERN = re.compile(
    r"(?<![\w.])"
    r"(?P<sign>[+\-\u2212])?\s*"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>%|个百分点|个百分點|pp|pct)?"
    r"(?![\w.])"
)
DEFAULT_NUMERIC_TOLERANCE = 0.051

# 声明为"预先指定"之外的检验数量超过此值时，提示多重比较风险
DEFAULT_MAX_EXPLORATORY_TESTS = 5


def read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract_statement_numbers(statement: str) -> list[dict]:
    """从结论文本中抽取数字、量纲与显式符号。

    返回 [{"value", "unit", "explicit_sign", "raw"}]：
    - unit ∈ {"raw", "percent", "pp"}，量纲独立匹配，raw↔percent 反向转换不允许；
    - explicit_sign 为 -1 / 1 / None。原实现丢掉了负号，导致「下降了 20.45%」
      （证据 relative_shift = -0.2045）永远无法溯源，模型只能靠改写措辞去过闸；
    - 千分位（1,234.56）解析为单个数字，不再被拆成 1 / 234 / 56。
    """
    without_dates = DATE_PATTERN.sub(" ", statement)
    result: list[dict] = []
    for match in NUMBER_PATTERN.finditer(without_dates):
        text = match.group("number").replace(",", "")
        value = float(text)
        sign_token = match.group("sign")
        explicit_sign = None
        if sign_token in {"-", "\u2212"}:
            explicit_sign = -1
            value = -value
        elif sign_token == "+":
            explicit_sign = 1
        unit_token = (match.group("unit") or "").lower()
        if unit_token in {"%", "pct"}:
            unit = "percent"
        elif unit_token in {"个百分点", "个百分點", "pp"}:
            unit = "pp"
        else:
            unit = "raw"
        result.append({
            "value": value,
            "unit": unit,
            "explicit_sign": explicit_sign,
            "raw": match.group(0).strip(),
        })
    return result


def extract_label_numbers(statement: str) -> set[float]:
    """抽取序号语境里的数字（分组 0、第 1 章、阶段 2），这些不参与溯源。"""
    return {float(match.group(1)) for match in LABEL_CONTEXT_PATTERN.finditer(statement)}


def statement_direction(statement: str) -> str | None:
    """判断结论的整体变化方向；上下行同时出现时视为方向不明，不做方向约束。"""
    has_down = any(marker in statement for marker in DIRECTION_DOWN)
    has_up = any(marker in statement for marker in DIRECTION_UP)
    if has_down == has_up:
        return None
    return "down" if has_down else "up"


def _scaled_pairs(
    value: float,
    unit: str,
    evidence_value: float,
    evidence_unit: str,
    evidence_hinted: bool = True,
) -> list[tuple[float, float]]:
    """把 statement 数值与 evidence 数值换算到同一量纲，返回可比对的候选对（按量级）。

    证据里的量纲来自**键名推断**（rate / 率 / delta / pp …），不是显式声明，
    所以这里的原则是：能自洽解释就接受，解释不通才判不可溯源。

    - statement 是 percent / pp：允许「百分数 ↔ 比率」两种书写（11.6% ↔ 0.116）；
      证据量纲未知时，÷100 与不换算两种解释都会试一次，
      否则 `{"delta": -0.2045}` 这种把比率写成小数的证据会被键名误会成百分点而误杀；
    - statement 是 raw：只在证据同为 raw（或量纲未知）时按数值比较；
      raw → percent 的反向转换仍然不允许，否则 `0.116` 能匹配 `11.6`。
    """
    a = abs(value)
    b = abs(evidence_value)
    pairs: list[tuple[float, float]] = []

    def add(left: float, right: float) -> None:
        for existing in pairs:
            if existing == (left, right):
                return
        pairs.append((left, right))

    if unit == "raw":
        if evidence_unit == "raw" or evidence_hinted:
            add(a, b)
        return pairs

    if evidence_unit == "raw":
        add(a / 100.0, b)
        return pairs

    if evidence_unit in {"percent", "pp"}:
        add(a, b)
        add(a / 100.0, b)
    return pairs


def number_matches(
    statement_value: float,
    statement_unit: str,
    evidence_values: list[tuple[float, str, bool]],
    tolerance: float,
    direction: str | None = None,
    explicit_sign: int | None = None,
) -> bool:
    """把 statement 数字与 evidence 数字按量纲 + 方向配对。

    与 0.6.0 的关键差别：匹配先按**量级**对齐，再用方向词或显式符号校验符号。
    原实现比较带符号的值，于是：
    - 「上升了 20.45%」和「下降了 20.45%」都能匹配 relative_shift = +0.2045，
      方向写反的结论照样放行；
    - 反过来，「下降了 20.45%」匹配 -0.2045 时因符号丢失而误报不可溯源。
    现在：显式符号必须与证据同号；未写符号但有方向词时，证据符号必须与方向一致。
    """
    for evidence_value, evidence_unit, evidence_hinted in evidence_values:
        pairs = _scaled_pairs(statement_value, statement_unit, evidence_value, evidence_unit, evidence_hinted)
        for left, right in pairs:
            if not math.isclose(left, right, rel_tol=1e-6, abs_tol=tolerance):
                continue
            evidence_sign = 0 if evidence_value == 0 else (1 if evidence_value > 0 else -1)
            if explicit_sign is not None:
                if evidence_sign == 0 or evidence_sign == explicit_sign:
                    return True
                continue
            if direction == "down" and evidence_sign < 0:
                return True
            if direction == "up" and evidence_sign > 0:
                return True
            if direction is None:
                return True
    return False


def number_present(statement: str, value: Any, tolerance: float) -> bool:
    """结论文本里是否出现了某个具体数值（按量级比较，容忍 100× 书写差异）。"""
    if value is None:
        return False
    target = abs(float(value))
    for item in extract_statement_numbers(statement):
        current = abs(item["value"])
        if math.isclose(current, target, rel_tol=1e-6, abs_tol=tolerance):
            return True
        if current != 0 and target != 0 and math.isclose(current / target, 100.0, rel_tol=1e-6, abs_tol=0.5):
            return True
    return False



def collect_numbers(node: Any, sink: list[tuple[float, str, bool]]) -> None:
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
            sink.append((value, "raw", True))
        return
    if isinstance(node, dict):
        for key, item in node.items():
            unit_hint = _unit_from_key(str(key))
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                value = float(item)
                if math.isfinite(value):
                    sink.append((value, unit_hint, True))
            elif isinstance(item, (dict, list)):
                collect_numbers(item, sink)
    elif isinstance(node, list):
        for item in node:
            collect_numbers(item, sink)


_PERCENT_KEY_RE = re.compile(r"率|占比|比例|share|rate|ratio|percent|%")
_PP_KEY_RE = re.compile(r"百分点|百分比点|绝对差|差值|delta|change|diff|pp\b")


def _unit_from_key(key: str) -> str:
    lower = key.lower()
    if _PP_KEY_RE.search(key) or _PP_KEY_RE.search(lower):
        return "pp"
    if _PERCENT_KEY_RE.search(key) or _PERCENT_KEY_RE.search(lower):
        return "percent"
    return "raw"


ENTRY_LIST_KEYS = ("evidence", "entries", "reconciliations", "items", "results")


def collect_numbers_excluding(node: Any, sink: list[tuple[float, str, bool]], skip: set[str]) -> None:
    """从结构化证据条目里抽取数字，跳过溯源字段（行号、id、范围描述等）。"""
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        value = float(node)
        if math.isfinite(value):
            sink.append((value, "raw", True))
        return
    if isinstance(node, dict):
        for key, item in node.items():
            if str(key) in skip or isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                value = float(item)
                if math.isfinite(value):
                    sink.append((value, _unit_from_key(str(key)), True))
            elif isinstance(item, (dict, list)):
                collect_numbers_excluding(item, sink, skip)
    elif isinstance(node, list):
        for item in node:
            collect_numbers_excluding(item, sink, skip)


def load_evidence(payload: Any) -> dict:
    """把证据文件解析成「条目」或「数字袋」。

    推荐结构（带 id 的条目列表，如 da_reconcile.py / da_ops 的输出）：
        {"evidence": [{"id": "R001", "value": 3000, "verified": true, ...}, ...]}
    此时数字按条目绑定：结论只能用它自己 evidence_ids 指向的条目里的数字，
    挂在别人头上的数字不再算「溯源成功」。

    自由结构（任意 JSON）仍可用，但会标注 unscoped_evidence：
    只能做全文件数字袋匹配，不提供语义绑定。
    """
    entries: dict[str, dict] = {}
    legacy: list[tuple[float, str, bool]] = []
    structured = False
    candidates: list = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ENTRY_LIST_KEYS:
            if isinstance(payload.get(key), list):
                candidates = payload[key]
                break
    for item in candidates:
        if isinstance(item, dict) and item.get("id"):
            structured = True
            numbers: list[tuple[float, str, bool]] = []
            collect_numbers_excluding(item, numbers, PROVENANCE_KEYS)
            entries[str(item["id"])] = {
                "id": str(item["id"]),
                "numbers": numbers,
                "verified": bool(item.get("verified", item.get("status") == "consistent")),
                "status": item.get("status"),
                "kind": item.get("kind"),
                "raw": item,
            }
    if not structured:
        collect_numbers(payload, legacy)
    return {"entries": entries, "legacy": legacy, "structured": structured, "poisoned": [], "reconciliation_present": False}


def merge_evidence(target: dict, incoming: dict, from_reconciliation: bool = False) -> None:
    target["entries"].update(incoming["entries"])
    target["legacy"].extend(incoming["legacy"])
    target["structured"] = bool(target["structured"] or incoming["structured"] or incoming["entries"])
    if from_reconciliation:
        target["reconciliation_present"] = True
        for entry in incoming["entries"].values():
            raw = entry.get("raw") or {}
            if raw.get("status") == "inconsistent":
                target["poisoned"].append((raw.get("stated"), raw.get("computed"), entry["id"]))


def check_claim(
    claim: dict,
    evidence: dict,
    strict: bool,
    numeric_tolerance: float,
    require_evidence: bool,
    lenient_numbers: bool = False,
    require_evidence_ids: bool = False,
) -> dict:
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

    # 因果措辞必须升到 L2，并且必须给出合法识别策略。
    # 0.6.0 的条件写成 `if identification and ...`，漏填 identification_strategy 时
    # 整条检查被跳过，只有填了非法值才 fail——与 evidence-contract.md 的约定相反。
    if statement and any(marker in statement for marker in CAUSAL_MARKERS):
        if level not in {"L2", "L3", "L4"}:
            issues.append({
                "severity": "fail",
                "code": "causal_language_below_l2",
                "message": f"statement 使用因果/证明措辞，但 level 为 {level}；未达 L2 时应改为“同步出现/高置信候选/待验证假设”。",
            })
        else:
            identification = str(claim.get("identification_strategy") or "").strip().lower()
            if not identification:
                issues.append({
                    "severity": "fail",
                    "code": "causal_language_without_identification",
                    "message": (
                        "L2 及以上使用了因果/证明措辞，必须提供 identification_strategy；"
                        f"当前未提供，必须是 {sorted(VALID_IDENTIFICATION)} 之一。"
                    ),
                })
            elif identification not in VALID_IDENTIFICATION:
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

    # ---------------- 数字溯源：按条目绑定 + 对账校验 ----------------
    binding = {"mode": "none", "bound_ids": []}
    if statement:
        entries = evidence.get("entries") or {}
        legacy = evidence.get("legacy") or []
        bound_ids = [str(item) for item in evidence_ids if str(item) in entries] if isinstance(evidence_ids, list) else []
        bound = [entries[item] for item in bound_ids]
        pool: list[tuple[float, str, bool]] = []
        for entry in bound:
            pool.extend(entry["numbers"])
        if bound_ids:
            binding = {"mode": "scoped", "bound_ids": bound_ids}
        elif evidence.get("structured"):
            binding = {"mode": "unresolved", "bound_ids": []}
        elif legacy:
            binding = {"mode": "legacy", "bound_ids": []}

        if not entries and not legacy:
            if require_evidence:
                issues.append({
                    "severity": "fail",
                    "code": "no_evidence_provided",
                    "message": "调用方未传 --evidence，本规则不允许做数字溯源；请运行 da_ops / da_reconcile 生成证据后重跑。",
                })
        elif binding["mode"] == "unresolved":
            issues.append({
                "severity": "fail" if (require_evidence_ids or strict) else "info",
                "code": "unresolved_evidence_ids",
                "message": (
                    "结论引用的 evidence_ids 在证据文件里找不到对应条目，无法按条目绑定："
                    + "、".join(str(item) for item in evidence_ids[:6])
                ),
            })
        elif binding["mode"] == "legacy":
            issues.append({
                "severity": "fail" if strict else "warn",
                "code": "unscoped_evidence",
                "message": (
                    "证据文件是自由结构（条目没有 id），只能做全文件数字袋匹配，"
                    "无法确认数字来自哪条结论；建议改用带 id 的结构化证据或 da_reconcile.py 的对账输出。"
                ),
            })

        if not pool and binding["mode"] in {"unresolved", "legacy"}:
            pool = legacy or [number for entry in entries.values() for number in entry["numbers"]]

        if pool:
            numbers = extract_statement_numbers(statement)
            direction = statement_direction(statement)
            label_numbers = extract_label_numbers(statement)
            unmatched: list[str] = []
            ignored: list[str] = []
            for item in numbers:
                if any(math.isclose(abs(item["value"]), value, rel_tol=1e-9, abs_tol=1e-9) for value in label_numbers):
                    ignored.append(item["raw"])
                    continue
                if not number_matches(
                    item["value"], item["unit"], pool, numeric_tolerance, direction, item["explicit_sign"]
                ):
                    unmatched.append(f"{item['raw']}({item['unit']})")
            if ignored:
                binding["ignored_label_numbers"] = ignored
            if unmatched:
                scope_text = "已绑定条目" if binding["mode"] == "scoped" else "证据文件"
                issues.append({
                    "severity": "warn" if lenient_numbers else "fail",
                    "code": "untraceable_number",
                    "message": f"以下数字未能在{scope_text}中按量纲与方向溯源：" + "、".join(unmatched),
                })

        # 引用了一条自己对不上的对账条目：不得引用表内已被证伪的数字
        for entry in bound:
            if entry.get("kind") == "reconciliation" and not entry.get("verified"):
                raw = entry.get("raw") or {}
                stated, computed = raw.get("stated"), raw.get("computed")
                if number_present(statement, stated, numeric_tolerance) and not number_present(statement, computed, numeric_tolerance):
                    issues.append({
                        "severity": "fail",
                        "code": "reconciliation_mismatch",
                        "message": (
                            f"结论引用了对账不通过的条目 {entry['id']}："
                            f"表内写 {stated}，按明细重算为 {computed}。"
                            "要么改口径、要么把差额写清楚，不能直接把表内那个数当结论。"
                        ),
                    })

        if evidence.get("reconciliation_present"):
            for stated, computed, entry_id in evidence.get("poisoned") or []:
                if not stated or entry_id in bound_ids:
                    continue
                if number_present(statement, stated, numeric_tolerance) and not number_present(statement, computed, numeric_tolerance):
                    issues.append({
                        "severity": "warn",
                        "code": "reconciliation_conflict_unbound",
                        "message": (
                            f"结论里的数字与对账条目 {entry_id} 的表内值一致，但该条目明细重算为 {computed}；"
                            "如果确实要引用这个数，请显式引用该条目并说明差异。"
                        ),
                    })

    severities = {issue["severity"] for issue in issues}
    status = "fail" if "fail" in severities else ("warn" if "warn" in severities else "pass")
    return {"claim_id": claim_id, "status": status, "issues": issues, "evidence_binding": binding}



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
    parser.add_argument("--evidence", help="证据 JSON；带 id 的条目列表按条目绑定数字，自由结构只能做数字袋匹配")
    parser.add_argument("--reconciliation", help="da_reconcile.py 的对账输出；引用 status=inconsistent 的条目会被拦下")
    parser.add_argument("--agents-dir", dest="agents_dir", help="独立角色工件目录（含 locator/mechanism/falsifier/reviewer .json）")
    parser.add_argument("--require-agent-manifest", action="store_true", help="强制检查 agents/execution.json 的执行模式与 agent id 留痕")
    parser.add_argument("--require-evidence", action="store_true", default=True, help="未传 --evidence 时强制 fail，不允许跳过数字溯源（默认开启）")
    parser.add_argument("--no-require-evidence", dest="require_evidence", action="store_false", help="未传 --evidence 时仅给出 warn（不推荐）")
    parser.add_argument("--max-exploratory-tests", type=int, default=DEFAULT_MAX_EXPLORATORY_TESTS, help="探索性结论数阈值，超过时给出多重比较警告")
    parser.add_argument("--strict", action="store_true", help="把弱模式证据与未解析 evidence_ids 升级为失败")
    parser.add_argument("--numeric-tolerance", type=float, default=DEFAULT_NUMERIC_TOLERANCE, help="数字溯源的绝对容差；另保留百万分之一相对容差")
    parser.add_argument("--lenient-numbers", action="store_true", help="把数字不可溯源降级为警告（默认直接 fail）")
    parser.add_argument("--require-evidence-ids", action="store_true", help="evidence_ids 解析不到条目时直接 fail")
    args = parser.parse_args()
    if args.numeric_tolerance < 0:
        parser.error("--numeric-tolerance 不能为负数")
    # --require-agent-manifest 单独使用时曾经是空操作（检查挂在 `if args.agents_dir`
    # 下面），等于给了「独立角色门禁已强制」的错觉。这里改成硬失败。
    if args.require_agent_manifest and not args.agents_dir:
        print(json.dumps({
            "status": "fail",
            "error": "--require-agent-manifest 必须同时提供 --agents-dir <运行目录>/agents；没有 --agents-dir 时无法检查四角色工件与 execution.json",
        }, ensure_ascii=False))
        return 2

    evidence: dict = {"entries": {}, "legacy": [], "structured": False, "poisoned": [], "reconciliation_present": False}
    try:
        claims_payload = read_json(args.claims)
        if args.evidence:
            merge_evidence(evidence, load_evidence(read_json(args.evidence)))
        if args.reconciliation:
            merge_evidence(evidence, load_evidence(read_json(args.reconciliation)), from_reconciliation=True)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1

    claims = claims_payload.get("claims") if isinstance(claims_payload, dict) else claims_payload
    if not isinstance(claims, list):
        print(json.dumps({"status": "fail", "error": "claims 必须是列表或 {\"claims\": [...]}"}, ensure_ascii=False))
        return 2

    p_hacking_issues = check_claims_for_p_hacking(claims, args.max_exploratory_tests)
    results = [
        check_claim(
            claim,
            evidence,
            args.strict,
            args.numeric_tolerance,
            args.require_evidence,
            args.lenient_numbers,
            args.require_evidence_ids,
        )
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
    reconciliation_entries = sum(1 for entry in evidence["entries"].values() if entry.get("kind") == "reconciliation")
    numbers_collected = len(evidence["legacy"]) or sum(len(entry["numbers"]) for entry in evidence["entries"].values())
    binding_modes: dict[str, int] = {}
    for item in results:
        mode = (item.get("evidence_binding") or {}).get("mode", "none")
        binding_modes[mode] = binding_modes.get(mode, 0) + 1
    print(json.dumps({
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "passed": sum(1 for item in results if item["status"] == "pass"),
        "warned": sum(1 for item in results if item["status"] == "warn"),
        "failed": sum(1 for item in results if item["status"] == "fail"),
        "noted": sum(1 for item in results if item["status"] == "pass" and any(i["severity"] == "info" for i in item["issues"])),
        "p_hacking_warnings": p_hacking_issues,
        "agent_issues": agent_issues,
        "evidence_summary": {
            "numbers_collected": numbers_collected,
            "structured_entries": len(evidence["entries"]),
            "reconciliation_entries": reconciliation_entries,
            "binding_modes": binding_modes,
            "reconciliation_supplied": bool(args.reconciliation),
        },
        "claims": results,
    }, ensure_ascii=False, indent=2))
    return 0 if overall != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
