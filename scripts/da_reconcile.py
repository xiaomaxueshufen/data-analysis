#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表内对账 —— 用表自己的「合计 / 小计」行证明数字没算错。

为什么需要它
------------
`da_verify.py` 只能回答「这个数字在证据文件里出现过」，回答不了
「这个数字对不对」。中文办公表格几乎都自带校验和：末尾的「合计」、
分组后的「小计」。把它们扔掉等于扔掉免费的交叉验证。

本脚本读**原始单元格**（openpyxl / csv，不经过 pandas 类型推断），
识别汇总行、推断每一行的管辖范围，再用明细行重算一遍去对账：

    「华东小计」→ 取「地区==华东」的 2 行明细 → 3,000.00  ✓ 一致
    「合计 99,000」 vs 全表明细 7,000            ✗ 差 -92,000（92.93%）

退出码：0 = 全部对上或无可对账项；1 = 有对不上的地方，可直接当流水线闸门。

用法
----
    python scripts/da_reconcile.py --data <文件> [--sheet 名称] --out <对账.json>
    python scripts/da_reconcile.py --data 表.xlsx --absolute-tolerance 0.5

输出可直接作为 `da_verify.py --reconciliation` 的输入：每条对账结果带
`id`、`status`、`verified`，结论只要引用 `verified: false` 的条目就会被拦下。

边界
----
- 只做加总类对账；比率行（占比 / 同比 / 率）不参与求和，标记为跳过；
- 不做跨表、跨 sheet 对账；
- 「1.2万」这类带中文数量级的单元格不解析，见 limitations。
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from da_envcheck import ensure_dependencies  # noqa: E402

ensure_dependencies()

from da_common import DataError, cli_guard, ensure_readable, file_sha256, write_json  # noqa: E402

# 汇总行关键字：分组层级在前，全表层级在后（判定时分组优先）
GROUP_WORDS = ("小计", "分组小计", "subtotal", "sub-total", "sub total")
TOTAL_WORDS = ("合计", "总计", "总和", "累计", "汇总", "共计", "总额", "总数", "grand total", "total", "sum")
# 比率行/列不参与加总对账：它们不满足「明细可加总」的前提
RATIO_WORDS = ("占比", "比例", "同比", "环比", "增长", "率", "percent", "rate", "%", "share")

DEFAULT_ABSOLUTE_TOLERANCE = 0.5
DEFAULT_RELATIVE_TOLERANCE = 0.005
BLANK_TOKENS = {"", "-", "--", "—", "－", "/", "n/a", "na", "null", "none", "无", "不适用"}

FULLWIDTH_MAP = {
    **{chr(0xFF10 + i): str(i) for i in range(10)},
    **{chr(0xFF0B + i): c for i, c in enumerate("+,-./")},
    "％": "%",
    "，": ",",
    "（": "(",
    "）": ")",
    "－": "-",
    "＋": "+",
    "．": ".",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text) if text else text
    text = text.translate(str.maketrans(FULLWIDTH_MAP)) if any(ch in text for ch in FULLWIDTH_MAP) else text
    return text.replace("\u3000", " ").strip()


def is_blank(value: Any) -> bool:
    return normalize_text(value).lower() in BLANK_TOKENS


def parse_value(value: Any) -> tuple[float | None, bool]:
    """把单元格解析成 (数值, 是否百分号)。

    处理千分位、会计式括号负数、货币符号、百分号、全角数字；
    解析不出来时返回 (None, False)——不猜、不把文本当 0。
    """
    text = normalize_text(value)
    if text.lower() in BLANK_TOKENS:
        return None, False
    negative = False
    if text.startswith("(") and text.endswith(")") and len(text) > 2:
        negative = True
        text = text[1:-1]
    percent = "%" in text
    cleaned = re.sub(r"[\s,￥$¥€£元人民币:]", "", text)
    match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)(?:%|个百分点|个百分點)?", cleaned)
    if not match:
        return None, False
    number = float(match.group(1))
    if negative:
        number = -abs(number)
    return number, percent


def parse_number(value: Any) -> float | None:
    return parse_value(value)[0]


def has_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def summary_level(label: str) -> str | None:
    if not label or has_any(label, RATIO_WORDS):
        return None
    if has_any(label, GROUP_WORDS):
        return "group"
    if has_any(label, TOTAL_WORDS):
        return "total"
    return None


