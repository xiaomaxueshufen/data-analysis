#!/usr/bin/env python3
"""把 README 里那些「token 数」「成本」的数字变成可复算的输出。

README / plugin 说明里出现过几类容易被误读的数字：常驻正文的 token 数、
写报告规格 JSON 与手写同版式 HTML 的 token 差、测试覆盖率。它们的口径不同
（编码器不同、统计对象不同），所以这里统一用一条命令打印，谁都可以自己复算。

用法
----
    python scripts/da_measure.py                 # 有 tiktoken 时打印 token 口径
    python scripts/da_measure.py --json          # 机器可读
    python scripts/da_measure.py --require-tiktoken

token 计数依赖 tiktoken（`pip install tiktoken`），它**不是** skill 的运行依赖；
没有装的时候脚本会打印安装指引并把 token 部分标成 unavailable，而不是抛栈。
覆盖率不在这里算，用 `python -m pytest tests/ --cov=scripts --cov-report=term`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 编码器口径必须写清楚：同一份中文文件在不同编码器下能差 25% 以上，
# 只说「≈4,900 token」而不说用哪个编码器，等于没说。
ENCODINGS = ("o200k_base", "cl100k_base")
TOKEN_TARGETS = (
    ("SKILL.md（常驻正文）", "SKILL.md"),
    ("README.md", "README.md"),
    ("references/report-design.md", "references/report-design.md"),
    ("references/harness.md", "references/harness.md"),
    ("examples/report_spec.example.json（模型写规格）", "examples/report_spec.example.json"),
    ("examples/report_example.html（手写同版式 HTML 的等价物）", "examples/report_example.html"),
)

COVERAGE_COMMAND = "python -m pytest tests/ --cov=scripts --cov-report=term-missing"


def tiktoken_encoders() -> tuple[dict, str | None]:
    try:
        import tiktoken  # type: ignore
    except ImportError:
        return {}, "tiktoken 未安装：pip install tiktoken（只用于测量，不是运行依赖）"
    return {name: tiktoken.get_encoding(name) for name in ENCODINGS}, None


def measure_tokens() -> tuple[dict, str | None]:
    encoders, problem = tiktoken_encoders()
    if problem:
        return {}, problem
    out: dict[str, dict[str, int]] = {}
    for label, relative in TOKEN_TARGETS:
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        out[label] = {name: len(encoder.encode(text)) for name, encoder in encoders.items()}
        out[label]["characters"] = len(text)
    return out, None


def main() -> int:
    parser = argparse.ArgumentParser(description="打印 token / 覆盖率口径与实测值")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--require-tiktoken", action="store_true", help="缺少 tiktoken 时以退出码 2 结束")
    args = parser.parse_args()

    tokens, problem = measure_tokens()
    if problem and args.require_tiktoken:
        print(json.dumps({"status": "fail", "error": problem}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "tokens": tokens,
            "encoding_note": "同一文件在不同编码器下差异显著，引用时必须写明编码器",
            "coverage_command": COVERAGE_COMMAND,
            "problem": problem,
        }, ensure_ascii=False, indent=2))
        return 0

    print("token 口径：tiktoken，逐文件按编码器分别计数")
    if problem:
        print(f"  unavailable — {problem}")
    else:
        for label, counts in tokens.items():
            cells = "  ".join(f"{name}={counts[name]}" for name in ENCODINGS if name in counts)
            print(f"  {label:<58} {cells}")
        spec = tokens.get("examples/report_spec.example.json（模型写规格）")
        html = tokens.get("examples/report_example.html（手写同版式 HTML 的等价物）")
        if spec and html:
            for name in ENCODINGS:
                if name in spec and name in html:
                    print(f"  规格 vs 手写 HTML（{name}）：{spec[name]} vs {html[name]}，约 1:{html[name] / spec[name]:.1f}")
    print("")
    print("覆盖率口径：整仓 scripts/ 一起统计（含 CLI、渲染器与算子），不是「核心模块」子集")
    print(f"  复算命令：{COVERAGE_COMMAND}")
    print("  依赖：pip install pytest pytest-cov（只用于自检，不是运行依赖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
