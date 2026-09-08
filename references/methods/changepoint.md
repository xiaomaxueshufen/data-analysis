# 断点检测与 CUSUM 监控方法包

## 角色

你是异动归因分析师。断点检测回答的是"指标在什么时候、从多少变到多少"，**不**回答"为什么变"。任何在断点附近挂因果动词的句子必须先有事件证据。

## 适用与前置条件

- 必须有 `date_field`（事件/记录日期）与 `metric_field`；
- 至少 30 个时间点。少于 30 个点，CUSUM 与水平切点的统计量都不可信；
- 必须有周期性参考（`seasonality` 默认 `weekly`）：
  - 日数据 → 周周期（周一对比周一）；
  - 周数据 → 周周期（同周对同周），或月周期；
  - 月数据 → 月周期（同月对比）。
- 若没有日历对齐，方法降级为滚动中位数基线，结果在 limitations 注明；
- 数据中存在"零值/缺失日/低流量日"时，季节性调整时窗口内的天数要剔除，避免拉低基线。

## 分析步骤

1. **先做季节性调整再做断点检测**。不调整的话周一周五天然差异会被当作断点。
   - 周周期：取过去 N 周同一 weekday 的中位数作为基线；
   - 月周期：取过去 N 月同一 date-of-month 的中位数。
   - 输出 `seasonal_adjustment.method` 与每个点的"调整值"，方便复核。
2. **CUSUM 与水平切点并行**，两者必须互相印证：
   - CUSUM 给出报警点（`cusum.alarms`）——累计偏移超过阈值（默认 5×σ）；
   - 水平切点（`level_shift`）给出"在哪一天均值发生显著跳变"；
   - 报警点与切点相差 ≤ 3 天才算稳健，否则只报告单一方法。
3. **断点位置是数据挑选出来的，实际显著性弱于该数值**——这一行必须在 limitations 里出现。
   - 因为 CUSUM 与切点扫描本质是多假设检验，没做 FDR/Holm 校正的单点 p 值是乐观的；
   - 解释为"该点为最强候选断点"，而不是"该点是显著断点"。
4. 写报告前必须给出方向（升/降/无变化）、幅度（绝对差、百分点差、相对差）、持续性（断点后 ≥ 7 天趋势是否仍维持）：
   - 单日尖峰 + 第二天立即回到原水平：写"尖峰"，不写"断点"；
   - 持续 ≥ 7 天的水平漂移：写"断点"，并保留方向。
6. 避免常见错误：
   - 不要对原始序列算 CUSUM，必须先做季节性调整；
   - 不要把节假日拉低/拉高的"日历异常"算业务断点——需要日历日历异常兜底；
   - 不要把"上升后回落"当成"无断点"——这是一个尖峰 + 一个反转。

## 证据纪律

- 断点处的事件归因必须挂 evidence_ids，否则只能写"与 XX 时间事件同时发生"，不写"由 XX 导致"；
- 多候选断点并列时（如有两个方向的跳变），必须分别给 evidence，不允许合并表述；
- "自上月初断崖式下跌"中的"断崖式"必须基于切点幅度 + 持续天数 + 不受随机波动影响三项验证；
- 调整后季节性窗口短（如 N=4 周）会因样本不足而高估基线，必须披露 N。

## 算子

```bash
python3 scripts/da_ops.py changepoint_scan --data <file> --config changepoint.json --out evidence/changepoint.json
```

```json
{
  "date_field": "date",
  "metric_field": "orders",
  "min_segment_days": 7,
  "seasonality": "weekly",
  "cusum_drift": 0.5,
  "cusum_threshold": 5.0
}
```

## 输出 JSON

```json
{
  "method": "changepoint_scan",
  "level_shift": {"date": "", "shift": 0, "from_value": 0, "to_value": 0, "approximate_p_value": 0},
  "cusum": {"alarms": [], "max_statistic": 0, "threshold": 0},
  "seasonal_adjustment": {"method": "weekly", "window_weeks": 8, "method": ""},
  "duration_check": {"first_alarm_to_last_alarm_days": 0, "sustained": true},
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- 数据点 < 30：方法不可用，禁止输出断点；
- 无 `date_field`：退化为横截面分布对比（均值差 + IQR 重叠），不报断点；
- 季节性窗口内样本不足：基线回退为滚动中位数，注明"无季节性调整"；
- 多断点候选无法收敛：保留两个最强候选并明确分歧，不强行报单一答案；
- 噪声过大（CUSUM 最大值 < 阈值）：报告"未识别到显著断点"，禁用最低报警点替代。