def strip_summary_words(label: str) -> str:
    text = label
    for word in GROUP_WORDS + TOTAL_WORDS:
        text = re.sub(re.escape(word), "", text, flags=re.IGNORECASE)
    return normalize_text(text)


# ----------------------------------------------------------------- 读取原始网格


def read_xlsx_grid(path: Path, sheet: str | None) -> tuple[list[list[str]], str]:
    try:
        from openpyxl import load_workbook
    except ImportError as error:  # pragma: no cover - 依赖缺失时给可执行提示
        raise DataError("需要 openpyxl 读取 .xlsx：pip install -r requirements.txt") from error
    workbook = load_workbook(path, data_only=True, read_only=True)
    names = list(workbook.sheetnames)
    chosen = sheet if sheet in names else None
    if chosen is None:
        # 默认选非空行最多的 sheet，而不是第一个
        best: tuple[int, str] | None = None
        for name in names:
            rows = _sheet_rows(workbook[name])
            filled = sum(1 for row in rows if any(not is_blank(cell) for cell in row))
            if best is None or filled > best[0]:
                best = (filled, name)
        chosen = best[1] if best else (names[0] if names else "")
    if chosen is None:
        raise DataError(f"sheet 不存在：{sheet}；可用：{names}")
    rows = _sheet_rows(workbook[chosen])
    workbook.close()
    return rows, chosen


