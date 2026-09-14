"""CLI 健壮性回归测试：坏输入不许把 traceback 甩给用户，好输入不许被误伤。

覆盖三类此前只在手工探测里验证过的行为：
1. 路径/文件层：不存在、目录、不支持的后缀、空文件、BOM、TSV、CRLF、参差行、
   重复表头、坏 Excel —— 要么给出明确 DataError，要么正常解析；
2. CLI 契约：DataError / JSONDecodeError / OSError 转成结构化失败 + 退出码 2，
   而 KeyError / IndexError / TypeError 这类真 bug 必须继续抛栈；
3. 算子退化输入：17 个算子对空表/单行/零分母/非数值列只允许「正常返回」或
   「DataError」，绝不允许别的异常类型漏出去。

运行：python3 tests/test_cli_robustness.py（也兼容 pytest）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import da_ops  # noqa: E402
from da_common import DataError, cli_guard, ensure_readable, load_tables, sanitize_json, write_json  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    if not condition:
        raise AssertionError(f"{name}" + (f" — {detail}" if detail else ""))


def expect_dataerror(name: str, work, contains: str = "") -> None:
    try:
        work()
    except DataError as error:
        check(name, contains in str(error), f"DataError: {error}")
    except Exception as error:  # noqa: BLE001
        check(name, False, f"抛出了 {type(error).__name__} 而不是 DataError：{error}")
    else:
        check(name, False, "本应抛 DataError，却正常返回")


def write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


# --------------------------------------------------------------------------- #
# 1. 路径与文件层
# --------------------------------------------------------------------------- #
def test_missing_file(tmp_path: Path) -> None:
    expect_dataerror("不存在的文件被拦下", lambda: load_tables(tmp_path / "nope.csv"), "文件不存在")
    expect_dataerror("不存在的路径被 ensure_readable 拦下", lambda: ensure_readable(tmp_path / "nope.xlsx"))


def test_directory_rejected(tmp_path: Path) -> None:
    expect_dataerror("目录被拦下", lambda: load_tables(tmp_path), "目录")


def test_unsupported_suffix(tmp_path: Path) -> None:
    for name in ("a.json", "a.dat", "a.txt", "noext"):
        path = write(tmp_path / name, "日期,金额\n2026-01-01,1\n")
        expect_dataerror(f"{name} 后缀被拦下", lambda p=path: load_tables(p), "不支持的文件类型")


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    expect_dataerror("0 字节文件被拦下", lambda: load_tables(path), "空的")


def test_header_only_csv(tmp_path: Path) -> None:
    path = write(tmp_path / "h.csv", "日期,渠道,金额\n")
    tables = load_tables(path)
    frame = tables["h"]["frame"]
    check("只有表头的 CSV 能解析出列", list(frame.columns) == ["日期", "渠道", "金额"])
    check("只有表头的 CSV 行数为 0", len(frame) == 0)


def test_utf8_bom_and_crlf(tmp_path: Path) -> None:
    path = write(tmp_path / "bom.csv", "日期,渠道,金额\r\n2026-01-01,A,10\r\n", encoding="utf-8-sig")
    frame = load_tables(path)["bom"]["frame"]
    check("BOM 不会污染第一列列名", frame.columns[0] == "日期", repr(frame.columns[0]))
    check("CRLF 行尾能正常解析", len(frame) == 1)


def test_tsv(tmp_path: Path) -> None:
    path = write(tmp_path / "t.tsv", "日期\t渠道\t金额\n2026-01-01\tA\t10\n")
    frame = load_tables(path)["t"]["frame"]
    check("TSV 按制表符切分", list(frame.columns) == ["日期", "渠道", "金额"], repr(list(frame.columns)))
    check("TSV 数值列解析正确", float(frame["金额"].iloc[0]) == 10.0)


def test_ragged_rows(tmp_path: Path) -> None:
    path = write(tmp_path / "r.csv", "日期,渠道,金额\n2026-01-01,A,10,99\n2026-01-02,B\n")
    table = load_tables(path)["r"]
    frame = table["frame"]
    check("参差行的表头不被数据行顶掉", list(frame.columns) == ["日期", "渠道", "金额"], repr(list(frame.columns)))
    check("参差行不会把第一列挤成索引", frame.index.name is None and list(frame.index) == [0, 1])
    check("参差行仍保留两行数据", len(frame) == 2)
    check("多余格子造成的丢数据被记录成 parse_notices", bool(table.get("parse_notices")), repr(table.get("parse_notices")))


def test_duplicate_headers(tmp_path: Path) -> None:
    path = write(tmp_path / "d.csv", "日期,金额,金额\n2026-01-01,1,2\n")
    columns = list(load_tables(path)["d"]["frame"].columns)
    check("重复表头被去重成唯一列名", len(columns) == len(set(columns)), repr(columns))


def test_excel_round_trip(tmp_path: Path) -> None:
    import pandas as pd

    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"日期": ["2026-01-01"], "金额": [10]}).to_excel(writer, sheet_name="明细", index=False)
        pd.DataFrame({"渠道": ["A"], "金额": [10]}).to_excel(writer, sheet_name="汇总", index=False)
    tables = load_tables(path)
    check("Excel 多 sheet 都能读出来", set(tables) == {"明细", "汇总"}, repr(sorted(tables)))
    check("Excel sheet 列名正确", list(tables["明细"]["frame"].columns) == ["日期", "金额"])


def test_broken_excel(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"this is definitely not a zip workbook")
    expect_dataerror("坏 Excel 被拦下", lambda: load_tables(path), "无法打开 Excel")


# --------------------------------------------------------------------------- #
# 2. CLI 契约
# --------------------------------------------------------------------------- #
def test_cli_guard_translates_input_errors(tmp_path: Path) -> None:
    import contextlib
    import io

    def run(work) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = cli_guard(work)
        return code, buffer.getvalue()

    code, err = run(lambda: (_ for _ in ()).throw(DataError("坏输入")))
    check("DataError → 退出码 2", code == 2)
    check("DataError → 结构化 JSON 错误", json.loads(err)["status"] == "fail" and "坏输入" in err)

    code, err = run(lambda: json.loads("{oops"))
    check("JSONDecodeError → 退出码 2", code == 2 and json.loads(err)["status"] == "fail")

    code, err = run(lambda: (_ for _ in ()).throw(OSError("磁盘满了")))
    check("OSError → 退出码 2", code == 2 and "OSError" in err)

    check("正常路径原样返回退出码", run(lambda: 0)[0] == 0)


def test_cli_guard_does_not_hide_real_bugs(tmp_path: Path) -> None:
    del tmp_path  # 只是沿用统一的 suite(tmp_path) 签名
    for exc in (KeyError("k"), IndexError("i"), TypeError("t"), AttributeError("a")):
        try:
            cli_guard(lambda e=exc: (_ for _ in ()).throw(e))
        except type(exc):
            check(f"真 bug {type(exc).__name__} 继续抛栈", True)
        else:
            check(f"真 bug {type(exc).__name__} 继续抛栈", False, "被 cli_guard 吞掉了")


def test_write_json_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "o.json"
    write_json(path, {"inf": float("inf"), "nan": float("nan"), "nested": [1.0, float("-inf")]})
    text = path.read_text(encoding="utf-8")
    check("非有限值被写成 null", "Infinity" not in text and "NaN" not in text, text[:80])
    try:
        json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        ok = True
    except ValueError:
        ok = False
    check("输出是严格合法 JSON", ok)
    check("sanitize_json 递归处理容器", sanitize_json({"a": [float("inf"), {"b": float("nan")}]}) == {"a": [None, {"b": None}]})


def test_ops_execute_contract(tmp_path: Path) -> None:
    path = write(tmp_path / "d.csv", "日期,渠道,访客数,金额\n2026-01-01,A,10,100\n2026-01-02,A,20,200\n")
    expect_dataerror("未知算子 → DataError", lambda: da_ops.execute("nope", str(path), {}), "未知算子")
    expect_dataerror("非对象配置 → DataError", lambda: da_ops.execute("contribution", str(path), ["x"]), "JSON 对象")
    expect_dataerror("缺字段配置 → DataError", lambda: da_ops.execute("contribution", str(path), {}))
    expect_dataerror("数据算子缺数据 → DataError", lambda: da_ops.execute("contribution", None, {"group_field": "渠道", "value_field": "金额"}))
    result = da_ops.execute("contribution", str(path), {"group_field": "渠道", "value_field": "金额"})
    check("正常算子返回带 sheet/config 的对象", isinstance(result, dict) and "sheet" in result and result["config"]["group_field"] == "渠道")


def test_envcheck_guidance_when_dependency_missing(tmp_path: Path) -> None:
    """缺 numpy/pandas 时必须给安装指引 + 退出码 2，而不是裸 traceback。

    用户第一台机器上最可能撞到的就是这条路径（skill 需要 numpy/pandas），
    所以它值得一个回归测试，而不是靠「本地装着库所以不会发生」。
    """
    fake = tmp_path / "fakelibs"
    fake.mkdir()
    (fake / "pandas.py").write_text('raise ImportError("simulated missing pandas")\n', encoding="utf-8")
    data = tmp_path / "d.csv"
    data.write_text("日期,渠道,金额\n2026-01-01,A,10\n", encoding="utf-8")
    profile = tmp_path / "p.json"
    profile.write_text(json.dumps({"main_table": "d"}), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(fake)}
    cases = [
        ["scripts/da_profile.py", "--data", str(data), "--out", str(tmp_path / "o.json")],
        ["scripts/da_quality.py", "--profile", str(profile), "--data", str(data), "--out", str(tmp_path / "o.json")],
        ["scripts/da_reconcile.py", "--data", str(data), "--out", str(tmp_path / "o.json")],
        ["scripts/da_report.py", "--spec", str(profile), "--out", str(tmp_path / "o.html")],
    ]
    for args in cases:
        proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
        name = Path(args[0]).name
        check(f"缺 pandas 时 {name} 给出安装指引", "缺少依赖" in proc.stderr and "pip install" in proc.stderr, proc.stderr[:120])
        check(f"缺 pandas 时 {name} 退出码 2 且无 traceback", proc.returncode == 2 and "Traceback" not in proc.stderr, f"exit={proc.returncode} {proc.stderr[:120]}")


def test_lightweight_cli_end_to_end(tmp_path: Path) -> None:
    cases = [
        ("profile/缺失文件", ["scripts/da_profile.py", "--data", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "o.json")], 2),
        ("reconcile/空文件", ["scripts/da_reconcile.py", "--data", str(tmp_path / "e.csv"), "--out", str(tmp_path / "o.json")], 2),
        ("report/非对象规格", ["scripts/da_report.py", "--spec", str(tmp_path / "s.json"), "--out", str(tmp_path / "o.html")], 2),
        ("verify/坏 JSON", ["scripts/da_verify.py", "--claims", str(tmp_path / "c.json")], 1),
        ("ops/缺字段配置", ["scripts/da_ops.py", "contribution", "--config", str(tmp_path / "oc.json"), "--data", str(tmp_path / "d.csv"), "--out", str(tmp_path / "o.json")], 2),
    ]
    (tmp_path / "e.csv").write_bytes(b"")
    (tmp_path / "s.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "c.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "oc.json").write_text("{}", encoding="utf-8")
    (tmp_path / "d.csv").write_text("日期,渠道,金额\n2026-01-01,A,10\n", encoding="utf-8")
    for name, args, expected in cases:
        proc = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        check(f"{name} 退出码 = {expected}", proc.returncode == expected, f"实际 {proc.returncode}: {proc.stderr[-160:]}")
        check(f"{name} 无 traceback", "Traceback" not in proc.stderr, proc.stderr[-160:])


# --------------------------------------------------------------------------- #
# 3. 算子退化输入扫描
# --------------------------------------------------------------------------- #
DEGENERATE = {
    "one_row": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,10,1,100\n",
    "empty_body": "日期,渠道,访客数,下单数,金额\n",
    "zero_denom": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,0,0,0\n2026-01-02,A,0,0,0\n",
    "one_group": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,10,1,100\n2026-01-02,A,20,2,200\n",
    "text_cols": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,abc,x,\n2026-01-02,A,def,y,\n",
    "negatives": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,-10,1,-100\n2026-01-02,A,-20,2,-200\n",
    "huge": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,1e308,1e300,1e308\n2026-01-02,A,1e308,1e300,1e308\n",
    "dup_dates": "日期,渠道,访客数,下单数,金额\n2026-01-01,A,10,1,100\n2026-01-01,A,20,2,200\n",
}

OP_CONFIG = {
    "ab_effect": {"variant_field": "渠道", "metric_field": "访客数", "control": "A", "treatment": "B"},
    "anomaly_scan": {"date_field": "日期", "metric_field": "访客数"},
    "attribution": {"date_field": "日期", "metric_field": "金额", "channel_field": "渠道"},
    "changepoint_scan": {"date_field": "日期", "metric_field": "访客数"},
    "cohort_retention": {"id_field": "渠道", "date_field": "日期", "reference_date": "2026-01-01"},
    "contribution": {"group_field": "渠道", "value_field": "金额"},
    "cuped": {"variant_field": "渠道", "metric_field": "访客数", "covariate_field": "下单数", "control": "A", "treatment": "B"},
    "funnel_rates": {"stages": ["访客数", "下单数", "金额"]},
    "multiple_testing": {"tests": [{"p_value": 0.01}, {"p_value": 0.2}]},
    "path_analysis": {"id_field": "渠道", "step_field": "日期"},
    "power_mde": {"metric_type": "binary", "baseline_rate": 0.1, "mde_relative": 0.05},
    "price_elasticity": {"price_field": "金额", "quantity_field": "下单数", "group_field": "渠道"},
    "ratio_decomp": {
        "group_field": "渠道", "numerator_field": "下单数", "denominator_field": "访客数",
        "base_filter": {"渠道": "A"}, "current_filter": {"渠道": "A"},
    },
    "rfm": {"id_field": "渠道", "date_field": "日期", "value_field": "金额", "reference_date": "2026-02-01"},
    "segment_profile": {"segment_field": "渠道", "value_field": "金额"},
    "srm_check": {"variant_field": "渠道", "unit_field": "渠道"},
    "survival": {"id_field": "渠道", "date_field": "日期", "event_field": "下单数"},
}


def test_degenerate_operator_inputs(tmp_path: Path) -> None:
    paths = {name: write(tmp_path / f"{name}.csv", text) for name, text in DEGENERATE.items()}
    problems: list[str] = []
    checked = 0
    for op in sorted(da_ops.OPERATORS):
        configs = [("empty_cfg", {})]
        if op in OP_CONFIG:
            configs.append(("full_cfg", OP_CONFIG[op]))
        for data_name, path in paths.items():
            for cfg_name, config in configs:
                checked += 1
                try:
                    result = da_ops.execute(op, str(path), dict(config))
                except DataError:
                    continue
                except Exception as error:  # noqa: BLE001
                    problems.append(f"{op}/{data_name}/{cfg_name} → {type(error).__name__}: {error}")
                else:
                    if not isinstance(result, dict):
                        problems.append(f"{op}/{data_name}/{cfg_name} → 非 dict 结果")
    check(f"算子退化扫描 {checked} 组只出现 DataError 或正常返回", not problems, "; ".join(problems[:5]))
    # 纯设计算子不需要数据文件
    for op in ("power_mde", "multiple_testing"):
        config = OP_CONFIG[op]
        result = da_ops.execute(op, None, dict(config))
        check(f"无数据算子 {op} 可离线执行", isinstance(result, dict))


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        for suite in (
            test_missing_file,
            test_directory_rejected,
            test_unsupported_suffix,
            test_empty_file,
            test_header_only_csv,
            test_utf8_bom_and_crlf,
            test_tsv,
            test_ragged_rows,
            test_duplicate_headers,
            test_excel_round_trip,
            test_broken_excel,
            test_cli_guard_translates_input_errors,
            test_cli_guard_does_not_hide_real_bugs,
            test_write_json_is_strict,
            test_ops_execute_contract,
            test_envcheck_guidance_when_dependency_missing,
            test_lightweight_cli_end_to_end,
            test_degenerate_operator_inputs,
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
