#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把分析结论渲染成一份自包含的离线 HTML 报告。

分工
----
洞察由模型产出（那是它擅长的），本脚本负责排版、图表和动效。
模型只需要写一份**紧凑的报告规格 JSON**（字段见 references/report-design.md），
不必逐字手写 HTML —— 手写一份带图表的报告约 8,000 token，而且版式每次都会漂移。

设计系统内置在脚本里，因此它是**被强制的**，不是靠模型自觉：
- 两套风格档案：`apple`（大留白、SF 字体栈、克制的分隔线）与 `editorial`（紧凑编辑部风）；
- 配色只允许「中性底 + 单一强调色 + 仅数据可用的正负色」，禁止纯黑、霓虹渐变；
- 数字一律 tabular-nums，表格或高密度版式用等宽；
- 图表是纯 SVG：细描边、极淡刻度、直接标注代替图例；
- 动效只做进场；命中 prefers-reduced-motion 或禁用 JS 时静态完整可读；
- 零外部请求：不引 CDN、不引字体、不发起任何网络访问。

用法
----
    python scripts/da_report.py --spec report_spec.json --out report.html
    python scripts/da_report.py --spec s.json --out r.html --emit-example example_spec.json

退出码：0 = 渲染成功；2 = 规格不合法（列出缺哪个字段）。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from da_envcheck import ensure_dependencies  # noqa: E402

ensure_dependencies()

from da_common import write_json  # noqa: E402

SECTIONS = ("核心发现", "分析背景与目标", "数据概况", "深入分析", "结论与建议", "附录")
DEFAULT_THEME = "apple-graphite"

# 每套主题：中性底 + 单一强调色 + 仅用于数据的正负色。禁止纯黑与霓虹渐变。
THEMES: dict[str, dict[str, str]] = {
    # 苹果产品页：白底、近黑文字、系统灰、单一蓝色强调
    "apple-light": {
        "bg": "#ffffff", "surface": "#ffffff", "surface_alt": "#f5f5f7", "border": "#d2d2d7",
        "ink": "#1d1d1f", "ink_soft": "#424245", "muted": "#86868b",
        "accent": "#0071e3", "accent_soft": "#f0f7ff", "pos": "#00875a", "neg": "#d70015",
    },
    # 苹果编辑部／财报：UI 骨架墨色（标题、卡片、分隔线都近黑），颜色整体让给数据
    "apple-graphite": {
        "bg": "#fbfbfd", "surface": "#ffffff", "surface_alt": "#f5f5f7", "border": "#d2d2d7",
        "ink": "#1d1d1f", "ink_soft": "#424245", "muted": "#86868b",
        "accent": "#1d1d1f", "accent_soft": "#f5f5f7", "pos": "#00695c", "neg": "#b3261e",
        # 折线/条形/漏斗/矩阵统一用 Apple 蓝；矩阵缺省跟随 data，无需单列
        "data": "#0071e3",
    },
    # 暗色模式：纯黑底 + 提亮强调色
    "apple-dark": {
        "bg": "#000000", "surface": "#1c1c1e", "surface_alt": "#2c2c2e", "border": "#3a3a3c",
        "ink": "#f5f5f7", "ink_soft": "#d2d2d7", "muted": "#98989d",
        "accent": "#2997ff", "accent_soft": "#0a2540", "pos": "#30d158", "neg": "#ff453a",
    },
    "slate-amber": {
        "bg": "#f7f8fa", "surface": "#ffffff", "surface_alt": "#f1f2f5", "border": "#e3e5ea",
        "ink": "#14161a", "ink_soft": "#454a54", "muted": "#787f8c",
        "accent": "#b45309", "accent_soft": "#fdf3e7", "pos": "#0f766e", "neg": "#b91c1c",
    },
    "zinc-emerald": {
        "bg": "#fafaf9", "surface": "#ffffff", "surface_alt": "#f4f4f2", "border": "#e4e4e1",
        "ink": "#18181b", "ink_soft": "#4b4b52", "muted": "#7c7c85",
        "accent": "#047857", "accent_soft": "#ecfdf5", "pos": "#047857", "neg": "#b45309",
    },
}

# 风格档案：字号阶梯、留白、圆角、卡片处理。apple 档参考系统排版节奏。
STYLE_PROFILES: dict[str, dict[str, Any]] = {
    "apple": {
        "base_size": "17px", "leading": "1.47", "measure": "68ch",
        "pad_x": "28px", "pad_y": "72px", "section_gap": "72px", "block_gap": "22px",
        "h1": "clamp(2.1rem,5vw,3.1rem)", "h2": "clamp(1.5rem,3.2vw,2.1rem)", "h3": "1.1875rem",
        "radius": "18px", "radius_sm": "12px",
        "card_bg": "surface-alt", "card_border": "transparent", "card_pad": "26px 28px",
        "kpi_value": "clamp(1.75rem,3.6vw,2.4rem)", "chip_radius": "980px",
        "tracking": "-0.022em", "max_width": "1040px",
    },
    "editorial": {
        "base_size": "16px", "leading": "1.78", "measure": "72ch",
        "pad_x": "40px", "pad_y": "56px", "section_gap": "48px", "block_gap": "30px",
        "h1": "clamp(1.75rem,3.4vw,2.5rem)", "h2": "clamp(1.2rem,2vw,1.5rem)", "h3": "1.02rem",
        "radius": "6px", "radius_sm": "6px",
        "card_bg": "surface", "card_border": "border", "card_pad": "16px 20px",
        "kpi_value": "1.5rem", "chip_radius": "999px",
        "tracking": "-0.02em", "max_width": "1180px",
    },
}

TONES = {
    "neutral": ("border", "surface"),
    "positive": ("pos", "surface"),
    "negative": ("neg", "surface"),
    "caution": ("accent", "accent_soft"),
    "accent": ("accent", "accent_soft"),
}
LEVEL_LABEL = {
    "L0": "L0 事实", "L1": "L1 比较", "L2": "L2 解释", "L3": "L3 决策含义", "L4": "L4 行动建议",
}


