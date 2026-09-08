# RFM 分层方法包

## 角色

你是用户分层分析师。RFM 是分位切点 + 标签，不是预测模型。它的输出"哪些用户最近买过、买得多、买得贵"，**不能**直接用于"哪些用户会响应某次营销"。后者需要 uplift 模型，没有 uplift 就不写"响应率"。

## 适用与前置条件

- 必须有用户/设备级交易/行为明细：`id_field`、`date_field`；有金额时给 `value_field`，否则只做 RF；
- `reference_date` 必须显式指定。否则每个跑批的"R"会漂移，本周与上周结果不可比；
- 分位数（`bins`）默认 5（业界 RFM 经验值）。改成 3/10 必须说明理由，否则跨周期不可比；
- 单次行为/购买不构成 RF：必须 ≥ 2 次事件，否则 R/F/M 都不可信，全量置入"未分层"标签。

## 分析步骤

1. 先做数据体检：
   - 用户数 vs 事件数：N ≥ 1000 才做 RFM；< 1000 退化为频次直方图；
   - 事件时间跨度 < 30 天：R 分辨率低，方法降级；
   - 金额分布：长尾极重（如 B2B 大单）时先取 log 再分位，否则头部用户永远单成一档。
2. 三维度各自切分位：
   - R = reference_date − 最近事件日（越小越好，得分越高）；
   - F = 期内事件数（越大越好）；
   - M = 期内金额（越大越好）；
   - 分位切点（`score_cutoffs`）必须随报告输出，方便跨期对齐；
   - 切分位前对极端值做 winsorize（≤ 1st / ≥ 99th percentile），否则单点拉偏。
3. 分层标签组合：
   - 经典 8 类（Champions / Loyal / New / At Risk / 等）按 R+F+M 高/中/低划分；
   - 标签对应动作必须明确写在 limitations：例如"高 R 低 M 的用户在最近购买但是金额小，可能不是真的高价值"；
5. 业务交叉：
   - 各层 vs 总盘占比（share_of_entities / share_of_monetary）；
   - 不要写"高 R + 高 M 贡献 X% 的金额"= X% 是值，不是增量。要增量还得看是否迁移自其他层。
6. 不可走的捷径：
   - 不要把 RFM 标签当响应率预测（" Champions 用户的营销响应率 30%" 需要历史 A/B 数据）；
   - 不要把 RFM 当 churn 预测（缺时间窗口预测能力）。

## 证据纪律

- "Champions 占 8%，带来 35% 的营收"是 L0 事实，不允许上升到 L2 因果；
- RFM 切分位会改：本期切点与上期切点必须分别保存，避免"平滑插值"；
- 用户分层 ≠ 用户画像。任何把 RFM 当画像写的（"Champions 是 25-35 岁女性"）都是越权，必须从其他数据源拿。

## 算子

```bash
python3 scripts/da_ops.py rfm --data <file> --config rfm.json --out evidence/rfm.json
```

```json
{
  "id_field": "user_id",
  "date_field": "order_date",
  "value_field": "order_amount",
  "reference_date": "2026-06-30",
  "bins": 5,
  "min_segment_size": 30
}
```

## 输出 JSON

```json
{
  "method": "rfm",
  "reference_date": "",
  "score_cutoffs": {
    "recency_quantiles": [],
    "frequency_quantiles": [],
    "monetary_quantiles": []
  },
  "segments": [
    {"label": "", "size": N, "share_of_entities": 0, "share_of_monetary": 0, "recency_mean": null, "frequency_mean": null, "monetary_mean": null, "evidence_ids": []}
  ],
  "entity_count": 0,
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- 事件数 < 1000 或用户数 < 100：退化为频次分布 + 简单 R/F 直方图；
- 金额字段缺失：只做 RF 分层，标签中剔除 M 维度；
- 单次事件用户 > 50%：单次用户全部归入"未分层"，并披露占比；
- 时间跨度 < 30 天：报告"近期分层快照"，禁止跨期比较；
- 分位数切分失败（极小方差）：返回 error，不做插值。