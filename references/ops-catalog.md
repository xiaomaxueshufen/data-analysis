# 可选验证算子目录

这些算子是**可选的单点复核工具**，不是分析流水线。模型可以现场编写一次性代码完成全部分析，也可以在需要交叉验证某个关键数字时调用其中某个算子。没有任何算子是必经路径。

各脚本入口：

```bash
python scripts/da_profile.py --data <文件路径> --out <profile.json>
python scripts/da_quality.py --profile <profile.json> --data <文件路径> --contract <semantic_contract.json> --out <quality.json>
python scripts/da_ops.py <operator> --data <文件路径> --config <配置.json> --out <证据.json>
python scripts/da_verify.py --claims <claims.json> --agents-dir <agents> --require-agent-manifest [--evidence <evidence.json>]
```

| 脚本/算子 | 用途 | 关键输入 |
|---|---|---|
| `da_profile.py` | 识别 sheet、表头、字段、类型、缺失和时间覆盖 | 文件路径 |
| `da_quality.py` | 检查合同字段缺失、日期重复、空值、极端值和异常延迟 | profile、原始文件、语义合同 |
| `anomaly_scan` | 计算同星期/滚动基线、偏离和 robust z | 日期、指标、`baseline_window_days` |
| `funnel_rates` | 由阶段计数重算阶段率、损失量 | 阶段字段顺序 |
| `ratio_decomp` | 将比率变化拆为组内与结构变化 | 分子、分母、维度、基线 |
| `contribution` | 将总量缺口按组对账 | 组、当前值、基线值 |
| `ab_effect` | 效应、标准误、置信区间和基本显著性 | 分流、指标、`confidence_level` |
| `segment_profile` | 分层规模、价值和覆盖 | 分层字段、指标 |

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

## 发布前真实性检查（推荐必跑）

```bash
python scripts/da_verify.py --claims <claims.json> --agents-dir <agents> --require-agent-manifest [--evidence <evidence.json>] [--strict]
```

`da_verify.py` 检查每条结论是否有 `evidence_ids`、因果措辞是否越过 L2 门槛、statement 数字能否在证据中找到相近值，以及独立角色工件和执行 manifest 是否有效。它不生成报告、不做分析、不规定视觉格式。

### `da_verify.py` 新增门禁

- `--require-evidence`（默认开启）：未传 `--evidence` 时数字溯源直接 fail，避免整段跳过；
- `--no-require-evidence`：显式关闭溯源（不推荐，会留下 `no_evidence_provided` 之外的盲区）；
- `--max-exploratory-tests`（默认 5）：超过该数量的探索性结论触发 `multiple_comparison_risk` 警告；
- `--strict`：把 `untraceable_number` 警告升级为 fail；
- L2 及以上结论若使用因果/证明措辞，必须提供 `identification_strategy`（`randomized` / `ab_test` / `did` / `matching` / `iv` / `rdd` / `synthetic_control` 等），否则 fail；
- 数字溯源按"量纲"严格匹配：raw / percent / 百分点（pp）三种量纲独立，raw↔percent 反向转换不被允许；
- 同一时间窗被多条结论引用时给出 `repeated_window_checks` 警告。
