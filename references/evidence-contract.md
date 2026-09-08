# 证据合同与结论门禁

## 结论对象

```json
{
  "claim_id": "C001",
  "statement": "结论文字，不超过两句",
  "level": "L0|L1|L2|L3|L4",
  "status": "fact|comparison|supported_candidate|hypothesis|action",
  "evidence_ids": ["E001", "E004"],
  "scope": {"date": "2026-07-27", "date_window": "2026-07-20..2026-07-27", "dimension": null},
  "confidence": "high|medium|low",
  "limitations": ["无处理对照，不能确认因果"],
  "identification_strategy": "randomized|ab_test|did|matching|iv|rdd|synthetic_control|null",
  "next_test": "要补什么数据才能升级"
}
```

`identification_strategy` 在 L2 及以上使用因果/证明措辞时必填，且必须在 `da_verify.py` 的 `VALID_IDENTIFICATION` 白名单内（`randomized` / `ab_test` / `did` / `difference_in_differences` / `matching` / `iv` / `instrumental_variable` / `rdd` / `regression_discontinuity` / `synthetic_control`）。未提供或不在白名单内 → `causal_language_without_identification` 失败。

`scope.date_window` 用于检测同一时间窗被多条结论引用（`repeated_window_checks`）；超过 `--max-exploratory-tests`（默认 5）条 `status: hypothesis` / `exploratory` 的结论触发 `multiple_comparison_risk`。

## 证据要求

- L0：一个可定位的计算结果即可；数字必须能从 evidence JSON 中按量纲匹配；
- L1：计算结果加明确基线、样本和比较方向；
- L2：至少两个互相独立的观测，或一个可闭合的分子分母/贡献度对账；
- L3：L2 之上，再明确决策对象、风险和适用范围；
- L4：只有用户要求行动建议且已给出责任边界、触发条件和验收指标时才写。

## 禁用升级

仅凭相关系数、单个分组降幅、同日共现、模型常识、文件名或用户预期，不能把 L0/L1 升级为 L2。仅凭 L2 也不能自动升级成因果。数据事故、样本不足和口径不确定会把结论降级或阻断。

数字溯源规则（`da_verify.py`）：
- raw（裸数） / percent（%） / pp（百分点）三种量纲独立匹配；
- raw ↔ percent 反向转换不被允许——`0.116` 不能匹配 `11.6%`，反之亦然；
- `--strict` 把数字溯源警告升级为失败；
- 未传 `--evidence` 时整段 fail（除非显式 `--no-require-evidence`）。

## 发布检查

报告发布前逐条检查：

1. 数字是否来自 JSON 证据，不重新计算；
2. 百分比是百分点还是相对百分比，是否写清；
3. 比率是否从分子分母重算，未把分组率简单平均；
4. 是否列出至少一个抵消项或明确没有发现可验证抵消项；
5. 是否把所有受影响日期和字段放入排除区；
6. 后续建议是否对应一个未解决的问题，而不是空泛提醒；
7. L2 及以上因果措辞是否挂上 `identification_strategy`，且在白名单内；
8. 探索性结论数是否超过阈值，超过时是否在 limitations 中标注多重比较风险。

