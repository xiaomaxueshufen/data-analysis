"""da_reconcile.py 的回归测试：用「表自己带的合计/小计」当校验和。

覆盖：干净表通过对账、被篡改的合计/小计被抓住、分组范围不会串组、
比率行不参与求和、千分位与会计式负数、无汇总行时的行为、退出码语义。

运行：python3 tests/test_reconcile.py（也兼容 pytest）
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECONCILE = ROOT / "scripts" / "da_reconcile.py"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    if not condition:
        # pytest 只把异常当失败；不抛的话断言失败会被静默吞掉
        raise AssertionError(f"{name}" + (f" — {detail}" if detail else ""))


def run_reconcile(path: Path, extra: list[str] | None = None) -> tuple[dict, int]:
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "reconcile.json"
        command = [sys.executable, str(RECONCILE), "--data", str(path), "--out", str(out)]
        command += extra or []
        completed = subprocess.run(command, capture_output=True, text=True)
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"status": "parse_error", "stdout": completed.stdout, "stderr": completed.stderr}
        return payload, completed.returncode


def write_xlsx(path: Path, rows: list[list[object]], sheet: str = "Sheet1") -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


def entry_by_scope(payload: dict, scope_type: str, scope_contains: str | None = None) -> dict | None:
    for entry in payload.get("reconciliations", []):
        if entry.get("scope_type") != scope_type:
            continue
        if scope_contains and scope_contains not in str(entry.get("scope")):
            continue
        return entry
    return None


# ---------------------------------------------------------------- 基本对账


def test_clean_table(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "clean.xlsx", [
        ["2026 年 1 月销售明细"],
        ["地区", "月份", "金额"],
        ["华东", "1月", 1000], ["华东", "2月", 2000],
        ["华东小计", "", 3000],
        ["华北", "1月", 1500], ["华北", "2月", 2500],
        ["华北小计", "", 4000],
        ["合计", "", 7000],
        ["占比", "", 0.6],
    ])
    payload, code = run_reconcile(path)
    check("干净表 master_check 通过", payload["master_check"]["status"] == "pass", payload["master_check"]["verdict"])
    check("干净表退出码 0", code == 0, f"exit={code}")
    check("干净表所有条目 verified", all(item["verified"] for item in payload["reconciliations"]))
    check("干净表识别表头行", payload["header_row"] == 1 + 1, f"header_row={payload['header_row']}")


def test_tampered_total(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "bad_total.xlsx", [
        ["地区", "金额"],
        ["华东", 1000], ["华东", 2000], ["华东小计", 3000],
        ["华北", 1500], ["华北", 2500], ["华北小计", 4000],
        ["合计", 99000],
    ])
    payload, code = run_reconcile(path)
    total = entry_by_scope(payload, "total")
    check("篡改合计被判定为 inconsistent", total is not None and total["status"] == "inconsistent",
          json.dumps(total, ensure_ascii=False)[:120] if total else "缺 total 条目")
    check("篡改合计 verified=false", total is not None and total["verified"] is False)
    check("篡改合计 master_check 失败", payload["master_check"]["status"] == "fail")
    check("篡改合计退出码 1", code == 1, f"exit={code}")
    check("篡改合计给出差额", total is not None and abs(total["diff"] - 92000) < 1e-6,
          f"diff={total['diff'] if total else None}")


def test_group_scope_not_crossed(tmp_path: Path) -> None:
    """小计写成了「两组之和」，说明分组范围没串组时会被抓出来。"""
    path = write_xlsx(tmp_path / "bad_subtotal.xlsx", [
        ["地区", "金额"],
        ["华东", 1000], ["华东", 2000],
        ["华东小计", 4500],            # 1000+2000=3000，写成 4500
        ["华北", 1500], ["华北", 2500],
        ["华北小计", 4000],
        ["合计", 7000],
    ])
    payload, code = run_reconcile(path)
    group = entry_by_scope(payload, "group", "地区==华东")
    check("分组小计只对本组明细", group is not None and abs(group["computed"] - 3000) < 1e-6,
          f"computed={group['computed'] if group else None}")
    check("被篡改的小计被抓出", group is not None and group["status"] == "inconsistent")
    check("小计错但合计对时，合计仍通过",
          entry_by_scope(payload, "total")["status"] == "consistent")


def test_subtotal_word_in_other_column(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "layout_b.xlsx", [
        ["地区", "月份", "金额"],
        ["华东", "1月", 1000], ["华东", "2月", 2000],
        ["华东", "小计", 3000],
        ["华北", "1月", 1500], ["华北", "2月", 2500],
        ["华北", "小计", 4000],
        ["", "合计", 7000],
    ])
    payload, _ = run_reconcile(path)
    group = entry_by_scope(payload, "group", "地区==华东")
    check("汇总词在非标签列也能定范围", group is not None and abs(group["computed"] - 3000) < 1e-6,
          f"scope={group['scope'] if group else None}")
    check("该版式 master_check 通过", payload["master_check"]["status"] == "pass")


def test_ratio_row_not_summed(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "ratio.xlsx", [
        ["渠道", "金额"],
        ["A", 10], ["B", 20],
        ["合计", 30],
        ["占比", 0.5],
    ])
    payload, _ = run_reconcile(path)
    total = entry_by_scope(payload, "total")
    check("比率行不污染合计", total is not None and abs(total["computed"] - 30) < 1e-6,
          f"computed={total['computed'] if total else None}")
    reasons = {item["reason"] for item in payload["skipped"]}
    check("比率行被标记跳过", "ratio_row" in reasons, f"skipped={payload['skipped']}")


def test_number_formats(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "formats.xlsx", [
        ["部门", "成本"],
        ["研发", "1,234.50"], ["研发", "(65.50)"],
        ["研发合计", "1169.00"],
        ["市场", "￥500"], ["市场", "２５０"],
        ["市场合计", "750"],
        ["总计", "1919.00"],
    ])
    payload, code = run_reconcile(path)
    check("千分位/会计负数/货币/全角都能解析",
          payload["master_check"]["status"] == "pass" and code == 0,
          json.dumps(payload["master_check"], ensure_ascii=False)[:120])


def test_tolerance_and_rounding(tmp_path: Path) -> None:
    """四舍五入后的合计不应被误判为对账失败。"""
    path = write_xlsx(tmp_path / "rounded.xlsx", [
        ["项", "金额"],
        ["a", 0.334], ["b", 0.333],
        ["合计", 0.67],
    ])
    payload, _ = run_reconcile(path)
    check("四舍五入差额落在容差内", payload["master_check"]["status"] == "pass")

    strict, _ = run_reconcile(path, extra=["--absolute-tolerance", "0.0001", "--relative-tolerance", "0"])
    check("收紧容差后同一张表报错", strict["master_check"]["status"] == "fail")


def test_no_summary_rows(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "nosum.xlsx", [["日期", "订单"], ["2026-01-01", 100], ["2026-01-02", 120]])
    payload, code = run_reconcile(path)
    check("无汇总行时不编造对账结论", payload["master_check"]["status"] == "no_summary_rows")
    check("无汇总行退出码 0", code == 0, f"exit={code}")


def test_csv_input(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["渠道", "金额"])
        writer.writerow(["A", 10])
        writer.writerow(["B", 20])
        writer.writerow(["A小计", 10])
        writer.writerow(["B小计", 20])
        writer.writerow(["合计", 30])
    payload, code = run_reconcile(path)
    check("CSV 输入可对账", payload["master_check"]["status"] == "pass" and code == 0,
          json.dumps(payload["master_check"], ensure_ascii=False)[:120])


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        for suite in (
            test_clean_table,
            test_tampered_total,
            test_group_scope_not_crossed,
            test_subtotal_word_in_other_column,
            test_ratio_row_not_summed,
            test_number_formats,
            test_tolerance_and_rounding,
            test_no_summary_rows,
            test_csv_input,
        ):
            before = len(RESULTS)
            try:
                suite(tmp_path)
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
