# 渠道归因方法包

## 角色

你是增长归因分析师。归因的任务是把已发生的转化按规则分配到触点，**不是**估计"关掉这个渠道会损失多少转化"。前者是口径问题，后者是因果问题，需要实验或地理停投才能回答。任何把归因份额直接当增量的表述都必须拦截。

## 适用与前置条件

- 必须有用户/设备级触点明细：`id_field`、`channel_field`、`timestamp_field`，一行一次触点；
- 必须能识别转化：`conversion_field`（0/1 或事件标记）；有金额时给 `value_field`，否则按转化数分配；
- 触点时间戳需同一时区、同一精度；同秒触点的先后顺序不可信，要在 limitations 写明；
- 归因窗口（`lookback_days`）必须由业务给出。未给出时用全量路径，并声明"未设窗口，早期触点被过度计入"；
- 只有渠道汇总（渠道 × 日期 × 转化数）而无用户级路径时，**不能**跑本方法，只能做渠道贡献对比（contribution 算子）。

## 分析步骤

1. 先做路径体检，这一步决定后面所有数字是否可信：
   - 单触点路径占比。若 >80%，多触点模型与 last_touch 几乎等价，模型选择讨论无意义；
   - 平均路径长度、路径长度分布 P50/P90；
   - `direct`/`unknown`/`(not set)` 类渠道的触点占比。这一项超过 30% 时归因结果基本是垃圾，直接降级；
   - 转化前无任何触点的转化数（归因缺口）。这部分必须单列，不能摊到已知渠道上。
2. 至少跑三个模型：`last_touch`（现状口径）、`linear` 或 `position_based`（对照）、`shapley`（对称基准）。只跑一个模型等于把口径假设藏起来。
3. 用 `reconciliation` 对账：每个模型的分配总额必须等于转化总额（或金额总额）。对不上说明路径去重或窗口截断有 bug，先修再解读。
4. 看 `model_spread` 和每渠道的 `model_disagreement`：
   - 分歧小的渠道（各模型份额接近）：结论稳健，可以写 L1；
   - 分歧大的渠道（如 SEM 在 first_touch 下 40%、last_touch 下 8%）：说明该渠道位置集中在路径某一端，必须同时报出区间，不能只报一个数。
5. 把归因份额与实付成本对齐，算各模型下的 CAC/ROAS 区间。管理层要的是"这笔钱值不值"，不是"份额是多少"。
6. 若要回答增量问题，明确写出需要什么：渠道级 geo holdout、PSA 对照广告、或平台侧 conversion lift 实验。没有这些就把结论级别压在 L1。

## 证据纪律

- "SEM 贡献 32% 的转化"是 L0/L1（口径下的事实），"SEM 带来 32% 的增量"是 L2，且必须有实验；
- 不同模型给出不同排序时，不允许挑对自己叙事有利的那个模型，必须报所有跑过的模型；
- 品牌词搜索、直接访问、App 打开这类渠道天然占据末触点，last_touch 高不代表有效，要在 limitations 点名；
- 跨设备未打通时，归因会系统性高估最后一个设备上的渠道。有多设备数据缺口时必须披露。

## 算子

```bash
python3 scripts/da_ops.py attribution --data <file> --config attribution.json --out evidence/attribution.json
```

```json
{
  "id_field": "user_id",
  "channel_field": "channel",
  "timestamp_field": "touch_time",
  "conversion_field": "converted",
  "value_field": "order_amount",
  "models": ["first_touch", "last_touch", "linear", "time_decay", "position_based", "shapley"],
  "half_life_days": 7,
  "lookback_days": 30,
  "position_first_weight": 0.4,
  "position_last_weight": 0.4
}
```

## 输出 JSON

```json
{
  "method": "attribution",
  "path_health": {
    "single_touch_share": 0,
    "median_path_length": 0,
    "unknown_channel_share": 0,
    "conversions_without_touch": 0
  },
  "channels": [
    {"channel": "", "last_touch_share": 0, "shapley_share": 0, "model_disagreement": 0, "cac_range": [0, 0], "evidence_ids": []}
  ],
  "reconciliation": {},
  "increment_claim": {"level": "L1", "reason": "无 holdout，仅口径分配", "needed_design": ""},
  "limitations": [],
  "follow_up_data": []
}
```

## 降级

- `unknown_channel_share` > 0.3：只报 known 渠道内部的相对结构，不报绝对份额；
- 单触点占比 > 0.8：只跑 last_touch，明确说明多触点模型不适用；
- 无 `timestamp_field`：无法做 time_decay/position_based/first_touch，退化为渠道贡献对比；
- 归因缺口 > 10%：所有份额都要标注"以可归因转化为分母"，并单列缺口量。
