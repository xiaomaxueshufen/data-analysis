from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from da_common import read_json


CSS = r"""
:root{--paper:#fffdf8;--canvas:#eeebe4;--ink:#182126;--muted:#667078;--accent:#0f5f73;--positive:#247154;--negative:#b64635;--border:#d8d3c9;--soft:#f1eee7;--page:1200px;--gutter:22px;--rule:1px solid var(--border)}
*{box-sizing:border-box}html{scroll-behavior:smooth;background:var(--canvas)}body{margin:0;color:var(--ink);background:var(--canvas);font-family:"Microsoft YaHei","Microsoft YaHei UI",Arial,sans-serif;font-size:15px;line-height:1.68;font-synthesis:none}a{color:inherit}h1,h2,h3,p,li,dd{overflow-wrap:anywhere}.skip-link{position:fixed;left:16px;top:12px;z-index:4;transform:translateY(-180%);background:var(--ink);color:var(--paper);padding:8px 12px}.skip-link:focus{transform:none}.page{width:min(calc(100% - 80px),var(--page));margin:30px auto 68px;background:var(--paper);border-top:5px solid var(--accent);padding:0 42px 50px}.topline{display:flex;justify-content:space-between;align-items:center;padding:15px 0;border-bottom:var(--rule);font-size:12px;color:var(--muted)}.brand{font-weight:700;color:var(--accent)}.status-line{display:flex;gap:9px;align-items:center}.status-dot{width:8px;height:8px;background:var(--positive);border-radius:50%}.status-dot.warn{background:var(--negative)}.masthead{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:var(--gutter);padding:54px 0 36px}.title-block{grid-column:1/span 8;min-width:0}.meta-block{grid-column:10/span 3;border-left:3px solid var(--accent);padding-left:16px;align-self:end;min-width:0}.kicker,.section-kicker,.rail-label{margin:0 0 8px;color:var(--accent);font-size:12px;font-weight:700;letter-spacing:0}.masthead h1{margin:0;font-size:40px;line-height:1.18;letter-spacing:0}.standfirst{max-width:36em;margin:18px 0 0;color:var(--muted);font-size:16px}.meta-block dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12px}.meta-block dt{color:var(--muted)}.meta-block dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}.fact-rail{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:var(--gutter);border-top:2px solid var(--ink);border-bottom:var(--rule);padding:20px 0 22px}.metric{grid-column:span 3;min-width:0}.metric+.metric{border-left:var(--rule);padding-left:var(--gutter)}.metric-label{margin:0;color:var(--muted);font-size:12px}.metric-value{margin:7px 0 0;font-size:30px;line-height:1.1;font-weight:700;font-variant-numeric:tabular-nums}.metric-value small{font-size:12px;font-weight:400;color:var(--muted)}.negative-text{color:var(--negative)}.positive-text{color:var(--positive)}.summary{max-width:820px;padding:34px 0 8px}.summary h2{margin:0 0 10px;font-size:14px;color:var(--accent)}.summary p{margin:0;font-size:20px;line-height:1.65}.report-nav{display:flex;gap:20px;flex-wrap:wrap;margin:22px 0 0;padding:12px 0;border-top:var(--rule);border-bottom:var(--rule);font-size:12px;color:var(--muted)}.report-nav a{text-decoration:none}.report-nav a:hover,.report-nav a:focus-visible{color:var(--accent);text-decoration:underline;text-underline-offset:4px}.overview{padding:48px 0 10px}.overview>h2,.method-section>h2{font-size:24px;line-height:1.32;margin:0 0 22px}.finding-list{list-style:none;margin:0;padding:0;border-top:2px solid var(--ink)}.finding-list li{display:grid;grid-template-columns:70px minmax(0,760px);gap:18px;padding:20px 0 22px;border-bottom:var(--rule)}.finding-number{font-size:12px;color:var(--accent);padding-top:4px}.finding-list h3{font-size:17px;margin:0 0 6px}.finding-list p{margin:0}.trace,figcaption{color:var(--muted);font-size:11px!important;margin-top:9px!important;word-break:break-word}.analysis-section{padding:52px 0 4px;scroll-margin-top:20px}.section-title{display:flex;gap:11px;align-items:flex-start;margin-bottom:22px}.section-index{color:var(--accent);font-size:12px;padding-top:9px}.section-title h2{margin:0;max-width:780px;font-size:25px;line-height:1.34}.exhibit-grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:var(--gutter);align-items:start}.exhibit{grid-column:1/span 8;margin:0;border-top:2px solid var(--ink);padding-top:12px;min-width:0}.chart-subtitle{margin:0 0 8px;color:var(--muted);font-size:12px}.plot-frame{background:var(--soft);padding:14px 12px 8px;overflow-x:auto}.report-chart{display:block;width:100%;height:auto;min-width:580px}.line-series{fill:none;stroke:var(--accent);stroke-width:3}.baseline-series{fill:none;stroke:var(--negative);stroke-width:2;stroke-dasharray:6 5}.zero-line{stroke:var(--ink);stroke-width:1}.plot-label,.plot-axis{fill:var(--muted);font-size:12px}.chart-point{fill:var(--accent)}.reading-rail{grid-column:10/span 3;border-top:2px solid var(--ink);padding-top:12px;font-size:13px}.reading-rail ul{margin:10px 0 0;padding-left:18px}.reading-rail li{margin-bottom:9px}.boundary-note{border-left:3px solid var(--border);padding-left:12px;margin-top:18px;color:var(--muted);font-size:12px}.table-section .table-wrap{margin-top:5px}.table-wrap{overflow-x:auto;border-top:2px solid var(--ink);border-bottom:var(--rule)}table{width:100%;border-collapse:collapse;font-size:13px}caption{text-align:left;color:var(--muted);font-size:12px;padding:9px 0}th,td{padding:10px 12px;border-bottom:var(--rule);text-align:left;vertical-align:top}th{font-size:12px;color:var(--muted);font-weight:700}tr:last-child td{border-bottom:0}.numeric{font-variant-numeric:tabular-nums;text-align:right}.quality-row td{background:#fff3ec}.decision-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--gutter);margin-top:52px;border-top:2px solid var(--ink);border-bottom:var(--rule)}.decision-block{padding:18px 0 22px}.decision-block+.decision-block{border-left:var(--rule);padding-left:var(--gutter)}.decision-block h2{font-size:18px;margin:0 0 10px}.decision-block ul{margin:0;padding-left:18px;font-size:13px}.next-analysis{margin-top:54px;padding:30px 0 0;border-top:2px solid var(--ink)}.next-header{max-width:760px}.next-header h2{font-size:25px;line-height:1.35;margin:0 0 10px}.next-header p{margin:5px 0;color:var(--muted)}.route-list{margin-top:22px;border-top:var(--rule)}.analysis-route{display:grid;grid-template-columns:80px minmax(0,1fr) 260px;gap:var(--gutter);padding:20px 0 22px;border-bottom:var(--rule)}.route-index{color:var(--accent);font-size:12px;padding-top:4px}.route-main h3{font-size:17px;margin:0 0 5px}.route-main p{margin:5px 0;font-size:13px}.route-question{font-size:15px!important}.route-output{color:var(--muted)}.route-side{border-left:var(--rule);padding-left:var(--gutter);font-size:12px}.route-side ul{margin:6px 0 8px;padding-left:18px}.method-section{padding:50px 0 10px}.method-grid{display:grid;grid-template-columns:2fr 1fr;gap:var(--gutter);border-top:var(--rule);padding-top:16px;font-size:12px}.method-main p,.method-side p{margin:5px 0}.method-side{border-left:var(--rule);padding-left:var(--gutter)}details{margin-top:22px;border-top:var(--rule);padding-top:12px}summary{cursor:pointer;color:var(--accent);font-size:13px;font-weight:700}footer{margin-top:42px;padding-top:15px;border-top:var(--rule);color:var(--muted);font-size:11px;line-height:1.6}@media(max-width:900px){.page{width:min(calc(100% - 28px),var(--page));padding:0 22px 40px;margin:14px auto 35px}.masthead{display:block;padding:36px 0 26px}.meta-block{margin-top:25px}.fact-rail{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.metric{grid-column:span 1}.metric+.metric{border-left:0;padding-left:0}.exhibit-grid{display:block}.reading-rail{margin-top:22px}.decision-grid{grid-template-columns:1fr}.decision-block+.decision-block{border-left:0;border-top:var(--rule);padding-left:0}.analysis-route{grid-template-columns:60px 1fr}.route-side{grid-column:2;border-left:0;border-top:var(--rule);padding:12px 0 0}.masthead h1{font-size:32px}}@media(max-width:560px){.page{padding:0 16px 32px}.masthead h1{font-size:28px}.summary p{font-size:17px}.report-nav{gap:12px}.finding-list li{grid-template-columns:42px 1fr}.analysis-route{grid-template-columns:1fr}.route-index{padding:0}.route-side{grid-column:1}.metric-value{font-size:24px}}
"""

