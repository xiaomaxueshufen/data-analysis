"""让 subprocess 里的 CLI 也计入覆盖率。

tests/ 里的 CLI 测试是 subprocess 调用 `scripts/*.py` 的：没有这段代码，
da_verify / da_reconcile / da_profile / da_quality 在覆盖率报告里永远是 0%，
README 里的覆盖率数字就会低得没有意义。

只有设置 COVERAGE_PROCESS_START 时才生效（默认不开销）：
    COVERAGE_PROCESS_START=$PWD/.coveragerc python -m pytest tests/ --cov=scripts --cov-report=term
"""

from __future__ import annotations

import os

if os.environ.get("COVERAGE_PROCESS_START"):
    import coverage

    coverage.process_startup()
