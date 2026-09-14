"""da_report.py 的回归测试：规格 JSON → 自包含离线 HTML。

覆盖：六段式骨架由脚本写死、未知 theme/style/图表类型被拦、证据引用与层级校验、
占位词与降级字段校验、marker 越界、XSS 转义、零外部请求、主题产出差异、
有符号条形的方向编码、矩阵文字对比度自适应，以及「不对数值几何做动画」。

运行：python3 tests/test_report.py（也兼容 pytest）
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "scripts" / "da_report.py"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    if not condition:
        # pytest 只把异常当失败；不抛的话断言失败会被静默吞掉
        raise AssertionError(f"{name}" + (f" — {detail}" if detail else ""))


_spec = importlib.util.spec_from_file_location("da_report", REPORT)
da_report = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(da_report)


def minimal_spec() -> dict:
    return {
        "meta": {"title": "测试报告", "decision": "复盘", "window": "2026-01-01~2026-03-31", "source": "t.csv"},
        "diversity": {"theme": "apple-light", "style": "apple", "density": 4},
        "kpis": [{"label": "订单量", "value": 1234.5, "delta": "-20.4%", "direction": "down"}],
        "findings": [
            {"title": "发现一", "body": "正文一", "level": "L1", "tone": "negative", "evidence_ids": ["E001"]}
        ],
        "background": {"narrative": "背景"},
        "data_overview": {
            "narrative": "概况",
            "table": {
                "columns": [{"key": "k", "label": "项目"}, {"key": "v", "label": "值"}],
                "rows": [{"k": "行数", "v": 90}],
                "numeric_columns": ["v"],
            },
        },
        "analysis": [
            {
                "heading": "机制一",
                "narrative": "说明",
                "charts": [
                    {"type": "line", "title": "趋势", "baseline": 1000,
                     "data": [{"label": "1月", "value": 1000}, {"label": "2月", "value": 900}, {"label": "3月", "value": 780}]},
                    {"type": "bars", "title": "贡献", "data": [
                        {"label": "渠道A", "value": -141.2}, {"label": "渠道B", "value": -38.6}]},
                    {"type": "funnel", "title": "漏斗", "data": [
                        {"label": "下单", "value": 78914}, {"label": "支付成功", "value": 68264}]},
                    {"type": "matrix", "title": "矩阵", "rows": ["渠道A", "渠道B"], "columns": ["1月", "2月"],
                     "cells": {"渠道A|1月": 502, "渠道A|2月": 361, "渠道B|1月": 301, "渠道B|2月": 171}},
                ],
            }
        ],
        "conclusions": [{"text": "结论一", "evidence_ids": ["E001"]}],
        "next_steps": [{"question": "还缺什么？", "data_needed": "支付日志"}],
        "appendix": {"notes": ["口径说明"]},
    }


def render(spec: dict, tmp_path: Path) -> tuple[str, dict, int]:
    spec_path = tmp_path / "spec.json"
    out_path = tmp_path / "report.html"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(REPORT), "--spec", str(spec_path), "--out", str(out_path)],
        capture_output=True, text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"status": "parse_error", "stdout": completed.stdout, "stderr": completed.stderr}
    markup = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    return markup, payload, completed.returncode


def test_renders_full_skeleton(tmp_path: Path) -> None:
    markup, payload, code = render(minimal_spec(), tmp_path)
    check("渲染返回 exit 0", code == 0, str(payload)[:160])
    check("输出体积 > 4KB", len(markup.encode("utf-8")) > 4096, f"{len(markup.encode('utf-8'))} bytes")
    for section in da_report.SECTIONS:
        check(f"六段式含「{section}」", section in markup)
    check("六个 section 元素齐备", markup.count('<section class="block"') == 6)
    check("自包含：零外部请求", payload.get("external_requests") == [], str(payload.get("external_requests")))
    check("关键数字用 tabular-nums", "tabular-nums" in markup)
    check("无外部协议引用", not any(token in markup for token in ("http://", "https://", "//cdn")))


def test_unknown_theme_and_style_rejected(tmp_path: Path) -> None:
    spec = minimal_spec()
    spec["diversity"]["theme"] = "neon-purple"
    _, payload, code = render(spec, tmp_path)
    check("未知 theme 被拦下", code == 2 and "未知 theme" in json.dumps(payload, ensure_ascii=False), str(payload)[:160])

    spec = minimal_spec()
    spec["diversity"]["style"] = "brutalist"
    _, payload, code = render(spec, tmp_path)
    check("未知 style 被拦下", code == 2 and "未知 style" in json.dumps(payload, ensure_ascii=False), str(payload)[:160])


def test_evidence_and_level_gates(tmp_path: Path) -> None:
    spec = minimal_spec()
    spec["findings"][0].pop("evidence_ids")
    problems = da_report.validate(spec)
    check("findings 缺 evidence_ids 被拦", any("evidence_ids" in item for item in problems), str(problems)[:160])

    spec = minimal_spec()
    spec["conclusions"][0].pop("evidence_ids")
    problems = da_report.validate(spec)
    check("conclusions 缺 evidence_ids 被拦", any("conclusions" in item for item in problems), str(problems)[:160])

    spec = minimal_spec()
    spec["findings"][0]["level"] = "L9"
    problems = da_report.validate(spec)
    check("未知 level 被拦", any("level" in item for item in problems), str(problems)[:160])

    spec = minimal_spec()
    spec["findings"] = []
    problems = da_report.validate(spec)
    check("findings 为空被拦", any("findings" in item for item in problems), str(problems)[:160])


def test_placeholder_and_degraded_gates(tmp_path: Path) -> None:
    spec = minimal_spec()
    spec["background"]["narrative"] = "这段数据待补"
    problems = da_report.validate(spec)
    check("占位词被拦", any("占位词" in item for item in problems), str(problems)[:160])

    spec = minimal_spec()
    spec["meta"]["degraded"] = {"read": "订单表"}
    problems = da_report.validate(spec)
    check("degraded 缺字段被拦", any("degraded" in item for item in problems), str(problems)[:160])

    spec = minimal_spec()
    spec["meta"]["degraded"] = {"read": "订单表", "unread": "支付日志", "reason": "字段缺失"}
    markup, payload, code = render(spec, tmp_path)
    check("合法 degraded 渲染出可见标志", code == 0 and "degraded" in markup.lower())


def test_marker_out_of_range(tmp_path: Path) -> None:
    spec = minimal_spec()
    spec["analysis"][0]["charts"][0]["marker"] = {"index": 99, "label": "越界"}
    problems = da_report.validate(spec)
    check("marker.index 越界被拦", any("marker.index" in item for item in problems), str(problems)[:160])

    spec["analysis"][0]["charts"][0]["marker"] = {"index": 1, "label": "合规"}
    problems = da_report.validate(spec)
    check("marker.index 合法放行", problems == [], str(problems)[:160])


def test_unknown_chart_type(tmp_path: Path) -> None:
    spec = minimal_spec()
    spec["analysis"][0]["charts"] = [{"type": "pie3d", "title": "三维饼图", "data": []}]
    problems = da_report.validate(spec)
    check("未知图表类型被拦", any("图表类型" in item for item in problems), str(problems)[:160])


def test_escapes_injected_markup(tmp_path: Path) -> None:
    payload_text = '<script>alert("xss")</script>'
    spec = minimal_spec()
    spec["meta"]["title"] = payload_text
    spec["findings"][0]["title"] = payload_text
    spec["findings"][0]["body"] = '<img src=x onerror="alert(1)">'
    spec["data_overview"]["table"]["rows"] = [{"k": payload_text, "v": 1}]
    markup, _, code = render(spec, tmp_path)
    check("注入用例仍能渲染", code == 0)
    check("script 标签被转义", "<script>alert" not in markup and "&lt;script&gt;" in markup)
    check("onerror 属性被转义", "onerror=" not in markup.split("</style>")[-1].replace("&quot;", "") or "&lt;img" in markup)


def test_no_value_distorting_animation(tmp_path: Path) -> None:
    markup, _, _ = render(minimal_spec(), tmp_path)
    check("KPI 无 count-up 数据属性", "data-count" not in markup)
    check("条形无生长动画类", 'class="grow"' not in markup and "grow-r" not in markup)
    check("折线无 draw-in 动画类", 'class="draw"' not in markup)
    check("无 scaleX 关键帧", "keyframes grow" not in markup)
    check("无 stroke-dashoffset 关键帧", "keyframes draw" not in markup)
    check("无 requestAnimationFrame 改数字", "requestAnimationFrame" not in markup)
    check("保留不改变几何的滚动显现兜底", "setTimeout(showAll" in markup)
    check("打印时强制显示", "@media print" in markup)


def test_all_themes_render_distinctly(tmp_path: Path) -> None:
    outputs = {}
    for theme in sorted(da_report.THEMES):
        spec = minimal_spec()
        spec["diversity"]["theme"] = theme
        markup, payload, code = render(spec, tmp_path)
        check(f"主题 {theme} 渲染成功", code == 0 and payload.get("external_requests") == [], str(payload)[:120])
        outputs[theme] = markup
    check("不同主题产出不同样式", len(set(outputs.values())) == len(outputs), f"{len(set(outputs.values()))}/{len(outputs)}")


def test_bars_share_origin_and_encode_direction(tmp_path: Path) -> None:
    """同号（全正/全负）必须共用左端起笔、向右生长；只有正负混合才用居中零线。

    回归点：全负曾把零线放右端、条形向左长，渲染成「右端齐平、左端参差」，
    与「降幅越大条越长」的读图直觉相反（用户实测反馈）。
    """
    import re

    label_w, value_w, view_w = 150, 92, 720
    track = view_w - label_w - value_w
    left_origin = label_w
    center_origin = label_w + track / 2

    def filled_rects(chart: dict) -> list[tuple[str, str]]:
        markup = da_report.svg_bars(chart, da_report.THEMES["apple-light"], False)
        return re.findall(
            r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="20" rx="6" '
            r'fill="(?!#f5f5f7)(?!#f1f2f5)[^"]+" opacity',
            markup,
        )

    neg_chart = {"data": [{"label": "A", "value": -141.2}, {"label": "B", "value": -38.6}]}
    filled = filled_rects(neg_chart)
    check("全负时两条数据条都被绘出", len(filled) == 2, str(filled))
    if len(filled) == 2:
        left_edges = [float(x) for x, _w in filled]
        check("全负时左端对齐同一起点", all(abs(edge - left_origin) < 0.6 for edge in left_edges),
              f"{left_edges} vs {left_origin}")
        widths = {round(float(w), 1) for _x, w in filled}
        check("全负时长度按 |value| 等比", round(max(widths) / min(widths), 2) == round(141.2 / 38.6, 2),
              f"{sorted(widths)}")
    check("同号图不画多余零线", "<line" not in da_report.svg_bars(neg_chart, da_report.THEMES["apple-light"], False))

    pos_filled = filled_rects({"data": [{"label": "A", "value": 50}, {"label": "B", "value": 100}]})
    check("全正时同样左端起笔", len(pos_filled) == 2 and all(abs(float(x) - left_origin) < 0.6 for x, _w in pos_filled),
          str(pos_filled))

    mixed_chart = {"data": [{"label": "A", "value": 50}, {"label": "B", "value": -100}]}
    mixed = da_report.svg_bars(mixed_chart, da_report.THEMES["apple-light"], False)
    check("有正有负时零线居中", f'x1="{center_origin:.1f}"' in mixed)
    mixed_filled = filled_rects(mixed_chart)
    check("有正有负时两条数据条都被绘出", len(mixed_filled) == 2, str(mixed_filled))
    if len(mixed_filled) == 2:
        # 正条从零线向右长，负条从零线向左长；两侧共用同一尺度（|−100| : |+50| = 2 : 1）。
        anchored = all(
            abs((float(x) - center_origin) if float(x) >= center_origin - 0.6
                else (float(x) + float(w) - center_origin)) < 0.6
            for x, w in mixed_filled
        )
        lengths = sorted(float(w) for _x, w in mixed_filled)
        check("有正有负时条形都以零线为锚点", anchored, str(mixed_filled))
        check("有正有负时两侧共用同一尺度", round(lengths[1] / lengths[0], 2) == 2.0, str(lengths))


def bar_color(accent: str, surface: str, alpha: float) -> tuple[int, int, int]:
    fr, fg, fb = da_report._hex_to_rgb(accent)
    br, bg, bb = da_report._hex_to_rgb(surface)
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in ((fr, br), (fg, bg), (fb, bb)))


def contrast_ratio(text_color: str, background_rgb: tuple[int, int, int]) -> float:
    """WCAG 对比度：文字色 vs 实际底色。"""
    light, dark = da_report._relative_luminance(da_report._hex_to_rgb(text_color)), da_report._relative_luminance(background_rgb)
    high, low = max(light, dark), min(light, dark)
    return (high + 0.05) / (low + 0.05)


def test_funnel_label_contrast(tmp_path: Path) -> None:
    """漏斗阶段标签曾写死白字：4 段以上、或暗色主题的亮强调色，都会变成不可读。

    规则：条内文字必须真的达到 4.5:1，达不到就把数值移到条外；每段的数值只能画一次。
    """
    import re

    stages = [{"label": f"阶段{i}", "value": 1000 - i * 120} for i in range(5)]
    shown = {da_report.fmt_number(stage["value"]): index for index, stage in enumerate(stages)}

    for theme_name in ("apple-light", "apple-graphite", "apple-dark"):
        theme = da_report.THEMES[theme_name]
        svg = da_report.svg_funnel({"data": stages, "title": "漏斗"}, theme, False)
        inline = re.findall(r'class="svg-value-in" style="fill:(#\w{6})">([^<]+)</text>', svg)
        outside = re.findall(r'class="svg-value">([^<]+)</text>', svg)
        check(f"{theme_name} 每段数值恰好画一次", len(inline) + len(outside) == len(stages),
              f"条内 {len(inline)} + 条外 {len(outside)}")

        worst = 99.0
        for fill, text in inline:
            index = shown[text.strip()]
            alpha = max(0.34, 1 - index * 0.18)
            worst = min(worst, contrast_ratio(fill, bar_color(da_report.chart_color(theme), theme["surface"], alpha)))
        if inline:
            check(f"{theme_name} 条内文字对比度 >= 4.5", worst >= 4.5, f"最差 {worst:.2f}")

        if theme_name == "apple-dark":
            # 亮蓝强调色上白字/墨字都不达标，必须有阶段退到条外
            check("apple-dark 漏斗部分阶段改为条外标注", 0 < len(outside) < len(stages),
                  f"条内 {len(inline)} 条外 {len(outside)}")


def test_number_formatting_consistent(tmp_path: Path) -> None:
    """880 与 880.0 必须渲染成同一个字符串；整数不能带出 ".0"。"""
    check("int 与 float 同形", da_report.fmt_number(880) == da_report.fmt_number(880.0) == "880",
          f"{da_report.fmt_number(880)!r} / {da_report.fmt_number(880.0)!r}")
    check("92.0 不带小数尾巴", da_report.fmt_number(92.0) == "92", da_report.fmt_number(92.0))
    check("千分位保留", da_report.fmt_number(1000.0) == "1,000", da_report.fmt_number(1000.0))
    check("真小数保留", da_report.fmt_number(789.2) == "789.2" and da_report.fmt_number(7.5) == "7.5")
    check("负零不写成 -0", da_report.fmt_number(-0.0) == "0", da_report.fmt_number(-0.0))
    check("None 不写成 0", da_report.fmt_number(None) == "—")


def test_matrix_text_contrast_adapts(tmp_path: Path) -> None:
    theme = da_report.THEMES["apple-light"]
    dark = da_report._text_on(theme["accent"], theme["surface"], 0.95, theme["ink"])
    light = da_report._text_on(theme["accent"], theme["surface"], 0.09, theme["ink"])
    check("深底色上用白字", dark == "#ffffff", dark)
    check("浅底色上用墨色字", light == theme["ink"], light)
    spec = minimal_spec()
    markup, _, _ = render(spec, tmp_path)
    check("矩阵单元内联对比度颜色", 'class="svg-value-in" style="fill:' in markup)


def test_data_color_separable_from_ui_accent(tmp_path: Path) -> None:
    """主题可把图表数据色与 UI 强调色拆开；缺省时两者一致。"""
    theme = dict(da_report.THEMES["apple-light"])  # 该主题未设 data / matrix_data
    check("缺省时数据色等于 UI 强调色", da_report.chart_color(theme) == theme["accent"], da_report.chart_color(theme))
    check("缺省时矩阵色跟随数据色", da_report.matrix_color(theme) == theme["accent"])

    theme["data"] = "#b45309"  # 故意选一个与该主题 accent 不同的颜色
    check("设置 data 后数据色改用它", da_report.chart_color(theme) == "#b45309")
    check("矩阵色跟随 data", da_report.matrix_color(theme) == "#b45309")

    theme["matrix_data"] = "#0a5bbd"
    check("matrix_data 可单独覆盖，且不影响其他图表",
          da_report.matrix_color(theme) == "#0a5bbd" and da_report.chart_color(theme) == "#b45309")

    line = da_report.svg_line({"data": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]}, theme, False)
    check("折线用数据色而非 UI 强调色", "#b45309" in line and theme["accent"] not in line)
    matrix = da_report.svg_matrix({"rows": ["r"], "columns": ["c"], "cells": {"r|c": 5}}, theme, False)
    check("矩阵用 matrix_data", "#0a5bbd" in matrix)

    graphite = da_report.THEMES["apple-graphite"]
    check("graphite 数据色为 Apple 蓝", da_report.chart_color(graphite) == "#0071e3", da_report.chart_color(graphite))
    check("graphite 矩阵跟随数据色", da_report.matrix_color(graphite) == "#0071e3", da_report.matrix_color(graphite))
    check("graphite UI 强调色仍是墨色", graphite["accent"] == "#1d1d1f", graphite["accent"])
    spec = minimal_spec()
    spec["diversity"] = {"theme": "apple-graphite", "style": "apple", "density": 4}
    markup, _, code = render(spec, tmp_path)
    check("graphite 渲染成功", code == 0)
    for chart_title in ("趋势", "漏斗", "矩阵"):
        block = next(part for part in markup.split("<figure") if chart_title in part)
        check(f"graphite「{chart_title}」图用蓝色数据", "#0071e3" in block, chart_title)
    # 贡献图的值本身是负的，走语义红（跌）而不是数据色；这是有意的
    bars = next(part for part in markup.split("<figure") if "贡献" in part)
    check("graphite「贡献」图用语义跌色而非数据蓝", "#b3261e" in bars and "#0071e3" not in bars)


def test_default_theme_is_graphite(tmp_path: Path) -> None:
    check("默认主题为 apple-graphite", da_report.DEFAULT_THEME == "apple-graphite", da_report.DEFAULT_THEME)
    spec = minimal_spec()
    spec["diversity"] = {"style": "apple", "density": 4}  # 不给 theme，走默认
    markup, payload, code = render(spec, tmp_path)
    check("省略 theme 时用 graphite 渲染", code == 0 and da_report.THEMES["apple-graphite"]["ink"] in markup)
    spec["diversity"] = {}
    check("空 diversity 走默认主题", "#1d1d1f" in render(spec, tmp_path)[0])


def test_emit_example_round_trips(tmp_path: Path) -> None:
    example_path = tmp_path / "example.json"
    out_path = tmp_path / "example.html"
    completed = subprocess.run(
        [sys.executable, str(REPORT), "--spec", str(example_path), "--out", str(out_path)],
        capture_output=True, text=True,
    )
    check("示例规格不存在时报错而不是写坏文件", completed.returncode == 2 and not out_path.exists(),
          f"exit={completed.returncode}")

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(minimal_spec(), ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, str(REPORT), "--spec", str(spec_path), "--out", str(out_path),
                    "--emit-example", str(example_path)], capture_output=True, text=True)
    emitted = json.loads(example_path.read_text(encoding="utf-8"))
    check("--emit-example 写出可校验的示例", da_report.validate(emitted) == [], str(da_report.validate(emitted))[:160])


def test_baseline_label_avoids_value_label(tmp_path: Path) -> None:
    """末点数值与基线同高时，基线标签不能继续钉在右端，否则和数值标签叠字。"""
    theme = da_report.THEMES["apple-graphite"]
    collision = {"type": "line", "title": "支付率", "baseline": 91.93,
                 "data": [{"label": "6/1", "value": 92.16}, {"label": "6/9", "value": 77.62},
                          {"label": "6/15", "value": 91.5}, {"label": "6/29", "value": 91.57}]}
    svg = da_report.svg_line(collision, theme, False)
    base_tag = [seg for seg in svg.split("<text") if "基线" in seg][0]
    check("末点与基线靠近时基线标签不再贴右端", 'text-anchor="end"' not in base_tag, base_tag[:160])
    far = {"type": "line", "title": "趋势", "baseline": 1000,
           "data": [{"label": "1月", "value": 500}, {"label": "2月", "value": 700}, {"label": "3月", "value": 900}]}
    far_tag = [seg for seg in da_report.svg_line(far, theme, False).split("<text") if "基线" in seg][0]
    check("末点远离基线时基线标签仍贴右端", 'text-anchor="end"' in far_tag, far_tag[:160])
    # 基线落在数据范围之外时，纵向定义域要把它包进来，不能画到画布外
    outside = {"type": "line", "title": "越界基线", "baseline": 1500,
               "data": [{"label": "1月", "value": 500}, {"label": "2月", "value": 700}, {"label": "3月", "value": 900}]}
    outside_tag = [seg for seg in da_report.svg_line(outside, theme, False).split("<text") if "基线" in seg][0]
    y_token = outside_tag.split('y="')[1].split('"')[0]
    check("基线超出数据范围时标签仍在画布内", float(y_token) > 0, f"y={y_token}")
    markup = da_report.render_report(minimal_spec())
    check("图表标注带底色描边光晕", "paint-order:stroke fill" in markup)


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        for suite in (
            test_renders_full_skeleton,
            test_unknown_theme_and_style_rejected,
            test_evidence_and_level_gates,
            test_placeholder_and_degraded_gates,
            test_marker_out_of_range,
            test_unknown_chart_type,
            test_escapes_injected_markup,
            test_no_value_distorting_animation,
            test_all_themes_render_distinctly,
            test_bars_share_origin_and_encode_direction,
            test_funnel_label_contrast,
            test_matrix_text_contrast_adapts,
            test_number_formatting_consistent,
            test_data_color_separable_from_ui_accent,
            test_default_theme_is_graphite,
            test_emit_example_round_trips,
            test_baseline_label_avoids_value_label,
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
