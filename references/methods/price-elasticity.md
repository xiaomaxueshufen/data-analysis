# 价格弹性方法包

## 角色

你是定价分析师。价格弹性的核心回答是"价格变动 1% 时，需求量变动多少 %"，**不是**"提价能否增加收入"。后者取决于弹性绝对值是否 > 1，而不是弹性的符号。任何把"需求弹性 = -1.5" 直接翻译为"提价增加营收"的写法都必须拦截。

## 适用与前置条件

- 必须有 `price_field` 与 `quantity_field`，至少覆盖一个价格段的时间序列或横截面；
- 数据必须满足：
  - 价格有真实变动（方差非零）；全是同一价格只是横截面差异不算弹性；
  - 不能包含促销、捆绑、满减导致的"名义价格"——用名义价格估计的弹性绝对值偏高；
  - SKU/地区/时间维度分组时，每组至少 10 个观测点。
- 必须显式标记识别假设（`identification`）：
  - `observational`（观测）：默认；结论最多 L1；
  - `randomized_pricing`：随机定价实验；允许 L2/L3；
  - 否则不允许写"提价导致销量下降"。
- 季节性、共生变量（竞品价格、库存、广告投放）未控制时，弹性估计偏差未知，必须报 limitations。

## 分析步骤

1. 先看描述统计：
   - 价格 P50/P10/P90，决定价格变动范围；
   - 销量序列是否有长期趋势/季节性——若有，先做 log 差分或加周/月哑变量；
   - 任何"销量为 0"的观测剔除。零值进 log 模型会变 -∞，且零本身可能是缺货而非无需求。
3. log-log 回归：`log(q) = α + β log(p) + ε`，β 即弹性。
   - 必须输出 R² 与残差图诊断：高 R² + 残差同方差 → 模型可用；R² < 0.1 或残差自相关 → 不可用，方法降级。
4. 分组估计：
   - 按 SKU / 品类 / 用户分层；分组内样本不足时返回 `below_min_sample: true`，不要硬估；
   - 跨组弹性差异 > 0.5 时说明"用户结构非均质"，不能用单点弹性下结论。
5. 反事实测算必须做边界检查：
   - 价格涨幅 > 当前价格 P50 的 50% 时进入外推区，标记 `out_of_sample_projection: true`；
   - 测算出的"营收变化方向"（`revenue_direction_of_price_increase`）若与单点弹性推断方向不一致（如弹性 -1.5 但算出来提价营收上升），必有 bug 或 R² 太低，立即返工。
6. 把"价格"外的其他维度（共品、库存、广告）进 OLS 控制后回归，与单变量弹性对比，差异 > 0.3 提示遗漏变量严重。

## 证据纪律

- 弹性估计的最大声明级别由 `randomized_pricing` 决定。无随机化，**绝对不能**写"提价会令销量下降 X%"；
- 正弹性（弹性 > 0）通常意味着内生性问题（Veblen 商品、价格作为质量信号、逆向选择），不是需求定理被推翻，必须在 limitations 标注；
- "弹性 -1.5" 与"提价能涨营收"是数学等价：**错的**。公式要求 |弹性| > 1 才提价营收上升；|弹性| < 1 时提价营收下降；
- 用昨日价格预测今日需求、用今日价格解释今日需求都是共同变化，不写因果。

## 算子

```bash
python3 scripts/da_ops.py price_elasticity --data <file> --config elasticity.json --out evidence/elasticity.json
```

```json
{
  "price_field": "unit_price",
  "quantity_field": "units_sold",
  "group_field": "sku",
  "identification": "observational",
  "randomized_pricing": false,
  "min_points": 10,
  "min_segment_size": 30
}
```

## 输出 JSON

```json
{
  "method": "price_elasticity",
  "overall": {
    "elasticity": 0,
    "demand_type": "elastic|unit|inelastic",
    "revenue_direction_of_price_increase": "revenue_falls|revenue_rises|indeterminate",
    "r_squared": 0,
    "n": 0
  },
  "groups": [{"group": "", "elasticity": 0, "below_min_sample": false, "n": 0}],
  "identification": {"strategy": "observational", "randomized_pricing": false, "max_claim_level": "L1"},
  "diagnostics": {"zero_obs_dropped": 0, "out_of_sample_projection": false},
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- 价格方差为零：方法不可用，禁止用均值代入；
- 销量零值 > 10%：剔除后跑，必须报告剔除量与偏差方向；
- 分组样本 < `min_points`：返回 `below_min_sample: true`，不强行估计；
- R² < 0.1：只输出"未识别出显著弹性曲线"，禁止输出弹性数值；
- `randomized_pricing: true`：允许 L2，但结论必须挂置信区间；不挂就是误导。