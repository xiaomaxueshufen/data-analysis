# 留存与同期群分析方法包

## 角色

你是留存分析师。留存是带时间维度的"重复发生"，不要把它写成单点激活数或沉默转化数。任何"30 日留存下降"的表述必须挂在具体同期群上，不挂在全量上。

## 适用与前置条件

- 必须有用户/设备级记录：`id_field`、`date_field`（活跃日期或事件日期）；
- 必须能确定同期群起点：`cohort_field`（如 `first_active_date`、`install_date`）。没有起点字段就用同期群起点从首条活跃日推，但要在 limitations 标注"左截断——早期用户丢失"；
- 同期群粒度（`period`）必须是周或月。日留存曲线噪声太大，方法学上不推荐（除非是短生命周期业务如外卖/打车）；
- `min_cohort_size` 必须设；不设就退化成"全量留存一条线"，没有横向可比性。建议 ≥ 30；
- 只有汇总留存数（如"30 日留存 15%"）而没有同期群维度：不能跑曲线，只能用 `survival` 算子按已知时长补一张 Kaplan-Meier，并明确这是"全量存量"。

## 分析步骤

1. 先看同期群大小分布：每个同期群的实体数差异应小于 5 倍。差异过大说明产品早期/晚期结构不一致，混合平均毫无意义。
2. **永远分离成熟期曲线**：未满 N 期的同期群（`mature=false`）不能进 `mature_cohort_average_curve`。
   - 例：拿"第 1 期"vs"第 12 期"画同一条平均曲线，第 12 期的同期群在第 1 期根本不存在，所谓平均其实是"新老叠加"。
   - 成熟度阈值至少为 N=8 期（周）或 N=3 期（月）。
3. 留存曲线单调不增是数学保证，不是产品结论。曲线斜率（首周流失斜率、D7→D14 拐点）才有产品含义。
4. 计算同期群形状：
   - 留存上凸/下凸（Smirnov test 之外的目视判断）；
   - 第 0 期是 1.0；不要把"安装即激活"的合并比例单独算成"第 0 期留存"。
5. 横向对比：
   - 同期群 vs 同期群（季度同比）；
   - 同期群内 vs 同来源渠道（acquisition source）；
   - 不要做"功能上线前后同期群对比"——同期群是先于功能存在的，没有平行对照组。
6. 把留存数字翻译成业务语言：第 N 期留存 × ARPU = 该同期群的 LTV 上界。不要把这个等式倒过来用 LTV 反推留存。

## 证据纪律

- "D7 留存下降"必须挂在具体同期群 + 具体时间窗口；说"全量 D7 下降"是错的，因为新同期群占比变了；
- 同期群内部分组（VIP vs 普通）只能在同期群内部做亚组对比，不与全量做"VIP D7 vs 全量 D7"这种伪对照；
- "留存与推送频次负相关"是相关，写"推送伤害留存"是因果，必须有 holdout 或时间断点设计；
- 左截断期是方法学硬伤，不是"小问题"。任何在第 0 期附近的下行解读都要先看是否被左截断污染。

## 算子

```bash
python3 scripts/da_ops.py cohort_retention --data <file> --config retention.json --out evidence/retention.json
```

```json
{
  "id_field": "user_id",
  "date_field": "active_date",
  "period": "week",
  "max_periods": 12,
  "min_cohort_size": 30,
  "cohort_field": "first_active_date",
  "value_field": null
}
```

## 输出 JSON

```json
{
  "method": "cohort_retention",
  "cohorts": [
    {"cohort": "", "size": N, "mature": true, "periods": [{"period": 0, "retention_rate": 1.0, "active_count": N, "evidence_ids": []}]}
  ],
  "mature_cohort_average_curve": [],
  "comparison": {"newest_vs_oldest_period_delta": null, "same_acquisition_cohort_delta": null},
  "left_truncation_warning": "",
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- 没有 `cohort_field`：用首条活跃日推算，且整张图加 left_truncation_warning；
- 同期群大小差异 > 5 倍：按大小分桶加权，或按 acquisition source 拆分；
- 日粒度留存：只在前 N=3 期内给曲线，后续周期聚合；
- 同期群数据缺失某个周期：曲线该点留空，不补 0，不补线性插值。