# --------------------------------------------------------------------- 基础工具


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_number(value: Any) -> str:
    """数据展示统一走这里：千分位、最多两位小数，不把 None 渲染成 0。"""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "—"
        if value == 0:  # 避免 -0.0 渲染成 "-0"
            return "0"
        if abs(value) >= 1000:
            return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
        if value.is_integer():
            # 注意 f"{880.0:,}" 会得到 "880.0"；整数要显式按 0 位小数格式化
            return f"{value:,.0f}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return esc(value)


def fmt_value(item: dict) -> str:
    """带单位数值：percent 走百分号，pp 写『个百分点』。"""
    raw = item.get("value")
    unit = str(item.get("unit") or "")
    if raw is None:
        return "—"
    if unit == "percent":
        try:
            return f"{float(raw):,.1f}%"
        except (TypeError, ValueError):
            return esc(raw)
    if unit == "pp":
        return f"{fmt_number(raw)} 个百分点"
    if unit:
        return f"{fmt_number(raw)} {esc(unit)}"
    return fmt_number(raw)


def _axis_scale(low: float, high: float, size: float, invert: bool = False) -> Any:
    span = (high - low) or 1.0

    def convert(value: float) -> float:
        ratio = (value - low) / span
        return size - ratio * size if invert else ratio * size

    return convert


# --------------------------------------------------------------------- SVG 图表


