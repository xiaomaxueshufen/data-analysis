# 行业视角路由

## 原则

行业模板只调整指标词典、分析重点、叙事语言和图表优先级；不替换数据质量门禁、统计方法、证据层级和因果边界。行业经验用于提出待验证问题，不用于替代用户数据。

## 识别流程

1. 模型读取用户问题、文件画像、字段样例和数据字典，提出最多三个行业候选，并说明每个候选的字段证据。
2. 如果一个候选具有清晰的业务链路和字段覆盖，标记为 `high`，向用户确认“按该行业口径分析是否正确”；用户要求直接分析时可暂用该候选，但在报告假设中披露。
3. 如果候选不唯一，给出 3–4 个具体选项，询问会改变指标定义或决策的最小问题；不要用文件名或单个字段拍板。
4. 如果数据跨行业，选择“主行业 + 辅助业务视角”，禁止把两套 KPI 混成一个总指标。
5. 无法识别行业时加载 `references/industries/general.md`，使用数据本身的字段名和用户确认的口径。

## 模板选择输出

```json
{
  "industry": {
    "primary": "retail-ecommerce|internet-saas|logistics-express|social-media-content|education-training|general|other",
    "confidence": "high|medium|low",
    "evidence": ["字段或用户描述"],
    "user_confirmation_needed": true,
    "secondary_lens": []
  },
  "template_effect": ["metric_dictionary", "analysis_priorities", "narrative_language", "chart_priority"],
  "template_does_not_override": ["quality_gate", "statistical_method", "causal_boundary", "evidence_level"]
}
```

## 行业候选提示词

```text
请根据用户问题、数据画像和字段样例识别行业视角，而不是根据文件名猜行业。
先列出最多三个候选行业；每个候选必须引用至少两个字段或业务链路证据，并说明采用该视角会改变哪些指标定义。
若候选会导致不同的分子、分母、事件时间或决策含义，必须向用户追问确认。
行业模板只提供词典、重点和叙事语言。任何行业模板都不能绕过质量门禁、改变统计基线或把相关写成因果。
```

## 当前模板索引

| 模板 | 适用信号 | 重点 |
|---|---|---|
| `general.md` | 行业不明、仅有通用指标 | 口径、趋势、分组、质量和证据边界 |
| `retail-ecommerce.md` | 订单、支付、退款、SKU、库存、加购或履约字段 | 交易漏斗、商品/库存、用户 cohort、营销归因和退款 |
| `internet-saas.md` | 订阅、合同、套餐、席位、用量、激活或续费字段 | MRR 对账、激活/留存、客户流失、单位经济和扩展 |
| `logistics-express.md` | 运单、揽收、分拨、干线、派送、签收、网点或线路 | 时效、节点漏斗、SLA、产能、异常件和成本服务权衡 |
| `social-media-content.md`（Social Media / Content Creation） | 内容/作品、账号/作者、曝光、播放、观看、互动、关注或外链字段 | 内容分发、观看/互动、受众留存、归因和创作效率 |
| `education-training.md`（Education / Training） | 学员/报名、课程/班级/课次、出勤、作业、考试、结课或缴退费字段 | 招生漏斗、出勤/完成 cohort、学习增益、续报和教学运营 |
