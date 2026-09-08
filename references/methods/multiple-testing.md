# 多重比较校正方法包

## 角色

你是统计分析师。本包只回答"多个指标 / 多个分群 / 多个时间窗的检验同时跑时，p 值应当怎么调"。**不能**用它替代预注册——校正后的显著性是数学上的真实，但仍是事后多重比较的话，结论不能写 L3。

## 适用与前置条件

- 必须输入 `tests` 列表，每项含 `label` 与 `p_value`（可选 `effect_size` / `n`）；
- 必须显式给出 `method`：`bonferroni` / `holm` / `bh`（FDR）。默认 BH，主指标仅一条时建议 Bonferroni；
- `prespecified: true` 必须挂在主指标 / 主分组上，否则视为探索性结论；
- 任意 p_value 越界（< 0 或 > 1）：报错，不静默跳过；
- 探索性结论（`status: hypothesis`）超过阈值（默认 5）时，必须触发 `da_verify.py` 的 `multiple_comparison_risk` 警告——但本算子仍然允许运行。

## 分析步骤

1. **先标注主指标 / 主分组**：`prespecified: true` 的项被视为预注册，剩下的归入探索性。
2. **Bonferroni**：阈值 = α / m（m = 检验总数）。最保守，适合主指标单一且检验数少（m ≤ 5）。
3. **Holm**：按 p 升序逐步收紧阈值。在 m ≤ 10 时几乎等同于 Bonferroni 但少 1 次。
4. **BH（Benjamini-Hochberg）**：控制 FDR。**前提：检验间相对独立或弱相关**——同窗口、同用户的多个指标强相关时 FDR 会被低估，必须在 limitations 写"违反独立性假设"。
5. 三种方法的输出：
   - `significant_before_correction`：原始 p < α 的数量；
   - `significant_after_correction`：校正后仍显著的数量；
   - `adjusted_p`：每个检验的调整后 p 值；
   - 显著项列表（label + adjusted_p + effect_size）。
6. **只对 p 值 < 0.1 的检验做 FDR**：全 1.0 的 p 值不需要校正，会拖累计算效率。但不要因为"反正都不过"就剔除主指标。
7. **同窗口重复检验**（`repeated_window_checks`）：同一时间窗被多次引用时，单条结论的显著性不能直接叠加——这是与 BH 不同的另一个独立风险，必须在 `da_verify.py` 阶段提示。

## 证据纪律

- BH 校正后仍显著，但相关矩阵严重违反独立性 → 退回 Holm 或 Bonferroni；
- 校正后显著项不允许只挑一条写报告——必须列出全部显著项；
- 调整后 p = 0.049 是显著，0.051 不是，**不要**用"接近显著"作为 L2 表述；
- 探索性显著结论（`exploratory_significant_labels`）只能写"信号"或"候选"，不写"显著"。

## 算子

```bash
python3 scripts/da_ops.py multiple_testing --config mt.json --out evidence/multiple_testing.json
```

```json
{
  "tests": [
    {"label": "primary_conversion", "p_value": 0.002, "prespecified": true, "effect_size": 0.005},
    {"label": "seg_a_conversion", "p_value": 0.011, "status": "hypothesis"},
    {"label": "seg_b_conversion", "p_value": 0.03, "status": "hypothesis"},
    {"label": "retention_d7", "p_value": 0.04, "status": "hypothesis"}
  ],
  "method": "bh",
  "alpha": 0.05
}
```

## 输出 JSON

```json
{
  "method": "multiple_testing",
  "method_used": "bh",
  "alpha": 0.05,
  "tests": [
    {"label": "", "p_value": 0, "adjusted_p": 0, "prespecified": true, "significant_after_correction": true}
  ],
  "significant_before_correction": 0,
  "significant_after_correction": 0,
  "exploratory_significant_labels": [],
  "independence_assumption": "assumed|violated",
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- 检验数 ≤ 1：不校正，直接报 p 值；
- 全部 p_value ≥ α：不校正但保留原始值，给出"无需校正"备注；
- m > 100：建议拆分到每个主指标单独校正，避免 BH 在强相关时失效；
- BH 独立性假设被否定：降级为 Holm 或 Bonferroni，并在 limitations 标注。