def svg_line(chart: dict, theme: dict, animate: bool) -> str:
    points = [item for item in chart.get("data", []) if isinstance(item, dict)]
    if len(points) < 2:
        return '<p class="empty">数据点不足，不做折线。</p>'
    width, height = 720, 230
    pad_l, pad_r, pad_t, pad_b = 52, 16, 18, 32
    values = [float(item.get("value") or 0) for item in points]
    low, high = min(values), max(values)
    # 基线要参与纵向定义域，否则基线落在数据范围之外时会被画到画布外。
    base_value = None
    if chart.get("baseline") is not None:
        try:
            base_value = float(chart["baseline"])
            low, high = min(low, base_value), max(high, base_value)
        except (TypeError, ValueError):
            base_value = None
    if low == high:
        low, high = low - 1, high + 1
    span = high - low
    low, high = low - span * 0.14, high + span * 0.14
    xs = _axis_scale(0, len(points) - 1, width - pad_l - pad_r)
    ys = _axis_scale(low, high, height - pad_t - pad_b, invert=True)
    coords = [(pad_l + xs(index), pad_t + ys(value)) for index, value in enumerate(values)]
    line = " ".join(("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}" for index, (x, y) in enumerate(coords))
    area = f"{line} L{coords[-1][0]:.1f},{height - pad_b:.1f} L{coords[0][0]:.1f},{height - pad_b:.1f} Z"

    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(chart.get("title", "折线图"))}">'
    ]
    # 三档极淡刻度：给数字一个参照，但不成网格噪音
    for tick in range(3):
        tick_value = low + (high - low) * tick / 2
        tick_y = pad_t + ys(tick_value)
        parts.append(
            f'<line x1="{pad_l}" y1="{tick_y:.1f}" x2="{width - pad_r}" y2="{tick_y:.1f}" '
            f'stroke="{theme["border"]}" stroke-width="1" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{pad_l - 10}" y="{tick_y + 4:.1f}" text-anchor="end" class="svg-axis">'
            f'{fmt_number(round(tick_value))}</text>'
        )
    parts.append(
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}" '
        f'stroke="{theme["border"]}" stroke-width="1"/>'
    )
    baseline = chart.get("baseline")
    if base_value is not None:
        try:
            by = pad_t + ys(base_value)
            parts.append(
                f'<line x1="{pad_l}" y1="{by:.1f}" x2="{width - pad_r}" y2="{by:.1f}" '
                f'stroke="{theme["muted"]}" stroke-width="1" stroke-dasharray="4 5"/>'
            )
            # 基线标签默认贴右；但首/末点的数值标签也在两端，若与基线同高会叠字，
            # 所以先量一下两侧标签的纵向距离，挑一个不会压字的锚点。
            label_y = by - 7
            first_label_y = coords[0][1] - 10
            last_label_y = coords[-1][1] - 10
            right_free = abs(label_y - last_label_y) >= 15
            left_free = abs(label_y - first_label_y) >= 15
            if right_free:
                bx, anchor, ty = width - pad_r, "end", label_y
            elif left_free:
                bx, anchor, ty = pad_l + 6, "start", label_y
            else:
                # 两端都被占：挪到中间并压到基线下方，避开只在点上方写的数值标签。
                bx, anchor, ty = pad_l + (width - pad_l - pad_r) / 2, "middle", min(by + 15, height - pad_b - 4)
            parts.append(
                f'<text x="{bx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" class="svg-note">'
                f'基线 {fmt_number(baseline)}</text>'
            )
        except (TypeError, ValueError):
            pass
    marker = chart.get("marker")
    if isinstance(marker, dict) and marker.get("index") is not None:
        try:
            marker_index = int(marker["index"])
        except (TypeError, ValueError):
            marker_index = -1
        if 0 <= marker_index < len(coords):
            mx, _ = coords[marker_index]
            parts.append(
                f'<line x1="{mx:.1f}" y1="{pad_t}" x2="{mx:.1f}" y2="{height - pad_b}" '
                f'stroke="{theme["neg"]}" stroke-width="1" stroke-dasharray="3 4"/>'
            )
            parts.append(
                f'<text x="{mx + 7:.1f}" y="{pad_t + 13:.1f}" class="svg-note">{esc(marker.get("label", ""))}</text>'
            )
    parts.append(
        f'<path d="{area}" fill="{chart_color(theme)}" opacity="0.06"/>'
        f'<path d="{line}" fill="none" stroke="{chart_color(theme)}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    for index, (x, y) in enumerate(coords):
        parts.append(
            f'<circle class="pop" cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{theme["bg"]}" '
            f'stroke="{chart_color(theme)}" stroke-width="1.8"/>'
        )
        if index in {0, len(coords) - 1}:
            offset = 10 if index == 0 else -10
            parts.append(
                f'<text x="{x:.1f}" y="{y + (offset if index else -offset):.1f}" '
                f'text-anchor="{"start" if index == 0 else "end"}" class="svg-value">{fmt_number(values[index])}</text>'
            )
            parts.append(
                f'<text x="{x:.1f}" y="{height - 10}" text-anchor="{"start" if index == 0 else "end"}" '
                f'class="svg-axis">{esc(points[index].get("label", ""))}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return (255, 255, 255)
    try:
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for raw in rgb:
        channel = raw / 255
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def chart_color(theme: dict) -> str:
    """图表数据色。默认与 UI 强调色相同；主题可用 data / matrix_data 单独指定。"""
    return theme.get("data") or theme["accent"]


def matrix_color(theme: dict) -> str:
    return theme.get("matrix_data") or chart_color(theme)


def _blend(fill: str, background: str, alpha: float) -> tuple[int, int, int]:
    """把半透明填充压到实际底色上，得到肉眼看到的颜色。"""
    fr, fg, fb = _hex_to_rgb(fill)
    br, bg, bb = _hex_to_rgb(background)
    return (
        round(fr * alpha + br * (1 - alpha)),
        round(fg * alpha + bg * (1 - alpha)),
        round(fb * alpha + bb * (1 - alpha)),
    )


def _contrast_ratio(text: str, background: tuple[int, int, int]) -> float:
    """WCAG 对比度；用于判断文字能否压在这个底色上。"""
    light = _relative_luminance(_hex_to_rgb(text))
    dark = _relative_luminance(background)
    high, low = max(light, dark), min(light, dark)
    return (high + 0.05) / (low + 0.05)


def _text_on(fill: str, background: str, alpha: float, ink: str) -> str:
    """在 blended 底色上取对比度更高的文字色，避免浅底白字看不清。"""
    blended = _blend(fill, background, alpha)
    luminance = _relative_luminance(blended)
    ink_luminance = _relative_luminance(_hex_to_rgb(ink))
    on_white = 1.05 / (luminance + 0.05)
    on_ink = (luminance + 0.05) / (ink_luminance + 0.05)
    return "#ffffff" if on_white >= on_ink else ink


def svg_bars(chart: dict, theme: dict, animate: bool) -> str:
    rows = [item for item in chart.get("data", []) if isinstance(item, dict)]
    if not rows:
        return '<p class="empty">没有可展示的分组数据。</p>'
    width, row_h, gap, label_w, value_w = 720, 30, 12, 150, 92
    height = len(rows) * (row_h + gap) + 10
    track = width - label_w - value_w
    values = [float(item.get("value") or 0) for item in rows]
    maximum = max(abs(value) for value in values) or 1.0
    has_positive = any(value > 0 for value in values)
    has_negative = any(value < 0 for value in values)
    mixed_signs = has_positive and has_negative
    if mixed_signs:
        # 有正有负：符号就是信息，零线居中，两侧同尺度，条长才可比。
        origin, scale = label_w + track / 2, (track / 2) / maximum
    else:
        # 同号（全正或全负）：统一左端起笔、向右生长，长度按 |value| 等比。
        # 全负若把零线放到右端让条形向左长，会变成「右端齐平、左端参差」，
        # 与「降幅越大条越长」的读图直觉相反；符号交给数值标签与语义色承担。
        origin, scale = label_w, track / maximum
    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(chart.get("title", "条形图"))}">'
    ]
    for index, item in enumerate(rows):
        value = float(item.get("value") or 0)
        y = 5 + index * (row_h + gap)
        length = max(abs(value) * scale, 3)
        bar_x = origin - length if (mixed_signs and value < 0) else origin
        # 同一语义只允许一种颜色；最大项靠不透明度加权，不靠换色。
        if item.get("tone") == "negative" or (item.get("tone") is None and value < 0):
            color = theme["neg"]
        elif item.get("tone") == "positive":
            color = theme["pos"]
        elif item.get("muted"):
            color = theme["muted"]
        else:
            color = chart_color(theme)
        weight = 1.0 if abs(value) >= maximum * 0.999 else 0.62
        parts.append(f'<text x="0" y="{y + 20}" class="svg-label">{esc(item.get("label", ""))}</text>')
        parts.append(f'<rect x="{label_w}" y="{y + 5}" width="{track}" height="{row_h - 10}" rx="6" fill="{theme["surface_alt"]}"/>')
        parts.append(
            f'<rect x="{bar_x:.1f}" y="{y + 5}" '
            f'width="{length:.1f}" height="{row_h - 10}" rx="6" fill="{color}" opacity="{weight:.2f}"/>'
        )
        parts.append(
            f'<text x="{width}" y="{y + 20}" text-anchor="end" class="svg-value">'
            f'{esc(item.get("display") or fmt_number(item.get("value")))}</text>'
        )
    # 只有正负混合时才需要零线：同号图左端即共同起点，画线反而像多了一个刻度。
    if mixed_signs:
        parts.append(
            f'<line x1="{origin:.1f}" y1="2" x2="{origin:.1f}" y2="{height - 2:.1f}" '
            f'stroke="{theme["border"]}" stroke-width="1"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_funnel(chart: dict, theme: dict, animate: bool) -> str:
    stages = [item for item in chart.get("data", []) if isinstance(item, dict)]
    if not stages:
        return '<p class="empty">没有可展示的漏斗阶段。</p>'
    width, height = 720, len(stages) * 60 + 8
    bar_x = 150
    top = float(stages[0].get("value") or 0) or 1.0
    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(chart.get("title", "漏斗图"))}">'
    ]
    for index, item in enumerate(stages):
        value = float(item.get("value") or 0)
        ratio = max(value / top, 0.03)
        bar_w = max((width - bar_x - 240) * ratio, 22)
        y = 4 + index * 60
        stage_opacity = max(0.34, 1 - index * 0.18)
        parts.append(f'<text x="0" y="{y + 25}" class="svg-label">{esc(item.get("label", ""))}</text>')
        parts.append(
            f'<rect x="{bar_x}" y="{y}" width="{bar_w:.1f}" height="36" rx="9" '
            f'fill="{chart_color(theme)}" opacity="{stage_opacity:.2f}"/>'
        )
        # 只有「条够宽」且「文字压在条上真能读」时才放条内；否则移到条外。
        # 暗色主题的强调色偏亮，白字与墨字都不达标，必须走条外分支。
        blended = _blend(chart_color(theme), theme.get("surface", "#ffffff"), stage_opacity)
        ink = _text_on(chart_color(theme), theme.get("surface", "#ffffff"), stage_opacity, theme["ink"])
        if bar_w >= 150 and _contrast_ratio(ink, blended) >= 4.5:
            parts.append(
                f'<text x="{bar_x + 14}" y="{y + 24}" class="svg-value-in" '
                f'style="fill:{ink}">{fmt_number(value)}</text>'
            )
            note_x = bar_x + bar_w + 16
        else:
            note_x = bar_x + bar_w + 16
            parts.append(f'<text x="{note_x:.1f}" y="{y + 24}" class="svg-value">{fmt_number(value)}</text>')
            note_x += 70
        if index:
            previous = float(stages[index - 1].get("value") or 0)
            rate = (value / previous * 100) if previous else None
            text = f"转化 {rate:.1f}%　流失 {fmt_number(previous - value)}" if rate is not None else ""
            parts.append(f'<text x="{note_x:.1f}" y="{y + 24}" class="svg-note">{text}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_matrix(chart: dict, theme: dict, animate: bool) -> str:
    rows, columns = chart.get("rows") or [], chart.get("columns") or []
    cells = chart.get("cells") or {}
    if not rows or not columns:
        return '<p class="empty">矩阵缺少 rows / columns。</p>'
    cell_w, cell_h, pad_l, pad_t = 100, 42, 122, 32
    width = pad_l + cell_w * len(columns)
    height = pad_t + cell_h * len(rows) + 6
    values = [float(value) for value in cells.values() if isinstance(value, (int, float))]
    low, high = (min(values), max(values)) if values else (0.0, 1.0)
    span = (high - low) or 1.0
    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(chart.get("title", "矩阵图"))}">'
    ]
    for column_index, column in enumerate(columns):
        parts.append(
            f'<text x="{pad_l + column_index * cell_w + cell_w / 2:.0f}" y="{pad_t - 11}" '
            f'text-anchor="middle" class="svg-axis">{esc(column)}</text>'
        )
    for row_index, row in enumerate(rows):
        parts.append(f'<text x="0" y="{pad_t + row_index * cell_h + 26}" class="svg-label">{esc(row)}</text>')
        for column_index, column in enumerate(columns):
            value = cells.get(f"{row}|{column}")
            x, y = pad_l + column_index * cell_w, pad_t + row_index * cell_h
            if isinstance(value, (int, float)):
                opacity = 0.09 + 0.6 * ((float(value) - low) / span)
                parts.append(
                    f'<rect x="{x + 3}" y="{y + 3}" width="{cell_w - 6}" height="{cell_h - 6}" rx="8" '
                    f'fill="{matrix_color(theme)}" opacity="{opacity:.2f}"/>'
                )
                ink = _text_on(matrix_color(theme), theme.get("surface", "#ffffff"), opacity, theme["ink"])
                parts.append(
                    f'<text x="{x + cell_w / 2:.0f}" y="{y + 26}" text-anchor="middle" class="svg-value-in" '
                    f'style="fill:{ink}">{fmt_number(value)}</text>'
                )
            else:
                parts.append(
                    f'<rect x="{x + 3}" y="{y + 3}" width="{cell_w - 6}" height="{cell_h - 6}" rx="8" '
                    f'fill="{theme["surface_alt"]}"/>'
                )
                parts.append(
                    f'<text x="{x + cell_w / 2:.0f}" y="{y + 26}" text-anchor="middle" class="svg-note">—</text>'
                )
    parts.append("</svg>")
    return "".join(parts)


