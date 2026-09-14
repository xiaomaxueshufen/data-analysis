# 可选验证算子目录

这些算子是**可选的单点复核工具**，不是分析流水线。模型可以现场编写一次性代码完成全部分析，也可以在需要交叉验证某个关键数字时调用其中某个算子。没有任何算子是必经路径。

各脚本入口：

```bash
python scripts/da_profile.py --data <文件路径> --out <profile.json>
python scripts/da_quality.py --profile <profile.json> --data <文件路径> --contract <semantic_contract.json> --out <quality.json>
python scripts/da_ops.py <operator> --data <文件路径> --config <配置.json> --out <证据.json>
python scripts/da_reconcile.py --data <文件路径> --out <对账.json>
python scripts/da_verify.py --claims <claims.json> --evidence <证据.json> --reconciliation <对账.json> --agents-dir <agents> --require-agent-manifest
```

| 脚本/算子 | 用途 | 关键输入 |
|---|---|---|
| `da_profile.py` | 识别 sheet、表头、字段、类型、缺失和时间覆盖 | 文件路径 |
| `da_quality.py` | 检查合同字段缺失、日期重复、空值、极端值和异常延迟 | profile、原始文件、语义合同 |
| `da_reconcile.py` | 用表内「合计 / 小计」行当校验和，对明细做加总交叉验证，产出带 `id` 的对账条目 | 文件路径、容差 |
| `anomaly_scan` | 计算同星期/滚动基线、偏离和 robust z；带 warmup 与基线门禁，输出 `gates` / `coverage` / `excluded_rows` / `limitations` | 日期、指标、`baseline_window_days`、`min_baseline_n`、`warmup_days` |
| `funnel_rates` | 由阶段计数重算阶段率、损失量 | 阶段字段顺序 |
| `ratio_decomp` | 将比率变化拆为组内与结构变化 | 分子、分母、维度、基线 |
| `contribution` | 将总量缺口按组对账 | 组、当前值、基线值 |
| `ab_effect` | 效应、标准误、置信区间和基本显著性 | 分流、指标、`confidence_level` |
| `segment_profile` | 分层规模、价值和覆盖 | 分层字段、指标 |

所有需要数据的算子都会在输出里带 `limitations` 数组，写明这次计算**不能**支持什么结论（基线污染、正负抵消、池化标准误的独立性前提、多值字段重复计数、比率分母漂移等）。写结论前先读它，不要越过它去写因果或排名。

## 异动算子的门禁与覆盖（`anomaly_scan`）

`anomaly_scan` 的基线尺度下限是 `|base| × 1%`：序列开头只有 1–2 天基线时，robust z 会被人为放大到 10 以上并霸占按 `|z|` 排的榜首。两条门禁把这类「没有基线可言的日期」直接排除，而不是留给模型自己发现：

| 参数 | 默认 | 语义 |
|---|---|---|
| `warmup_days` | 14 | 按**序列位置**排除开头 N 天：前 N 天不做异动判定 |
| `min_baseline_n` | 14 | 按**可用历史**排除：基线窗口内历史天数不足 N 天的日期不判定。判的是窗口里有多少天历史，不是同星期子集的大小——56 天窗口里同星期最多 8 天，拿子集大小当门禁会让 14 这个默认值永远无法满足 |
| `min_points_for_weekday` | 8 | 同星期基线要求至少 8 个同星期点（整 8 周）才启用，否则回退到滚动窗口中位数 |
| `baseline_window_days` | 56 | 滚动基线回看窗口 |
| `min_same_weekday` | 2 | 启用同星期基线的下限，与 `min_points_for_weekday` 取较大者 |

另有一条硬地板：进入基线计算的点少于 3 个时中位数与 MAD 不可用，同样排除。

`warmup_days` 与 `min_baseline_n` 是两个口径——前者按位置、后者按可用历史——所以同一天可能同时命中两者，`excluded_rows` 里按 `warmup_period` 先记。

输出逐条说明为什么排除：`gates` 记录本次生效的门禁值，`coverage` 给出 `total_days` / `judged_days` / `excluded_days` 与三类排除计数，`excluded_rows` 每行带 `exclusion_reason`（`warmup_period` / `insufficient_baseline` / `insufficient_baseline_points`）和人类可读的 `exclusion_detail`。负的 `min_baseline_n` 或 `warmup_days` 直接 `ValueError`，不会被静默当成 0；可判定日期少于 5 天时 `limitations` 追加「排名极不稳定，不要按名次解读」。

代价同样写进 `limitations`：序列开头几天的真实事故不会被报出来，`min_baseline_n` 收紧也会削掉早期真实尖峰。

## 增长与生命周期算子（新增）

| 算子 | 用途 | 关键输入 |
|---|---|---|
| `attribution` | 多模型归因（last_touch / linear / time_decay / position_based / shapley / first_touch），对账 + 模型分歧度 | `id_field`、`channel_field`、`timestamp_field`、`conversion_field`、`value_field`、`models`、`half_life_days`、`lookback_days` |
| `cohort_retention` | 同期群留存矩阵，仅用成熟 cohort 计算平均曲线 | `id_field`、`date_field`、`period`、`max_periods`、`min_cohort_size`、`cohort_field` |
| `survival` | Kaplan-Meier 曲线 + log-rank 分组比较 | `duration_field`、`event_field`、`group_field`、`survival_at_times` |
| `path_analysis` | 转移矩阵、入口/出口、自环与高频路径 | `id_field`、`step_field`、`timestamp_field`、`terminal_steps`、`session_gap_minutes` |
| `rfm` | R/F/M 三维度分位切点 + 8 段标签 | `id_field`、`date_field`、`value_field`、`reference_date`、`bins` |
| `price_elasticity` | log-log 弹性估计 + 反事实测算（非随机化定价最多 L1） | `price_field`、`quantity_field`、`group_field`、`randomized_pricing` |

