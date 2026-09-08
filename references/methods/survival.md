# 生存与流失分析方法包

## 角色

你是流失分析师。生存分析的核心是回答"对一个尚未流失的用户，再过多久会流失"，所以必须有右删失（censoring）字段或者明确的研究窗口。无删失数据得出的中位生存时间是观察期内 50% 留存——这是数学事实，不是产品事实。

## 适用与前置条件

- 必须有每实体的 `duration_field`（生存/停留时长），单位写明（天/小时/周）；
- 必须能区分"观察到事件（流失）"vs"观察期结束仍存活"：
  - 字段式：有 `event_field`（1=发生，0=删失）；
  - 字段式无但有结束时间：用"结束时间 − 起点"截断，仍视为删失，并在 limitations 写明；
  - 两者都无：所有实体都按"已流失"处理，**不允许**——会大幅低估生存时间，本方法不可用；
- 可选 `group_field`（套餐/版本/渠道）做 log-rank 比较；分组越多越要注意多重比较；
- `survival_at_times` 是预设查询点（如 7 天、30 天、90 天），不是最大时长——别混。

## 分析步骤

1. 先看删失率。无删失样本 + 短期窗口 = 暴露窗口 vs 真实生存时间混在一起，结论基本不可信。
2. 跑 Kaplan-Meier：
   - 曲线必须单调不增；跃度（drop）= 在该时长点上的事件数 / 风险集（at risk）；
   - `survival_at_times` 给出的点估计必须等于曲线插值，不允许四舍五入成 0 或 1。
4. log-rank 仅在以下全部满足时跑：
   - 分组是预设（不是看曲线挑的）；
   - 删失模式在分组间独立（违反假设会失真，需要 Schoenfeld 检验后再说）；
   - 分组数 ≤ 4（再多就走 multiple_testing 算子）。
5. 中位生存时间（median_survival_time）只能给观察窗口内的值；如果曲线在观察窗口内未跌破 0.5，必须写"未到中位"而不是无穷大或缺失。
6. 风险集（at risk）表单独输出：哪些实体在哪个时长还处于风险中。
   - 例：第 7 天 at_risk=1200、第 30 天 at_risk=300 表示大量用户在 30 天前就离开了。

## 证据纪律

- "30 天留存 60%"是 KM 在 t=30 的 S(30)，不是"30 天后还有 60% 用户没走"——后者还受中位生存时间影响；
- log-rank p < 0.01 但置信区间跨 0 是常事：解读时优先说 CI，p 值其次；
- 删失与事件**非独立**时（如活跃度低的用户更容易被系统失联），KM 估计有偏，方法学上不能信赖；
- 分组比较只输出相对风险/中位差异，不输出绝对增量——绝对增量属于 causation 实验。

## 算子

```bash
python3 scripts/da_ops.py survival --data <file> --config survival.json --out evidence/survival.json
```

```json
{
  "duration_field": "tenure_days",
  "event_field": "churned",
  "group_field": "plan",
  "survival_at_times": [7, 30, 90]
}
```

## 输出 JSON

```json
{
  "method": "survival",
  "overall": {"curve": [{"time": 0, "survival": 1.0, "at_risk": N, "events": K}], "censored": N, "median_survival_time": null, "survival_at_times": {}},
  "groups": [{"group": "", "median_survival_time": null, "survival_at_times": {}}],
  "log_rank": {"statistic": null, "p_value": null, "prespecified": true},
  "assumptions": {"independent_censoring": "untested", "proportional_hazards": "untested"},
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- 无 `event_field`：方法不可用，改为 `cohort_retention` 算子 + 显式截断警告；
- 删失率 > 50% 且删失分布与事件不等：降级为观察期内累计留存率，不报生存曲线；
- 分组 > 4：只跑预设的主分组，其余分组用 `multiple_testing` 算子单独校验；
- 生存时间为 0 的实体：剔除并在 limitations 说明，避免跃度过大拉偏曲线。