CHART_BUILDERS = {"line": svg_line, "bars": svg_bars, "funnel": svg_funnel, "matrix": svg_matrix}


def render_chart(chart: dict, theme: dict, animate: bool) -> str:
    kind = str(chart.get("type") or "line")
    builder = CHART_BUILDERS.get(kind)
    body = builder(chart, theme, animate) if builder else f'<p class="empty">未知图表类型：{esc(kind)}</p>'
    # title 是「指标 + 单位」，caption 是「所以呢」。两者都写时把 title 显式排出来，
    # 否则标题只进了 SVG 的 aria-label，页面上看不到，读者得靠上下文猜这张图在画什么。
    title = str(chart.get("title") or "").strip()
    caption = str(chart.get("caption") or "").strip()
    if title and caption and title != caption:
        head = (f'<span class="chart-title">{esc(title)}</span>'
                f'<span class="chart-caption">{esc(caption)}</span>')
    else:
        head = f'<span class="chart-caption">{esc(caption or title)}</span>'
    footer = "".join(
        part for part in (
            f'<p class="chart-note">{esc(chart["note"])}</p>' if chart.get("note") else "",
            f'<p class="chart-source">来源：{esc(chart["source"])}</p>' if chart.get("source") else "",
        )
    )
    return f'<figure class="chart"><figcaption>{head}</figcaption>{body}{footer}</figure>'


# --------------------------------------------------------------------- 区块渲染