## 实验设计与统计算子（新增）

| 算子 | 用途 | 关键输入 |
|---|---|---|
| `power_mde` | 功效 / MDE 正算与反解；纯设计，无需数据 | `metric_type`、`baseline_rate` / `baseline_mean`/`baseline_sd`、`mde_absolute` 或 `mde_relative`、`alpha`、`power`、`n_per_arm` |
| `srm_check` | 样本比例失衡 + 跨组单位识别 | `variant_field`、`unit_field`、`expected_ratio` |
| `multiple_testing` | Bonferroni / Holm / BH-FDR 校正 | `tests[]`（含 `p_value` 与可选 `prespecified`）、`method`、`alpha` |
| `cuped` | 协方差缩减方差，处理前均衡检查 | `variant_field`、`metric_field`、`covariate_field`、`control`、`treatment` |
| `changepoint_scan` | 季节性调整 + CUSUM + 水平切点 | `date_field`、`metric_field`、`min_segment_days`、`seasonality`、`cusum_drift`、`cusum_threshold` |

`power_mde` 与 `multiple_testing` 是纯设计算子（`--data` 可省略），其他需要数据。

分母为 0、样本不足、日期不齐、基线不可用、分组样本 < `min_segment_size`、协变量缺失或窗口未成熟时返回结构化错误，不返回伪造数字。

## 表内对账（写数字之前推荐先跑）

中文表格几乎都自带校验和：末尾的「合计」、分组后的「小计」。`da_reconcile.py`
把汇总行捞出来，推断每一行的管辖范围，再用明细行重算一遍：

```bash
python scripts/da_reconcile.py --data <文件路径> [--sheet 名称] --out <对账.json>
```

```
✓ R001 地区==华东 / 金额: 表内 21,000.75 vs 明细 21,000.75  [consistent]
✗ R003 全表明细 / 金额: 表内 99,999.99 vs 明细 30,500.75  [inconsistent]
MASTER CHECK：不通过：1 项对不上。在解决之前，不要把这些数字写进交付物。
```

- 退出码：`0` = 全部对上或表中没有可对账的汇总行；`1` = 有对不上的地方，可直接当流水线闸门；
- 比率行（占比 / 同比 / 率）与比率列不参与加总，列入 `skipped`，不会把 `0.6` 当金额加进合计；
- 支持千分位、会计式括号负数、货币符号、全角数字；容差默认 `绝对 0.5 / 相对 0.5%`，覆盖四舍五入；
- 输出条目自带 `id` / `status` / `verified`，直接作为 `da_verify.py --reconciliation` 的输入。

## 发布前真实性检查（推荐必跑）

```bash
python scripts/da_verify.py --claims <claims.json> --evidence <证据.json> --reconciliation <对账.json> --agents-dir <agents> --require-agent-manifest [--strict]
```

`da_verify.py` 检查每条结论是否有 `evidence_ids`、因果措辞是否越过 L2 门槛、statement 数字能否在**它自己引用的证据条目**里按量纲与方向溯源、是否引用了表内已被证伪的数字，以及独立角色工件和执行 manifest 是否有效。它不生成报告、不做分析、不规定视觉格式。

### `da_verify.py` 门禁（0.7.0）

- **按条目绑定**：证据文件带 `id` 条目时，结论只能用它 `evidence_ids` 指向的条目里的数字——「渠道A 贡献 900」不能再拿「渠道B = 900」来溯源；
- **对账联动**：`--reconciliation` 传入对账结果后，引用 `verified: false` 的条目会被 `reconciliation_mismatch` 拦下；同时披露表内值与明细值的结论不算掩盖；
- **方向与符号**：`下降 20.45%` 不再匹配 `+0.2045`，「上升」写反会被抓出；`-20.45%`、`1,234.56` 都能正确解析；结论里同时出现上下行时不强加方向约束；
- **序号不算数据**：「分组 3」「第 1 章」这类被引用的对象名不参与溯源，避免逼模型改措辞；
- **弱模式标注**：证据是自由结构（条目没有 `id`）时给 `unscoped_evidence` 警告，提示数字只做了数字袋匹配；
- `--require-evidence`（默认开启）：未传 `--evidence` 时数字溯源直接 fail；
- `--no-require-evidence`：显式关闭溯源（不推荐）；
- `--lenient-numbers`：把数字不可溯源降级为警告（默认直接 fail）；
- `--require-evidence-ids`：`evidence_ids` 解析不到条目时直接 fail（默认只给 info 提示）；
- `--strict`：把弱模式证据与未解析 `evidence_ids` 升级为失败；
- `--max-exploratory-tests`（默认 5）：超过该数量的探索性结论触发 `multiple_comparison_risk` 警告；
- L2 及以上结论若使用因果/证明措辞，**必须**提供白名单内的 `identification_strategy`（`randomized` / `ab_test` / `did` / `matching` / `iv` / `rdd` / `synthetic_control` 等），**未提供同样 fail**；
- 同一时间窗被多条结论引用时给出 `repeated_window_checks` 警告。
