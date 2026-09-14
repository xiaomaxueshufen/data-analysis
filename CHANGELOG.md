# Changelog

版本号沿用被删除的 `plugin.json` 里的语义（`0.8.0` 是删除前的最后一版）。本仓库就是 skill 目录本身、不随包发布，所以版本号只用于标识变更批次，代码里不读取。

## 0.9.0

### 修复

- **交付契约自相矛盾**：`SKILL.md` 写「交付物恒为 HTML」，`references/clarify.md` 写反问轮「不生成完整报告」，两处对同一件事给了不同答案。现统一为：**反问轮不产出 `report.html`，且这是唯一例外；除此之外一切情况（含质量门禁阻断、`da_verify` fail、SRM 报警、降级路径命中）都必须交付 HTML**。措辞已同步到 `SKILL.md`（目标 3、硬门禁 1、渲染段、交付前自检项）、`references/clarify.md` 和 `README.md`。
- **`--require-agent-manifest` 缺 `--agents-dir` 时静默通过**：现在直接输出 `{"status": "fail", "error": ...}` 并以退出码 `2` 结束，不再把「没给 agents 目录」当作「没有 agent 问题」。
- **`da_verify` 把日期标签当成待溯源数字**：「11 月」「2011-11」这类日历标签会作为数字参与匹配、产生假告警。日期模式已扩展，`YYYY年M月D日` / `YYYY-MM` / `M月` / `M季度` 不再参与溯源。

### 变更

- **删除 `plugin.json`**：它通不过官方 `validate_plugin.py`——要过校验就得改成 `skills/<name>/` 的插件布局，而那会破坏「克隆仓库根目录即为 skill 目录」的安装方式（README 的两种安装方式都依赖它）。两者不可兼得，选择保可用性、删掉这份元数据，版本语义移入本文件。

### 新增

- **异动算子门禁**（`scripts/da_ops.py`）：`anomaly_scan` 新增 `min_baseline_n`（默认 14，判基线窗口内可用历史天数）与 `warmup_days`（默认 14，前 N 天不做异动判定）；同星期基线要 `min_points_for_weekday`（默认 8，整 8 周）才启用，否则回退滚动窗口中位数；进入基线计算的点少于 3 个的日期硬性排除。输出新增 `gates` / `coverage` / `excluded_rows`（带 `exclusion_reason` 与 `exclusion_detail`）。动机是基线尺度下限为 `|base| × 1%`，开头只有 1–2 天基线时 robust z 会被放大到 10 以上并霸占榜首。
- **旧算子补 `limitations`**：`funnel_rates`、`contribution`、`ratio_decomp`、`ab_effect`、`segment_profile` 现在都输出 `limitations` 数组，说明该次计算**不能**支持什么结论（正负抵消、池化标准误的独立性前提、多值字段重复计数等）。
- **`scripts/da_measure.py`**：把 README 里的效能数字变成可复算输出——常驻正文 token 数（按 `o200k_base` / `cl100k_base` 分别计）、「写规格 vs 手写 HTML」的输出量差、覆盖率的复算口径；`--require-tiktoken` 让缺依赖变成失败。
- **CI**（`.github/workflows/ci.yml`）：`test` job 在 Python 3.10 / 3.12 / 3.13 上跑 74 项回归测试；`gate` job 校验案例工件过 `da_verify`（0 fail、0 agent issue）、案例表内对账、示例报告与案例报告的逐字节渲染比对、覆盖率统计与 token 口径复算。
- **真实脱敏案例**（`examples/case_study/`）：基于公开数据集 UCI Online Retail II（CC BY 4.0）的聚合口径案例，含数据构建脚本（逐条记录清洗规则与影响行数）、16 条证据、15 条分级结论、四个独立角色工件、`da_verify` 通过结果和逐字节可复现的 HTML 报告。
- **`conftest.py` + `.coveragerc`**：CLI 测试是 subprocess 调用的，之前的覆盖率把 `da_verify` / `da_reconcile` 记为 0%。现在带 `COVERAGE_PROCESS_START` 运行可统计子进程，合计覆盖率 81%。

### 测试

- 68 → 74 项：新增 `test_anomaly_gates`、`test_legacy_operator_limitations`、`test_calendar_labels_not_required`、`test_agent_manifest_requires_agents_dir`、`test_example_report_is_reproducible`、`test_case_study_report_renders`。
- 报告渲染新增逐字节可复现断言（示例报告 + 案例报告），CI 里同样逐字节比对。
- README 里的覆盖率与 token 数字改为带口径的实测值，并可用 `python scripts/da_measure.py` 复算。

## 0.8.0

- `da_report.py` 报告渲染器：模型只写紧凑的规格 JSON，脚本渲染自包含离线 HTML（五套主题、四种纯 SVG 图表、六段式骨架由代码写死，机器校验证据引用 / 层级 / 图表类型 / 占位词）。
- 单次报告输出成本从约 10,700 token 降到 2,000–3,000；`SKILL.md` 常驻正文从 7,600 压到 4,900 token。
- 三份重复的报告设计文档合并为 `references/report-design.md`，新增「哪一步读哪个文件」的渐进式披露加载表。
- 移除会冻结成错误读数的数值动画（条形生长、折线 draw-in、数字 count-up）；图表文字按 WCAG 自动挑色，对比度不足时把数值移到条外。

更早版本见 `git log`。