def render_table(table: dict, theme: dict) -> str:
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not columns:
        return ""
    keys = [column.get("key") if isinstance(column, dict) else column for column in columns]
    numeric = set(table.get("numeric_columns") or [])
    head = "".join(
        f'<th class="{"num" if key in numeric else ""}">'
        f'{esc(column.get("label", column.get("key", "")) if isinstance(column, dict) else column)}</th>'
        for key, column in zip(keys, columns)
    )
    body = []
    for row in rows:
        cells = []
        for key in keys:
            value = row.get(key) if isinstance(row, dict) else None
            rendered = fmt_number(value) if key in numeric else esc(value if value not in (None, "") else "—")
            cells.append(f'<td class="{"num" if key in numeric else ""}">{rendered}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    caption = f'<caption>{esc(table.get("title"))}</caption>' if table.get("title") else ""
    return f'<table class="data">{caption}<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def render_finding(item: dict, theme: dict) -> str:
    tone = str(item.get("tone") or "neutral")
    edge_key, _ = TONES.get(tone, TONES["neutral"])
    edge = theme.get(edge_key, theme["border"])
    chips = "".join(f'<span class="chip">证据 {esc(value)}</span>' for value in item.get("evidence_ids") or [])
    level = LEVEL_LABEL.get(str(item.get("level") or "").upper())
    if level:
        chips += f'<span class="chip chip-level">{esc(level)}</span>'
    for value in item.get("limitations") or []:
        chips += f'<span class="chip chip-limit">限制：{esc(value)}</span>'
    return (
        f'<article class="finding">'
        f'<span class="rule" style="background:{edge}"></span>'
        f'<h3>{esc(item.get("title", ""))}</h3>'
        f'<p class="finding-body">{esc(item.get("body", ""))}</p>'
        f'<div class="chips">{chips}</div>'
        "</article>"
    )


def render_kpis(items: list[dict]) -> str:
    cards = []
    for item in items:
        direction = str(item.get("direction") or "")
        arrow = {"up": "▲", "down": "▼"}.get(direction, "")
        tone = "flat"
        if direction == "up":
            tone = "pos" if not item.get("good_when_down") else "neg"
        elif direction == "down":
            tone = "neg" if not item.get("good_when_down") else "pos"
        cards.append(
            '<div class="kpi">'
            f'<span class="kpi-label">{esc(item.get("label", ""))}</span>'
            f'<span class="kpi-value">{fmt_value(item)}</span>'
            + (f'<span class="kpi-delta {tone}">{arrow} {esc(item.get("delta", ""))}</span>' if item.get("delta") else "")
            + "</div>"
        )
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def render_section(index: int, title: str, body: str) -> str:
    return f'<section class="block" id="s{index}"><h2>{esc(title)}</h2>{body}</section>'


def render_report(spec: dict) -> str:
    meta = spec.get("meta") or {}
    diversity = spec.get("diversity") or {}
    theme = THEMES.get(str(diversity.get("theme") or DEFAULT_THEME), THEMES[DEFAULT_THEME])
    profile = STYLE_PROFILES.get(str(diversity.get("style") or "apple"), STYLE_PROFILES["apple"])
    motion = str(diversity.get("motion") or "restrained")
    animate = motion != "none"
    compact = int(diversity.get("density") or 4) >= 7

    findings = "".join(render_finding(item, theme) for item in spec.get("findings") or [])
    if spec.get("kpis"):
        findings = render_kpis(spec["kpis"]) + findings
    overview = spec.get("data_overview") or {}
    overview_html = "".join(
        part for part in (
            f'<p>{esc(overview["narrative"])}</p>' if overview.get("narrative") else "",
            render_table(overview["table"], theme) if overview.get("table") else "",
            "".join(f'<p class="aside">{esc(note)}</p>' for note in overview.get("notes") or []),
        )
    )
    analysis_html = []
    for block in spec.get("analysis") or []:
        inner = [f'<h3>{esc(block.get("heading", ""))}</h3>']
        if block.get("narrative"):
            inner.append(f'<p>{esc(block["narrative"])}</p>')
        inner.extend(render_chart(chart, theme, animate) for chart in block.get("charts") or [])
        inner.extend(render_table(table, theme) for table in block.get("tables") or [])
        analysis_html.append(f'<div class="analysis-block">{"".join(inner)}</div>')
    conclusions = "".join(
        '<li class="conclusion">'
        f'<span class="conclusion-text">{esc(item.get("text", ""))}</span>'
        + "".join(f'<span class="chip">证据 {esc(value)}</span>' for value in item.get("evidence_ids") or [])
        + "</li>"
        for item in spec.get("conclusions") or []
    )
    steps = "".join(
        '<li class="step">'
        f'<span class="step-q">{esc(item.get("question", ""))}</span>'
        + (f'<span class="step-need">需要：{esc(item.get("data_needed", ""))}</span>' if item.get("data_needed") else "")
        + "</li>"
        for item in spec.get("next_steps") or []
    )
    appendix = spec.get("appendix") or {}
    appendix_html = "".join(render_table(table, theme) for table in appendix.get("tables") or [])
    appendix_html += "".join(f'<p class="aside">{esc(note)}</p>' for note in appendix.get("notes") or [])

    degraded = meta.get("degraded") or {}
    banner = ""
    if degraded.get("active"):
        banner = (
            '<div class="degraded" role="status"><strong>DEGRADED</strong>'
            f'<span class="deg-reason">{esc(degraded.get("reason", ""))}</span>'
            f'<span class="deg-scope">已读：{esc(degraded.get("read", "—"))}　未读：{esc(degraded.get("unread", "—"))}</span></div>'
        )
    quality = meta.get("quality") or {}
    quality_chip = (
        f'<span class="chip chip-warn">数据质量需复核：{esc(quality.get("note", ""))}</span>'
        if quality.get("flag") == "review" else ""
    )
    header = (
        '<header class="masthead">'
        f'<p class="eyebrow">{esc(meta.get("decision") or "决策复盘")}</p>'
        f'<h1>{esc(meta.get("title", "分析报告"))}</h1>'
        + (f'<p class="subtitle">{esc(meta["subtitle"])}</p>' if meta.get("subtitle") else "")
        + '<div class="meta-row">'
        + f'<span class="meta-item"><b>观察窗</b>{esc(meta.get("window", "—"))}</span>'
        + f'<span class="meta-item"><b>来源</b>{esc(meta.get("source", "—"))}</span>'
        + '<span class="meta-item"><b>结论分级</b>L0–L4</span>'
        + quality_chip
        + "</div></header>"
    )
    nav = '<nav class="toc">' + "".join(
        f'<a href="#s{index + 1}">{esc(title)}</a>' for index, title in enumerate(SECTIONS)
    ) + "</nav>"
    blocks = "".join((
        render_section(1, SECTIONS[0], findings),
        render_section(2, SECTIONS[1], f'<p>{esc((spec.get("background") or {}).get("narrative", ""))}</p>'
                       if (spec.get("background") or {}).get("narrative") else ""),
        render_section(3, SECTIONS[2], overview_html),
        render_section(4, SECTIONS[3], "".join(analysis_html)),
        render_section(5, SECTIONS[4], f'<ul class="conclusions">{conclusions}</ul>'
                       + (f'<h3 class="steps-title">后续分析建议</h3><ul class="steps">{steps}</ul>' if steps else "")),
        render_section(6, SECTIONS[5], appendix_html),
    ))
    return HTML_TEMPLATE.format(
        lang="zh-CN",
        title=esc(meta.get("title", "分析报告")),
        css=build_css(theme, profile, animate, compact),
        banner=banner,
        header=header,
        nav=nav,
        blocks=blocks,
        generated=esc(str(meta.get("generated", ""))),
        script=JS if animate else "",
    )


def build_css(theme: dict, profile: dict, animate: bool, compact: bool) -> str:
    gap = "40px" if compact else profile["section_gap"]
    return f"""
:root {{
  --bg:{theme['bg']}; --surface:{theme['surface']}; --surface-alt:{theme['surface_alt']};
  --border:{theme['border']}; --ink:{theme['ink']}; --ink-soft:{theme['ink_soft']};
  --muted:{theme['muted']}; --accent:{theme['accent']}; --accent-soft:{theme['accent_soft']};
  --pos:{theme['pos']}; --neg:{theme['neg']};
  --radius:{profile['radius']}; --radius-sm:{profile['radius_sm']};
  --measure:{profile['measure']}; --gap:{gap};
}}
* {{ box-sizing:border-box; }}
html {{ background:var(--bg); }}
body {{
  margin:0 auto; max-width:{profile['max_width']}; padding:{profile['pad_y']} {profile['pad_x']} 96px;
  background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:{profile['base_size']}; line-height:{profile['leading']}; letter-spacing:{profile['tracking']};
  -webkit-font-smoothing:antialiased; font-variant-numeric:tabular-nums;
}}
h1,h2,h3 {{ margin:0; font-weight:600; text-wrap:balance; }}
h1 {{ font-size:{profile['h1']}; line-height:1.08; letter-spacing:-0.031em; }}
h2 {{ font-size:{profile['h2']}; line-height:1.14; letter-spacing:-0.026em; }}
h3 {{ font-size:{profile['h3']}; line-height:1.3; letter-spacing:-0.01em; }}
p {{ margin:{'8px' if compact else '14px'} 0; max-width:var(--measure); color:var(--ink-soft); text-wrap:pretty; }}
b {{ color:var(--ink); font-weight:600; }}
.masthead {{ padding-bottom:26px; border-bottom:1px solid var(--border); }}
.eyebrow {{ margin:0 0 12px; font-size:.82rem; letter-spacing:.01em; color:var(--muted); font-weight:500; }}
.subtitle {{ margin:16px 0 0; font-size:1.22rem; line-height:1.42; color:var(--ink-soft); max-width:62ch; }}
.meta-row {{ display:flex; flex-wrap:wrap; gap:8px 34px; margin-top:26px; align-items:center; }}
.meta-item {{ font-size:.86rem; color:var(--ink-soft); }}
.meta-item b {{ display:block; font-size:.72rem; letter-spacing:.04em; color:var(--muted); font-weight:500; }}
.degraded {{ margin:22px 0 0; padding:16px 20px; border-radius:var(--radius-sm); background:var(--surface-alt);
  border:1px solid var(--border); font-size:.88rem; color:var(--ink-soft); display:flex; flex-wrap:wrap; gap:8px 20px; align-items:baseline; }}
.degraded strong {{ color:var(--neg); font-size:.76rem; letter-spacing:.1em; }}
.deg-reason {{ color:var(--ink); }}
.toc {{ display:flex; flex-wrap:wrap; gap:22px; padding:14px 0; border-bottom:1px solid var(--border);
  font-size:.84rem; position:sticky; top:0; background:color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter:saturate(180%) blur(20px); z-index:5; }}
.toc a {{ color:var(--muted); text-decoration:none; transition:color .2s ease; }}
.toc a:hover {{ color:var(--ink); }}
.block {{ padding-top:var(--gap); }}
.block + .block {{ border-top:1px solid var(--border); }}
.block h2 {{ margin-bottom:{'14px' if compact else '24px'}; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin-bottom:{'20px' if compact else '30px'}; }}
.kpi {{ background:var(--surface-alt); border-radius:var(--radius); padding:22px 24px; }}
.kpi-label {{ display:block; font-size:.8rem; color:var(--muted); }}
.kpi-value {{ display:block; font-size:{profile['kpi_value']}; font-weight:600; letter-spacing:-0.024em; margin-top:8px; }}
.kpi-delta {{ display:inline-block; margin-top:8px; font-size:.84rem; color:var(--muted); }}
.kpi-delta.pos {{ color:var(--pos); }}
.kpi-delta.neg {{ color:var(--neg); }}
.finding {{ position:relative; background:{theme['surface_alt'] if profile['card_bg'] == 'surface-alt' else theme['surface']};
  border:1px solid {'transparent' if profile['card_border'] == 'transparent' else theme['border']};
  border-radius:var(--radius); padding:{profile['card_pad']}; margin-bottom:12px; overflow:hidden; }}
.finding .rule {{ position:absolute; left:0; top:0; bottom:0; width:3px; }}
.finding h3 {{ margin-bottom:8px; }}
.finding-body {{ margin:0; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }}
.chip {{ font-size:.76rem; padding:4px 11px; border-radius:{profile['chip_radius']}; color:var(--muted); background:var(--surface); }}
.finding .chip {{ background:color-mix(in srgb, var(--surface) 70%, transparent); }}
.chip-level {{ color:var(--accent); }}
.chip-limit {{ color:var(--ink-soft); }}
.chip-warn {{ color:var(--neg); background:transparent; border:1px solid var(--neg); }}
.analysis-block {{ margin-bottom:{'22px' if compact else '38px'}; }}
.analysis-block h3 {{ margin-bottom:12px; }}
figure.chart {{ margin:26px 0 30px; }}
figure.chart figcaption {{ font-size:.92rem; font-weight:500; color:var(--ink-soft); margin-bottom:14px; }}
.chart-title {{ display:block; font-size:.95rem; font-weight:600; color:var(--ink); margin-bottom:3px; }}
.chart-caption {{ display:block; }}
.chart-svg {{ width:100%; height:auto; display:block; overflow:visible; }}
.svg-label {{ font-size:12.5px; fill:var(--ink-soft); font-weight:500; }}
.svg-value {{ font-size:12.5px; fill:var(--ink); font-weight:600; }}
.svg-value-in {{ font-size:12.5px; fill:#fff; font-weight:600; }}
.svg-axis {{ font-size:11px; fill:var(--muted); }}
.svg-note {{ font-size:11px; fill:var(--muted); }}
/* 图表标注压到折线/网格上时，用底色描边留出光晕，保证仍然读得清 */
.svg-value, .svg-note {{ paint-order:stroke fill; stroke:var(--surface); stroke-width:3px; stroke-linejoin:round; }}
.chart-note {{ font-size:.8rem; color:var(--muted); margin:12px 0 0; }}
.chart-source {{ font-size:.76rem; color:var(--muted); margin:4px 0 0; }}
table.data {{ width:100%; border-collapse:collapse; margin:20px 0; font-size:.88rem; }}
table.data caption {{ text-align:left; font-size:.88rem; font-weight:500; color:var(--ink-soft); padding-bottom:10px; }}
table.data th, table.data td {{ text-align:left; padding:12px 14px 12px 0; border-bottom:1px solid var(--border); }}
table.data th {{ font-size:.76rem; letter-spacing:.02em; color:var(--muted); font-weight:500; }}
table.data td.num, table.data th.num {{ text-align:right; font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; padding-left:16px; }}
.conclusions {{ list-style:none; padding:0; margin:0; }}
.conclusion {{ padding:16px 0; border-bottom:1px solid var(--border); display:flex; flex-wrap:wrap; gap:10px; align-items:baseline; }}
.conclusion-text {{ flex:1 1 360px; color:var(--ink); }}
.steps-title {{ margin:30px 0 14px; }}
.steps {{ list-style:none; padding:0; margin:0; display:grid; gap:10px; }}
.step {{ background:var(--surface-alt); border-radius:var(--radius-sm); padding:16px 20px; }}
.step-q {{ display:block; color:var(--ink); }}
.step-need {{ display:block; margin-top:6px; font-size:.84rem; color:var(--muted); }}
.aside {{ font-size:.86rem; color:var(--muted); }}
.empty {{ color:var(--muted); font-size:.86rem; }}
footer.colophon {{ margin-top:56px; padding-top:20px; border-top:1px solid var(--border); font-size:.78rem; color:var(--muted); }}
@media (max-width:720px) {{
  body {{ padding:40px 20px 64px; }}
  .subtitle {{ font-size:1.06rem; }}
}}
@media print {{
  body {{ max-width:none; padding:0; }}
  .toc {{ display:none; }}
  .block, figure.chart, table.data, .finding, .kpi-grid {{ break-inside:avoid; }}
}}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none !important; transition:none !important; }} }}
""".strip()


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
{banner}
{header}
{nav}
<main>
{blocks}
</main>
<footer class="colophon">本报告由 data-analysis skill 生成；数字来自离线证据 JSON，可逐条复算。{generated}</footer>
{script}
</body>
</html>
"""

JS = """<script>
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce || !('IntersectionObserver' in window)) return;
  var nodes = [].slice.call(
    document.querySelectorAll('figure.chart, .finding, .analysis-block, .kpi-grid')
  );
  var showAll = function () {
    nodes.forEach(function (node) { node.classList.add('in'); });
  };
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('in');
      observer.unobserve(entry.target);
    });
  }, { rootMargin: '0px 0px -4% 0px' });
  nodes.forEach(function (node) { node.classList.add('reveal'); observer.observe(node); });
  // 兜底：打印、截图、后台标签页不会触发布局观察，1.5s 后强制全部显示。
  setTimeout(showAll, 1500);
  window.addEventListener('beforeprint', showAll);
})();
</script>
<style>
.reveal{opacity:0;transform:translateY(10px);transition:opacity .55s cubic-bezier(.4,0,.2,1),transform .55s cubic-bezier(.4,0,.2,1)}
.reveal.in{opacity:1;transform:none}
@media print{.reveal{opacity:1 !important;transform:none !important}}
@media (prefers-reduced-motion: reduce){.reveal{opacity:1 !important;transform:none !important}}
</style>"""


EXAMPLE_SPEC = {
    "meta": {"title": "示例报告", "decision": "决策复盘", "window": "2026-01-01~2026-03-31", "source": "example.csv"},
    "diversity": {"theme": DEFAULT_THEME, "style": "apple", "motion": "restrained", "density": 4},
    "kpis": [{"label": "订单量", "value": 30500, "delta": "-20.4%", "direction": "down", "raw": 30500}],
    "findings": [{"title": "示例发现", "body": "这里是结论正文。", "level": "L1", "tone": "negative",
                  "evidence_ids": ["R003"], "limitations": ["单断点"]}],
    "background": {"narrative": "背景说明。"},
    "data_overview": {"narrative": "数据概况。", "table": {"columns": [{"key": "k", "label": "项目"}, {"key": "v", "label": "值"}],
                                                          "rows": [{"k": "行数", "v": 90}], "numeric_columns": ["v"]}},
    "analysis": [{"heading": "机制一", "narrative": "说明。", "charts": [{"type": "line", "title": "趋势", "baseline": 1000,
                                                                     "data": [{"label": "1月", "value": 1000}, {"label": "3月", "value": 800}]}]}],
    "conclusions": [{"text": "结论一。", "evidence_ids": ["R003"]}],
    "next_steps": [{"question": "补什么数据能回答什么？", "data_needed": "支付日志"}],
    "appendix": {"notes": ["口径说明。"]},
}


# --------------------------------------------------------------------- 校验与入口


PLACEHOLDERS = ("待补", "TODO", "todo", "此处略", "图表待生成", "占位")


def _evidence_problems(items: Any, label: str) -> list[str]:
    """每条结论都必须自带证据引用；这是 skill 的硬规则，不靠模型自觉。"""
    problems: list[str] = []
    if items is None:
        return problems
    if not isinstance(items, list):
        return [f"{label} 应为数组"]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"{label}[{index}] 应为对象")
            continue
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or not [value for value in ids if str(value).strip()]:
            problems.append(f"{label}[{index}] 缺少非空 evidence_ids")
    return problems


def _walk_strings(node: Any) -> Any:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_strings(value)


def validate(spec: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["规格必须是 JSON 对象"]
    meta = spec.get("meta")
    if not isinstance(meta, dict) or not str(meta.get("title") or "").strip():
        problems.append("缺少 meta.title")
    findings = spec.get("findings")
    if not isinstance(findings, list) or not findings:
        problems.append("缺少 findings（至少一条核心发现）")
    for name in ("background", "data_overview", "analysis", "conclusions", "next_steps", "appendix"):
        if name in spec and not isinstance(spec[name], (dict, list)):
            problems.append(f"{name} 的类型应为对象或数组")

    for index, item in enumerate(findings or []):
        if not isinstance(item, dict):
            problems.append(f"findings[{index}] 应为对象")
            continue
        if not str(item.get("body") or "").strip():
            problems.append(f"findings[{index}] 缺少 body")
        level = str(item.get("level") or "").upper()
        if level and level not in LEVEL_LABEL:
            problems.append(f"findings[{index}] 未知 level：{item.get('level')}；可选 {sorted(LEVEL_LABEL)}")
    problems.extend(_evidence_problems(findings, "findings"))
    problems.extend(_evidence_problems(spec.get("conclusions"), "conclusions"))

    for index, step in enumerate(spec.get("next_steps") or []):
        if not isinstance(step, dict) or not str(step.get("question") or "").strip():
            problems.append(f"next_steps[{index}] 缺少 question")
    for index, item in enumerate(spec.get("kpis") or []):
        direction = str((item or {}).get("direction") or "")
        if direction and direction not in ("up", "down", "flat"):
            problems.append(f"kpis[{index}] direction 只能是 up / down / flat")

    degraded = meta.get("degraded") if isinstance(meta, dict) else None
    if isinstance(degraded, dict):
        for field in ("read", "unread", "reason"):
            if not str(degraded.get(field) or "").strip():
                problems.append(f"degraded 模式缺少 {field}")

    diversity = spec.get("diversity") or {}
    if isinstance(diversity, dict):
        if diversity.get("theme") and diversity["theme"] not in THEMES:
            problems.append(f"未知 theme：{diversity['theme']}；可选 {sorted(THEMES)}")
        if diversity.get("style") and diversity["style"] not in STYLE_PROFILES:
            problems.append(f"未知 style：{diversity['style']}；可选 {sorted(STYLE_PROFILES)}")
    for index, block in enumerate(spec.get("analysis") or []):
        if not isinstance(block, dict) or not str(block.get("heading") or "").strip():
            problems.append(f"analysis[{index}] 缺少 heading")
            continue
        for chart in block.get("charts") or []:
            if str(chart.get("type") or "line") not in CHART_BUILDERS:
                problems.append(f"analysis[{index}] 未知图表类型：{chart.get('type')}")
            if chart.get("type") == "line":
                data = chart.get("data") or []
                marker = chart.get("marker") or {}
                if marker.get("index") is not None and isinstance(data, list) and len(data) and int(marker["index"]) >= len(data):
                    problems.append(f"analysis[{index}] marker.index 超出数据点范围（{len(data)} 个点）")

    for text in _walk_strings(spec):
        hit = next((word for word in PLACEHOLDERS if word in text), None)
        if hit:
            problems.append(f"规格里出现占位词「{hit}」：{text[:40]}")
            break
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="把报告规格 JSON 渲染成自包含离线 HTML")
    parser.add_argument("--spec", required=True, help="报告规格 JSON 路径")
    parser.add_argument("--out", required=True, help="输出 HTML 路径")
    parser.add_argument("--emit-example", help="额外写出一份最小示例规格")
    args = parser.parse_args()

    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(json.dumps({"status": "fail", "error": f"规格不是合法 JSON：{error}"}, ensure_ascii=False))
        return 2
    except OSError as error:
        print(json.dumps({"status": "fail", "error": f"读不到规格文件：{error}"}, ensure_ascii=False))
        return 2
    problems = validate(spec)
    if problems:
        print(json.dumps({"status": "fail", "problems": problems}, ensure_ascii=False, indent=2))
        return 2

    markup = render_report(spec)
    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markup, encoding="utf-8")
        if args.emit_example:
            write_json(args.emit_example, EXAMPLE_SPEC)
    except OSError as error:
        print(json.dumps({"status": "fail", "error": f"写不出报告文件：{error}"}, ensure_ascii=False))
        return 2
    external = [token for token in ("http://", "https://", "//cdn", "@import") if token in markup]
    print(json.dumps({
        "status": "ok", "out": str(out), "bytes": out.stat().st_size,
        "external_requests": external, "sections": list(SECTIONS),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