CSS += r"""
:root{--paper:#ffffff;--canvas:#eef6fb;--ink:#18313f;--muted:#647d8a;--accent:#4b9dcc;--accent-deep:#2f78a5;--positive:#4e9b83;--negative:#df6b72;--border:#d7e8f2;--soft:#f3f9fd;--rule:1px solid var(--border)}
html{background:var(--canvas)}body{background:var(--canvas);letter-spacing:.005em}.page{background:var(--paper);border-top-color:var(--accent);box-shadow:0 18px 48px rgba(47,120,165,.08)}.brand,.kicker,.section-kicker,.rail-label,.finding-number,.section-index,summary{color:var(--accent-deep)}.topline{border-bottom-color:var(--border)}.status-dot{background:var(--positive)}.status-dot.warn{background:var(--negative)}.meta-block{border-left-color:var(--accent)}.fact-rail{border-bottom-color:var(--border)}.summary h2{color:var(--accent-deep)}.report-nav a{transition:color .2s ease,background-color .2s ease;text-underline-offset:4px}.report-nav a.active{color:var(--accent-deep);font-weight:700;text-decoration:underline}.plot-frame{background:var(--soft);border:1px solid rgba(215,232,242,.72)}.line-series{stroke:var(--accent-deep)}.baseline-series{stroke:var(--negative)}.chart-point{fill:var(--accent)}.chart-accent{fill:var(--accent)}.quality-row td{background:#fff3f4}.decision-grid{border-bottom-color:var(--border)}
.reveal{opacity:0;transform:translateY(14px);transition:opacity .55s ease,transform .55s ease}.reveal.on{opacity:1;transform:none}.metric-value{animation:rise .65s ease both}.finding-list li,.analysis-route{transition:background-color .2s ease}.finding-list li:hover,.analysis-route:hover{background:rgba(243,249,253,.72)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.reveal{opacity:1;transform:none;transition:none}.metric-value{animation:none}.report-nav a,.finding-list li,.analysis-route{transition:none}}
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def numeric(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
        return f"{number:,.{digits}f}"
    except (TypeError, ValueError):
        return esc(value)


def is_rate_metric(metric: str | None) -> bool:
    text = str(metric or "").lower()
    return text.endswith("rate") or "率" in text or "ratio" in text or "conversion" in text


def display_value(value: Any, metric: str | None = None, digits: int = 1) -> str:
    if value is None:
        return "—"
    if is_rate_metric(metric):
        try:
            return f"{float(value) * 100:.{digits}f}%"
        except (TypeError, ValueError):
            return esc(value)
    return numeric(value, 0 if abs(float(value)) >= 100 else digits)


def signed_value(value: Any, metric: str | None = None) -> str:
    if value is None:
        return "—"
    try:
        number_value = float(value)
    except (TypeError, ValueError):
        return esc(value)
    text = display_value(number_value, metric)
    return ("+" if number_value > 0 else "") + text


def fallback_narrative(analysis: dict, quality: dict) -> dict:
    events = material_events(analysis, quality)
    findings = []
    primary_role = analysis.get("primary_metric", {}).get("role")
    for event in events[:8]:
        metrics = event.get("metrics", [])
        primary = next((item for item in metrics if item.get("metric") == primary_role), metrics[0] if metrics else {})
        value = primary.get("value")
        baseline = primary.get("baseline", {}).get("value") if isinstance(primary.get("baseline"), dict) else None
        if event.get("excluded_by_quality"):
            statement = f"{event.get('date')} 先按数据质量问题处理：关键字段或链路质量与该日异常同时出现，不能直接解释为业务变化。"
        else:
            statement = f"{event.get('date')} 出现需要复核的偏离：当前值 {display_value(value, primary_role)}，基线 {display_value(baseline, primary_role)}，稳健异常评分 {numeric(event.get('score'), 2)}。"
        findings.append({
            "title": f"{event.get('date')}：{'数据质量优先' if event.get('excluded_by_quality') else '指标偏离'}",
            "statement": statement,
            "level": "L0" if event.get("excluded_by_quality") else "L1",
            "confidence": "high" if event.get("excluded_by_quality") else "medium",
            "evidence_ids": event.get("evidence_ids", []),
            "support": [item.get("statement") for item in event.get("mechanism_candidates", [])[:3]],
            "limitations": event.get("limitations", []),
        })
    if not findings:
        findings.append({"title": "当前没有足够证据生成业务结论", "statement": "请先确认主指标、时间列和比较基线。", "level": "L0", "confidence": "low", "evidence_ids": [], "support": [], "limitations": []})
    return {
        "title": "数据分析报告",
        "subtitle": "报告只展示当前数据支持的事实与候选解释，未确认的原因不写成确定因果。",
        "executive_summary": "先看事实，再看与观测信号一致的机制候选；没有实验或业务事件确认的解释会保留为待验证假设。",
        "key_metrics": [],
        "findings": findings,
        "next_steps": [
            {"need": "确认异动日期对应的活动、版本、投放、支付或数据链路事件", "unlocks": "把同步候选升级为已确认的业务事件解释", "decision": "确定排查或复盘优先级"},
            {"need": "补充按渠道、设备、用户类型或路由的分子分母明细", "unlocks": "判断是结构变化还是组内效率变化", "decision": "决定优化流量、系统或策略"},
        ],
        "assumptions": ["字段角色来自名称和类型的候选识别，正式报告应由用户确认口径。"],
    }


def report_dates(analysis: dict) -> tuple[str, str]:
    dates = [item.get("date") for item in analysis.get("daily", []) if item.get("date")]
    return (min(dates), max(dates)) if dates else ("未识别", "未识别")


def material_events(analysis: dict, quality: dict) -> list[dict]:
    primary_role = analysis.get("primary_metric", {}).get("role")
    selected = []
    for event in analysis.get("events", []):
        primary = next((item for item in event.get("metrics", []) if item.get("metric") == primary_role), None)
        z = primary.get("deviation", {}).get("robust_z") if primary else None
        meaningful = event.get("excluded_by_quality") or float(event.get("score") or 0) >= 15 or len(event.get("mechanism_candidates", [])) >= 1 or (z is not None and abs(float(z)) >= 3)
        if meaningful:
            selected.append(event)
    return selected or analysis.get("events", [])[:8]


def build_title(narrative: dict, analysis: dict) -> str:
    title = narrative.get("title")
    if title and title != "数据分析报告":
        return str(title)
    metric = analysis.get("primary_metric", {}).get("field") or "主指标"
    start, end = report_dates(analysis)
    return f"{metric}异动分析｜{start}至{end}"


def current_snapshot(analysis: dict) -> dict:
    series = [item for item in analysis.get("time_series", []) if item.get("value") is not None]
    latest = series[-1] if series else {}
    metric = analysis.get("primary_metric", {}).get("field") or analysis.get("primary_metric", {}).get("role")
    value = latest.get("value")
    baseline = latest.get("baseline")
    delta = value - baseline if value is not None and baseline is not None else None
    relative = delta / baseline if delta is not None and baseline else None
    return {"metric": metric, "value": value, "baseline": baseline, "delta": delta, "relative": relative, "date": latest.get("date")}


def svg_time_series(series: list[dict], title: str, metric: str | None) -> str:
    points = []
    for item in series:
        if item.get("value") is None:
            continue
        try:
            points.append((str(item.get("date")), float(item.get("value")), item.get("baseline")))
        except (TypeError, ValueError):
            continue
    if len(points) < 2:
        return "<p class='chart-fallback'>当前主指标没有足够的有效时间点，暂不绘制趋势图。</p>"
    width, height, left, right, top, bottom = 860, 285, 54, 18, 30, 46
    values = [point[1] for point in points] + [float(point[2]) for point in points if point[2] is not None]
    low, high = min(values), max(values)
    pad = max((high - low) * 0.14, 0.005 if is_rate_metric(metric) else 1)
    low -= pad
    high += pad
    def xy(index: int, value: float) -> tuple[float, float]:
        return (left + index * (width - left - right) / max(len(points) - 1, 1), top + (high - value) * (height - top - bottom) / max(high - low, 1e-9))
    line = " ".join(f"{xy(i, value)[0]:.1f},{xy(i, value)[1]:.1f}" for i, (_, value, _) in enumerate(points))
    base_points = [(i, float(base)) for i, (_, _, base) in enumerate(points) if base is not None]
    baseline = " ".join(f"{xy(i, value)[0]:.1f},{xy(i, value)[1]:.1f}" for i, value in base_points)
    labels = []
    for index, (date, value, _) in enumerate(points):
        x, y = xy(index, value)
        labels.append(f"<circle class='chart-point' cx='{x:.1f}' cy='{y:.1f}' r='3.2'/>")
        if index == 0 or index == len(points) - 1 or index % max(1, len(points) // 7) == 0:
            labels.append(f"<text class='plot-axis' x='{x:.1f}' y='{height-13}' text-anchor='middle'>{esc(date[5:] if len(date)>5 else date)}</text>")
    return f"<svg class='report-chart' viewBox='0 0 {width} {height}' role='img' aria-label='{esc(title)}'><title>{esc(title)}</title><line class='zero-line' x1='{left}' x2='{width-right}' y1='{height-bottom}' y2='{height-bottom}'/><polyline class='line-series' points='{line}'/>{f"<polyline class='baseline-series' points='{baseline}'/>" if baseline else ''}{''.join(labels)}</svg>"


def svg_funnel(funnel: dict) -> str:
    if not funnel.get("available"):
        return "<p class='chart-fallback'>当前没有足够的阶段计数字段，暂不绘制漏斗图。</p>"
    stages = [item for item in funnel.get("stages", []) if item.get("count") is not None]
    if len(stages) < 2:
        return "<p class='chart-fallback'>当前没有足够的阶段计数字段，暂不绘制漏斗图。</p>"
    max_count = max(float(item["count"]) for item in stages) or 1
    width, height = 860, max(190, 65 * len(stages))
    body = [f"<svg class='report-chart' viewBox='0 0 {width} {height}' role='img' aria-label='阶段漏斗'><title>阶段漏斗</title>"]
    for index, stage in enumerate(stages):
        y = 22 + index * 60
        bar_width = 610 * float(stage["count"]) / max_count
        rate = stage.get("rate_from_previous")
        body.append(f"<text class='plot-label' x='10' y='{y+19}'>{esc(stage.get('stage'))}</text><rect class='chart-accent' x='145' y='{y}' width='{bar_width:.1f}' height='28' rx='2'/><text class='plot-label' x='{min(790,155+bar_width):.1f}' y='{y+19}'>{numeric(stage.get('count'))} · {display_value(rate, 'rate') if rate is not None else '起点'}</text>")
    body.append("</svg>")
    return "".join(body)


def render_findings(findings: list[dict]) -> str:
    rows = []
    for index, finding in enumerate(findings[:10], start=1):
        support = "；".join(str(item) for item in finding.get("support", []) if item)
        trace = ", ".join(str(item) for item in finding.get("evidence_ids", [])[:8]) or "未绑定逐字段证据"
        boundary = "；".join(str(item) for item in finding.get("limitations", []) if item)
        detail = f"<p class='trace'>证据：{esc(trace)}{f'｜边界：{esc(boundary)}' if boundary else ''}{f'｜观测信号：{esc(support)}' if support else ''}</p>"
        rows.append(f"<li><div class='finding-number'>{index:02d}</div><div><h3>{esc(finding.get('title'))}</h3><p>{esc(finding.get('statement'))}</p>{detail}</div></li>")
    return "<ol class='finding-list'>" + "".join(rows) + "</ol>"


def render_event_table(events: list[dict], metric_role: str | None) -> str:
    rows = []
    for event in events:
        metrics = {item.get("metric"): item for item in event.get("metrics", [])}
        primary = metrics.get(metric_role, {})
        baseline = primary.get("baseline", {}).get("value") if isinstance(primary.get("baseline"), dict) else None
        delta = primary.get("deviation", {}).get("delta") if isinstance(primary.get("deviation"), dict) else None
        quality = "质量排除" if event.get("excluded_by_quality") else "业务候选"
        cls = " class='quality-row'" if event.get("excluded_by_quality") else ""
        ids = ", ".join(str(item) for item in event.get("evidence_ids", [])[:5])
        rows.append(f"<tr{cls}><td>{esc(event.get('date'))}</td><td class='numeric'>{numeric(event.get('score'),2)}</td><td>{quality}</td><td class='numeric'>{display_value(primary.get('value'), metric_role)}</td><td class='numeric'>{display_value(baseline, metric_role)}</td><td class='numeric'>{signed_value(delta, metric_role)}</td><td>{esc(ids or '—')}</td></tr>")
    if not rows:
        rows.append("<tr><td colspan='7'>没有可展示的候选异动。</td></tr>")
    return "<div class='table-wrap'><table><caption>候选日期按异常评分排序；橙色行属于数据质量排除区。</caption><thead><tr><th>日期</th><th>异常评分</th><th>分类</th><th>当前值</th><th>基线</th><th>偏离</th><th>证据</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


def render_evidence_table(evidence: list[dict]) -> str:
    rows = []
    for item in evidence[:160]:
        source = item.get("source", {})
        rows.append(f"<tr><td>{esc(item.get('evidence_id'))}</td><td>{esc(source.get('sheet'))}</td><td class='numeric'>{esc(source.get('data_row'))}</td><td>{esc(item.get('field'))}</td><td>{esc(item.get('value'))}</td><td>{esc(item.get('detail'))}</td></tr>")
    return "<div class='table-wrap'><table><caption>逐字段证据，展示前 160 条；完整证据保存在运行目录 JSON 工件。</caption><thead><tr><th>ID</th><th>Sheet</th><th>行</th><th>字段</th><th>值</th><th>说明</th></tr></thead><tbody>" + ("".join(rows) if rows else "<tr><td colspan='6'>当前运行没有逐字段证据。</td></tr>") + "</tbody></table></div>"


def render_routes(next_steps: list[dict]) -> str:
    routes = next_steps or [{"need": "确认决策目标、主指标和基线", "unlocks": "把探索性结果转为可发布的比较结论", "decision": "确定正式分析口径"}]
    rows = []
    for index, item in enumerate(routes[:4], start=1):
        rows.append(f"<article class='analysis-route'><div class='route-index'>路线{index:02d}</div><div class='route-main'><h3>{esc(item.get('need'))}</h3><p class='route-question'>{esc(item.get('unlocks'))}</p><p class='route-output'><strong>预计影响：</strong>{esc(item.get('decision'))}</p></div><div class='route-side'><p class='rail-label'>需要补充</p><ul><li>与当前指标同粒度的数据</li><li>可定位到日期或分组的事件字段</li><li>用于验证候选解释的对照信息</li></ul></div></article>")
    return "<div class='route-list'>" + "".join(rows) + "</div>"


def render_report(run_dir: str, out_path: str) -> None:
    run = Path(run_dir)
    profile = read_json(run / "01_profile.json", {}) or {}
    quality = read_json(run / "03_quality.json", {}) or {}
    analysis = read_json(run / "04_analysis.json", {}) or {}
    narrative = read_json(run / "07_narrative.json", None) or read_json(run / "05_narrative.json", None) or fallback_narrative(analysis, quality)
    events_for_report = material_events(analysis, quality)
    title = build_title(narrative, analysis)
    start, end = report_dates(analysis)
    status = quality.get("status") or analysis.get("status") or "UNKNOWN"
    status_label = {"PASS": "通过", "DEGRADED": "需注意", "BLOCK": "阻断"}.get(status, status)
    primary_role = analysis.get("primary_metric", {}).get("role")
    primary_field = analysis.get("primary_metric", {}).get("field") or primary_role or "未识别"
    snapshot = current_snapshot(analysis)
    delta_class = "negative-text" if snapshot.get("delta") is not None and snapshot["delta"] < 0 else "positive-text" if snapshot.get("delta") is not None and snapshot["delta"] > 0 else ""
    dot_class = "warn" if status in {"DEGRADED", "BLOCK"} else ""
    sheets = profile.get("sheets", [])
    source_file = profile.get("file", {}).get("name") or "未识别"
    sha = profile.get("file", {}).get("sha256") or "未记录"
    findings = narrative.get("findings", []) or fallback_narrative(analysis, quality).get("findings", [])
    risks = ["未确认的同步关系只作为候选解释，不升级为因果。"]
    risks.extend(flag.get("message", "存在质量旗标") for flag in quality.get("flags", [])[:3])
    unresolved = list(narrative.get("assumptions", [])) or ["字段角色由名称和类型识别，仍需业务确认。"]
    pending = [item.get("decision") for item in narrative.get("next_steps", [])[:3] if item.get("decision")] or ["本报告不代替业务责任人确认整改优先级。"]
    snapshot_summary = narrative.get("executive_summary") or "报告只展示当前数据支持的事实与候选解释。"
    sheet_summary = "；".join(f"{sheet.get('name')}（{sheet.get('rows')}行，{sheet.get('columns')}列）" for sheet in sheets)
    html_doc = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)}</title><style>{CSS}</style></head><body><a class='skip-link' href='#main'>跳到主要内容</a><main id='main' class='page'>
<div class='topline'><span class='brand'>数据分析｜证据优先</span><span class='status-line'><span class='status-dot {dot_class}' aria-hidden='true'></span>{esc(status_label)}</span></div>
<header class='masthead'><div class='title-block'><p class='kicker'>业务数据分析</p><h1>{esc(title)}</h1><p class='standfirst'>{esc(narrative.get('subtitle') or '结论先行，计算口径、数据质量和后续研究路径同时披露。')}</p></div><div class='meta-block'><dl><dt>观察窗</dt><dd>{esc(start)}至{esc(end)}</dd><dt>主指标</dt><dd>{esc(primary_field)}</dd><dt>分析状态</dt><dd>{esc(status_label)}</dd><dt>来源表</dt><dd>{len(sheets)} 张</dd></dl></div></header>
<section class='fact-rail' aria-label='关键指标'><div class='metric'><p class='metric-label'>最新值 <small>{esc(snapshot.get('date') or '')}</small></p><p class='metric-value'>{display_value(snapshot.get('value'), primary_role)}</p></div><div class='metric'><p class='metric-label'>历史基线</p><p class='metric-value'>{display_value(snapshot.get('baseline'), primary_role)}</p></div><div class='metric'><p class='metric-label'>绝对偏离</p><p class='metric-value {delta_class}'>{signed_value(snapshot.get('delta'), primary_role)}</p></div><div class='metric'><p class='metric-label'>相对偏离</p><p class='metric-value {delta_class}'>{signed_value(snapshot.get('relative'), 'rate')}</p></div></section>
<section class='summary' aria-labelledby='summary-title'><h2 id='summary-title'>全文结论</h2><p>{esc(snapshot_summary)}</p></section>
<nav class='report-nav' aria-label='报告目录'><a href='#findings'>关键发现</a><a href='#visual-evidence'>证据图表</a><a href='#detail-table'>日期明细</a><a href='#decisions'>边界与未决</a><a href='#next-analysis'>后续路线</a><a href='#method'>方法与来源</a></nav>
<section class='overview' id='findings' aria-labelledby='findings-title'><h2 id='findings-title'>最重要的发现与影响范围</h2>{render_findings(findings)}</section>
<section class='analysis-section' id='visual-evidence' aria-labelledby='visual-title'><header class='section-title'><span class='section-index' aria-hidden='true'>01</span><div><p class='section-kicker'>时间证据</p><h2 id='visual-title'>观测值与历史基线的偏离集中在哪些日期</h2></div></header><div class='exhibit-grid'><figure class='exhibit'><p class='chart-subtitle'>蓝线为观测值，红色虚线为脚本计算的历史基线</p><div class='plot-frame'>{svg_time_series(analysis.get('time_series', []), primary_field, primary_role)}</div><figcaption>主指标：{esc(primary_field)}；观察窗：{esc(start)}至{esc(end)}；异常评分和基线保存在分析工件。</figcaption></figure><aside class='reading-rail'><p class='rail-label'>读图</p><ul><li>展示候选异动：{len(events_for_report)} 个日期。</li><li>质量排除：{esc(', '.join(quality.get('excluded_dates', [])) or '无')}。</li><li>当前报告按同星期稳健基线识别偏离，不把周末波动直接写成业务原因。</li></ul><p class='boundary-note'>趋势图用于定位，不单独证明原因。原因判断需要漏斗、环境、策略或业务事件的独立证据。</p></aside></div></section>
<section class='analysis-section' aria-labelledby='funnel-title'><header class='section-title'><span class='section-index' aria-hidden='true'>02</span><div><p class='section-kicker'>过程证据</p><h2 id='funnel-title'>阶段规模能否解释主指标变化</h2></div></header><div class='exhibit-grid'><figure class='exhibit'><p class='chart-subtitle'>阶段人数与相邻阶段转化率</p><div class='plot-frame'>{svg_funnel(analysis.get('funnel', {}))}</div><figcaption>阶段率由相邻阶段计数重算；如果用户实体或跨日口径未确认，漏斗只作为探索性证据。</figcaption></figure><aside class='reading-rail'><p class='rail-label'>当前可读出的范围</p><ul><li>阶段计数来自主表可识别的分子字段。</li><li>漏斗可以定位损失发生在哪一步，但不自动证明产品、库存或系统是原因。</li><li>更细渠道、设备、路由和用户类型的贡献需要同粒度分子分母。</li></ul></aside></div></section>
<section class='analysis-section table-section' id='detail-table' aria-labelledby='detail-title'><header class='section-title'><span class='section-index' aria-hidden='true'>03</span><div><p class='section-kicker'>明细与对账</p><h2 id='detail-title'>保留每个候选日期的方向、偏离和质量分类</h2></div></header>{render_event_table(events_for_report, primary_role)}<details><summary>展开逐字段证据</summary>{render_evidence_table(analysis.get('evidence', []))}</details></section>
<section class='decision-grid' id='decisions' aria-label='决策、风险与未决问题'><article class='decision-block'><h2>待决事项</h2><ul>{''.join(f'<li>{esc(item)}</li>' for item in pending)}</ul></article><article class='decision-block'><h2>风险与反证</h2><ul>{''.join(f'<li>{esc(item)}</li>' for item in risks)}</ul></article><article class='decision-block'><h2>未决问题</h2><ul>{''.join(f'<li>{esc(item)}</li>' for item in unresolved)}</ul></article></section>
<section class='next-analysis' id='next-analysis' aria-labelledby='next-title'><header class='next-header'><p class='section-kicker'>分析选择，不是业务结论</p><h2 id='next-title'>基于当前证据，可以沿这些方向继续分析</h2><p>每条路线都说明补什么、能升级哪一层证据，以及会影响什么决策。不需要一次补齐全部数据。</p></header>{render_routes(narrative.get('next_steps', []))}</section>
<section class='method-section' id='method' aria-labelledby='method-title'><h2 id='method-title'>方法、质量与来源</h2><div class='method-grid'><div class='method-main'><p><strong>方法：</strong>{esc(analysis.get('primary_metric', {}).get('role') or 'anomaly')}｜辅助：funnel / evidence gate</p><p><strong>主表：</strong>{esc(analysis.get('main_table') or '未识别')}；{esc(sheet_summary)}</p><p><strong>来源文件：</strong>{esc(source_file)}｜sha256：{esc(sha)}</p></div><div class='method-side'><p><strong>数据质量：</strong>{esc(status_label)}</p><p><strong>交互策略：</strong>固定报告，不提供改变口径的控件</p></div></div></section>
<footer>渲染方式：离线自包含 HTML｜零外部请求｜业务数字来自锁定计算工件<br>报告设计采用结论先行、证据分层、决策边界和后续分析路线的渐进式披露。</footer></main></body></html>"""
    for original, enhanced in (
        ("class='masthead'", "class='masthead reveal'"),
        ("class='fact-rail'", "class='fact-rail reveal'"),
        ("class='summary'", "class='summary reveal'"),
        ("class='report-nav'", "class='report-nav reveal'"),
        ("class='overview'", "class='overview reveal'"),
        ("class='analysis-section'", "class='analysis-section reveal'"),
        ("class='decision-grid'", "class='decision-grid reveal'"),
        ("class='next-analysis'", "class='next-analysis reveal'"),
        ("class='method-section'", "class='method-section reveal'"),
    ):
        html_doc = html_doc.replace(original, enhanced)
    html_doc = html_doc.replace(
        "</body>",
        "<script>(function(){const items=[...document.querySelectorAll('.reveal')];const links=[...document.querySelectorAll('.report-nav a')];const sections=links.map(function(link){return document.querySelector(link.getAttribute('href'));}).filter(Boolean);function show(item){item.classList.add('on')}if('IntersectionObserver' in window){const observer=new IntersectionObserver(function(entries){entries.forEach(function(entry){if(entry.isIntersecting){show(entry.target);}});},{threshold:.08});items.forEach(function(item){observer.observe(item);});const activeObserver=new IntersectionObserver(function(entries){entries.forEach(function(entry){if(entry.isIntersecting){links.forEach(function(link){link.classList.toggle('active',link.getAttribute('href')==='#'+entry.target.id);});}});},{rootMargin:'-20% 0px -65% 0px',threshold:0});sections.forEach(function(section){activeObserver.observe(section);});}else{items.forEach(show);}})();</script></body>",
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(html_doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成离线 HTML 分析报告")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    render_report(args.run, args.out)


if __name__ == "__main__":
    main()
