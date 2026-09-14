"""依赖自检：缺 numpy / pandas 时给出可执行的安装指引，而不是甩一个 traceback。

这个模块刻意不 import 任何第三方库——它必须在 numpy / pandas 之前被 import，
所以只能依赖标准库。

用法（放在 CLI 的最前面）：
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from da_envcheck import ensure_dependencies
    ensure_dependencies()
"""

from __future__ import annotations

import sys

REQUIRED = ("numpy", "pandas")

GUIDE = """{rule}
[data-analysis] 缺少依赖：{missing}
本 skill 的计算脚本需要 numpy 和 pandas。请任选一种方式安装：

  方式一：用项目根目录的 requirements.txt（推荐）
    pip install -r requirements.txt

  方式二：在当前解释器里直接装
    python3 -m pip install numpy pandas

  方式三：PEP 668 的「externally managed」环境（Homebrew / 部分发行版自带 python）
    优先建虚拟环境：
      python3 -m venv .venv && source .venv/bin/activate && pip install numpy pandas
    清楚风险后再绕过保护：
      pip install --break-system-packages numpy pandas

装好后重新运行本命令即可。
{rule}
"""


def missing_dependencies(required: tuple[str, ...] = REQUIRED) -> list[str]:
    missing = []
    for name in required:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    return missing


def ensure_dependencies(required: tuple[str, ...] = REQUIRED) -> None:
    missing = missing_dependencies(required)
    if not missing:
        return
    rule = "=" * 64
    print(GUIDE.format(rule=rule, missing=", ".join(missing)), file=sys.stderr)
    raise SystemExit(2)