def _sheet_rows(worksheet: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in worksheet.iter_rows(values_only=True):
        rows.append(["" if cell is None else str(cell) for cell in row])
    return rows


def read_delimited_grid(path: Path) -> list[list[str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
            continue
        if path.suffix.lower() == ".tsv":
            delimiter = "\t"
        else:
            try:
                delimiter = csv.Sniffer().sniff(text[:10000], delimiters=",\t;|").delimiter
            except csv.Error:
                delimiter = ","
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    raise DataError(f"无法解码文件：{path}；最后错误：{type(last_error).__name__}: {last_error}")


def read_grid(path: Path, sheet: str | None) -> tuple[list[list[str]], str]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return read_xlsx_grid(path, sheet)
    if suffix in {".csv", ".tsv"}:
        return read_delimited_grid(path), path.stem
    if suffix == ".xls":
        raise DataError("暂不支持旧版 .xls：请另存为 .xlsx 或 .csv 后重试。")
    raise DataError(f"不支持的文件类型：{suffix or '（无扩展名）'}；只支持 .xlsx / .xlsm / .csv / .tsv")


# ----------------------------------------------------------------- 结构识别


def grid_width(rows: list[list[str]]) -> int:
    return max((len(row) for row in rows), default=0)


def padded(rows: list[list[str]]) -> list[list[str]]:
    width = grid_width(rows)
    return [row + [""] * (width - len(row)) for row in rows]


def detect_header_row(rows: list[list[str]]) -> int:
    """表头 = 前若干行里「非空文本多、且其下多为数值」的那一行。"""
    limit = min(15, len(rows))
    best_index, best_score = 0, float("-inf")
    for index in range(limit):
        row = rows[index]
        labels = [cell for cell in row if not is_blank(cell)]
        if not labels:
            continue
        text_like = sum(parse_number(cell) is None for cell in labels)
        below = rows[index + 1 : index + 21]
        numeric_below = 0
        for column in range(len(row)):
            if is_blank(row[column]):
                continue
            values = [parse_number(other[column]) for other in below if column < len(other)]
            filled = [value for value in values if value is not None]
            if filled:
                numeric_below += 1
        score = len(labels) * 2 + text_like + numeric_below * 1.5 - index * 0.5
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def build_columns(header: list[str], width: int) -> list[str]:
    names: list[str] = []
    seen: dict[str, int] = {}
    for index in range(width):
        raw = normalize_text(header[index]) if index < len(header) else ""
        name = raw or f"__col_{index + 1}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        names.append(name if count == 1 else f"{name}__{count}")
    return names


def label_column_index(rows: list[list[str]], header_row: int) -> int:
    """标签列 = 正文里「非空且解析不成数字」的取值最多的那一列。"""
    body = rows[header_row + 1 :]
    width = grid_width(rows)
    best_index, best_score = 0, -1
    for column in range(width):
        texts = [normalize_text(row[column]) for row in body if column < len(row)]
        text_like = sum(1 for text in texts if text and parse_number(text) is None)
        if text_like > best_score:
            best_index, best_score = column, text_like
    return best_index


def numeric_columns(rows: list[list[str]], header_row: int, columns: list[str], summary_row_indexes: set[int]) -> list[int]:
    body = [(index, row) for index, row in enumerate(rows) if index > header_row and index not in summary_row_indexes]
    result: list[int] = []
    for column in range(len(columns)):
        if has_any(columns[column], RATIO_WORDS):
            continue
        values = [parse_number(row[column]) for _, row in body if column < len(row)]
        filled = [value for value in values if value is not None]
        if len(filled) >= 1 and len(filled) >= 0.5 * max(len(values), 1):
            result.append(column)
    return result


def classify_rows(rows: list[list[str]], header_row: int, label_index: int, columns: list[str]) -> list[dict[str, Any]]:
    """给每个正文行打标签：detail / group / total / blank。"""
    classified: list[dict[str, Any]] = []
    for index in range(header_row + 1, len(rows)):
        row = rows[index]
        filled = [normalize_text(cell) for cell in row if not is_blank(cell)]
        if not filled:
            classified.append({"index": index, "kind": "blank", "label": "", "label_column": label_index})
            continue
        label = normalize_text(row[label_index]) if label_index < len(row) else ""
        level = summary_level(label)
        label_at = label_index
        if level is None and has_any(label, RATIO_WORDS):
            # 「占比 / 同比 / 转化率」这类行不满足可加总前提，必须排除在明细之外，
            # 否则 0.6 这种比率会被当成金额加进合计。
            classified.append({"index": index, "kind": "ratio", "label": label, "label_column": label_index})
            continue
        if level is None:
            # 汇总词可能落在别的列（如「地区=华东, 月份=小计」）
            for column, cell in enumerate(row):
                text = normalize_text(cell)
                candidate = summary_level(text)
                if text and candidate:
                    level, label, label_at = candidate, text, column
                    break
        kind = level or "detail"
        if level is None and has_any(label, RATIO_WORDS):
            kind = "ratio"
        classified.append({"index": index, "kind": kind, "label": label, "label_column": label_at})
    return classified


def scope_constraints(row: list[str], label_index: int, label: str) -> list[tuple[int, str]]:
    """汇总行的管辖条件：该行非空文本单元格 → (列, 值)。

    「华东小计」在标签列 → 条件 (地区, 华东)；
    「地区=华东 / 月份=小计」→ 条件 (地区, 华东)。
    """
    constraints: list[tuple[int, str]] = []
    for column, cell in enumerate(row):
        text = normalize_text(cell)
        if not text or parse_number(cell) is not None:
            continue
        if column == label_index:
            remainder = strip_summary_words(text)
            if remainder:
                constraints.append((column, remainder))
            elif summary_level(text) is None:
                constraints.append((column, text))
            continue
        if summary_level(text) is None:
            constraints.append((column, text))
    return constraints


def rows_matching(rows: list[list[str]], indexes: list[int], constraints: list[tuple[int, str]]) -> list[int]:
    matched: list[int] = []
    for index in indexes:
        row = rows[index]
        ok = True
        for column, expected in constraints:
            actual = normalize_text(row[column]) if column < len(row) else ""
            if actual != expected and expected not in actual:
                ok = False
                break
        if ok:
            matched.append(index)
    return matched


# ----------------------------------------------------------------- 对账


def reconcile(
    rows: list[list[str]],
    header_row: int,
    columns: list[str],
    label_index: int,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    classified = classify_rows(rows, header_row, label_index, columns)
    summary_indexes = {item["index"] for item in classified if item["kind"] in {"group", "total", "ratio"}}
    detail_indexes = [item["index"] for item in classified if item["kind"] == "detail"]
    value_columns = numeric_columns(rows, header_row, columns, summary_indexes)

    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    counter = 0

    for item in classified:
        if item["kind"] == "ratio":
            skipped.append({"row": item["index"] + 1, "label": item["label"], "reason": "ratio_row", "detail": "比率行不满足可加总前提，不参与求和对账"})
            continue
        if item["kind"] not in {"group", "total"}:
            continue
        index = item["index"]
        row = rows[index]
        label = item["label"]
        constraints = scope_constraints(row, label_index, label)
        effective_label_index = item["label_column"] if item["kind"] == "group" else label_index
        if item["kind"] == "group" and not constraints:
            previous = [other for other in detail_indexes if other < index]
            if previous:
                fallback = normalize_text(rows[previous[-1]][effective_label_index])
                if fallback:
                    constraints = [(effective_label_index, fallback)]
        for column in value_columns:
            stated = parse_number(row[column]) if column < len(row) else None
            if stated is None:
                continue
            candidates = candidate_scopes(rows, item["kind"], index, constraints, detail_indexes, classified)
            if not candidates:
                skipped.append({"row": index + 1, "label": label, "column": columns[column], "reason": "scope_unresolved", "detail": "无法确定该汇总行管辖的明细范围"})
                continue
            tried: list[dict[str, Any]] = []
            matched_scope: str | None = None
            computed: float | None = None
            for scope_name, scope_indexes in candidates:
                total = sum(
                    value
                    for value in (parse_number(rows[other][column]) if column < len(rows[other]) else None for other in scope_indexes)
                    if value is not None
                )
                diff = stated - total
                tolerance = max(absolute_tolerance, relative_tolerance * abs(stated))
                tried.append({"scope": scope_name, "computed": total, "diff": diff, "detail_rows": len(scope_indexes)})
                if abs(diff) <= tolerance:
                    matched_scope, computed = scope_name, total
                    break
            if computed is None:
                computed = tried[0]["computed"]
            diff = stated - computed
            tolerance = max(absolute_tolerance, relative_tolerance * abs(stated))
            consistent = matched_scope is not None
            counter += 1
            entry: dict[str, Any] = {
                "id": f"R{counter:03d}",
                "kind": "reconciliation",
                "scope_type": item["kind"],
                "scope": describe_scope(matched_scope or tried[0]["scope"], constraints, columns),
                "column": columns[column] if column < len(columns) else f"col{column + 1}",
                "unit": "raw",
                "stated": stated,
                "computed": computed,
                "diff": diff,
                "diff_rate": (diff / stated) if stated else None,
                "status": "consistent" if consistent else "inconsistent",
                "verified": bool(consistent),
                "source": {
                    "row": index + 1,
                    "label": label,
                    "detail_rows": tried[0]["detail_rows"],
                },
            }
            if not consistent:
                entry["tried"] = tried
                entry["detail"] = f"表内写 {stated:,.2f}，按明细重算得 {computed:,.2f}，差 {diff:,.2f}"
            entries.append(entry)

    failed = [entry["id"] for entry in entries if entry["status"] == "inconsistent"]
    if not entries:
        status = "no_summary_rows"
    elif failed:
        status = "fail"
    else:
        status = "pass"

    limitations = [
        "只做加总对账：比率行（占比/同比/率）与比率列不参与，已列入 skipped。",
        "对账只证明「明细之和与汇总一致」，证明不了口径是否合理、明细行本身是否该被排除。",
        "嵌套小计以明细行为基准；若子小计与明细不一致，父子层级会同时报出，需要人工定位是哪一层错。",
        "不解析「1.2万」「3亿」这类带中文数量级的单元格，这类表格请先规范成纯数值。",
        "多区块堆叠的表会同时尝试「全表明细」与「紧邻区块」两种口径，任一成立即视为对上。",
    ]
    return {
        "op": "reconcile",
        "schema_version": "1.0",
        "header_row": header_row + 1,
        "label_column": columns[label_index] if label_index < len(columns) else f"col{label_index + 1}",
        "value_columns": [columns[column] for column in value_columns],
        "summary_rows": [
            {"row": item["index"] + 1, "label": item["label"], "scope_type": item["kind"]}
            for item in classified
            if item["kind"] in {"group", "total"}
        ],
        "reconciliations": entries,
        "skipped": skipped,
        "excluded_rows": [
            {"row": item["index"] + 1, "kind": item["kind"], "label": item["label"]}
            for item in classified
            if item["kind"] in {"group", "total", "ratio", "blank"} and item["label"]
        ],
        "master_check": {
            "status": status,
            "checked": len(entries),
            "failed": len(failed),
            "failed_ids": failed,
            "verdict": master_verdict(status, len(failed)),
        },
        "limitations": limitations,
    }


def candidate_scopes(
    rows: list[list[str]],
    kind: str,
    index: int,
    constraints: list[tuple[int, str]],
    detail_indexes: list[int],
    classified: list[dict[str, Any]],
) -> list[tuple[str, list[int]]]:
    scopes: list[tuple[str, list[int]]] = []
    if constraints:
        matched = rows_matching(rows, detail_indexes, constraints)
        if matched:
            scopes.append(("constraints", matched))
    if kind == "total":
        if detail_indexes:
            scopes.append(("all_detail", list(detail_indexes)))
        previous_stop = max([item["index"] for item in classified if item["kind"] in {"group", "total"} and item["index"] < index], default=-1)
        block = [other for other in detail_indexes if previous_stop < other < index]
        if block:
            scopes.append(("preceding_block", block))
    else:
        previous_stop = max([item["index"] for item in classified if item["kind"] in {"group", "total"} and item["index"] < index], default=-1)
        block = [other for other in detail_indexes if previous_stop < other < index]
        if block:
            scopes.append(("preceding_block", block))
    deduped: list[tuple[str, list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for name, indexes in scopes:
        key = tuple(indexes)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, indexes))
    return deduped


def describe_scope(scope_name: str, constraints: list[tuple[int, str]], columns: list[str]) -> str:
    if scope_name == "all_detail":
        return "全表明细"
    if scope_name == "preceding_block":
        return "紧邻上一汇总行之后的明细区块"
    if constraints and columns:
        parts = []
        for column, value in constraints:
            name = columns[column] if column < len(columns) else f"col{column + 1}"
            parts.append(f"{name}=={value}")
        return "、".join(parts)
    return scope_name


def master_verdict(status: str, failed: int) -> str:
    if status == "no_summary_rows":
        return "未发现可对账的合计/小计行；本表没有可用于交叉验证的校验和。"
    if status == "fail":
        return f"不通过：{failed} 项对不上。在解决之前，不要把这些数字写进交付物。"
    return "通过：所有可机器验证的汇总项都与明细一致。"


# ----------------------------------------------------------------- 入口


def main() -> int:
    parser = argparse.ArgumentParser(description="表内对账：用合计/小计行交叉验证明细")
    parser.add_argument("--data", required=True, help="数据文件（.xlsx/.xlsm/.csv/.tsv）")
    parser.add_argument("--sheet", help="xlsx 的 sheet 名；省略时选非空行最多的")
    parser.add_argument("--out", help="对账结果 JSON 输出路径")
    parser.add_argument("--absolute-tolerance", type=float, default=DEFAULT_ABSOLUTE_TOLERANCE, help="绝对容差（默认 0.5，覆盖四舍五入）")
    parser.add_argument("--relative-tolerance", type=float, default=DEFAULT_RELATIVE_TOLERANCE, help="相对容差（默认 0.005）")
    args = parser.parse_args()

    source = ensure_readable(args.data)
    if args.absolute_tolerance < 0 or args.relative_tolerance < 0:
        parser.error("容差不能为负")

    grid, sheet = read_grid(source, args.sheet)
    rows = padded(grid)
    if not rows or not any(not is_blank(cell) for row in rows for cell in row):
        raise DataError(f"表里没有可对账的内容：{source}")
    header_row = detect_header_row(rows)
    columns = build_columns(rows[header_row], len(rows[header_row]))
    label_index = label_column_index(rows, header_row)
    report = reconcile(rows, header_row, columns, label_index, args.absolute_tolerance, args.relative_tolerance)
    report["sheet"] = sheet
    report["file"] = {"path": str(source.resolve()), "name": source.name, "sha256": file_sha256(source)}

    if args.out:
        write_json(args.out, report)

    master = report["master_check"]
    print(f"sheet={sheet} 表头行={report['header_row']} 标签列={report['label_column']} 数值列={report['value_columns']}")
    for entry in report["reconciliations"]:
        marker = "✓" if entry["verified"] else "✗"
        print(f"  {marker} {entry['id']} {entry['scope']} / {entry['column']}: 表内 {entry['stated']:,.2f} vs 明细 {entry['computed']:,.2f}  [{entry['status']}]")
    for item in report["skipped"]:
        print(f"  – 跳过 第{item['row']}行「{item.get('label', '')}」：{item['reason']}")
    print(f"MASTER CHECK：{master['verdict']}")
    return 1 if master["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(cli_guard(main))
