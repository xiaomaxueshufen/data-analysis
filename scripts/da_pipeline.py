from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from da_analyze import analyze
from da_common import file_sha256, write_json
from da_profile import profile_data
from da_quality import quality_gate
from da_report import fallback_narrative, render_report


def run_pipeline(data_path: str, out_dir: str, question: str) -> Path:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    profile = profile_data(data_path)
    write_json(output / "00_manifest.json", {
        "schema_version": "1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "data_path": str(Path(data_path).resolve()),
        "sha256": file_sha256(data_path),
        "question": question,
        "mode": "pipeline_with_assumptions",
    })
    write_json(output / "01_profile.json", profile)
    quality = quality_gate(profile, data_path)
    write_json(output / "03_quality.json", quality)
    contract = {
        "decision": question or "探索数据中的主要变化并提出后续分析方向",
        "fields": {},
        "baseline": {"type": "same_weekday_robust", "window_days": 56},
        "assumptions": ["字段角色由名称和类型候选识别，需在正式分析中确认。"],
    }
    plan = {
        "primary_method": "anomaly",
        "secondary_methods": ["funnel", "ratio_decomp"],
        "dependency_order": ["quality", "anomaly", "funnel", "ratio_decomp", "mechanism_scan"],
        "mode": "default_pipeline_plan",
    }
    write_json(output / "02_contract.json", contract)
    write_json(output / "04_plan.json", plan)
    analysis = analyze(data_path, profile, contract, quality, plan)
    write_json(output / "04_analysis.json", analysis)
    write_json(output / "06_claims.json", analysis.get("auto_claims", []))
    write_json(output / "07_narrative.json", fallback_narrative(analysis, quality))
    render_report(str(output), str(output / "report.html"))
    return output / "report.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="一键生成数据分析报告")
    parser.add_argument("--data", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--question", default="")
    args = parser.parse_args()
    report = run_pipeline(args.data, args.out_dir, args.question)
    print(report)


if __name__ == "__main__":
    main()
