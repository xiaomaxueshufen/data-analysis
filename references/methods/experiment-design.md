# 实验设计方法包（功效 / MDE / SRM / CUPED）

## 角色

你是实验分析师。本包回答三类问题：

- 在某个最小可检测效应下，需要多少样本（**power / MDE**）；
- 分流系统是否合规（**SRM**）；
- 实验已经跑出结果，但样本量不足或方差过大（**CUPED**）。

任何把这三类之外的判断（如"实验是否可信""能不能上线"）也写在本包里的，必须重新分发到 `ab-test.md` 与 `da_verify.py`。

## 适用与前置条件

- 指标必须明确：二元率（`metric_type: binary`）或连续（`continuous`）；
- baseline 与 MDE 口径必须显式：
  - 二元率必须给 `baseline_rate` 与 `mde_absolute`（如 0.05）或 `mde_relative`（如 0.1）；
  - 连续指标必须给 `baseline_mean`、`baseline_sd` 与相对/绝对 MDE。
- alpha 默认 0.05，power 默认 0.8。改这两个参数必须写理由（合规要求 / 历史经验）；
- 双侧 vs 单侧（`two_sided` 默认 True）；单侧必须有业务/合规依据；
- 每组样本量 `daily_traffic_per_arm` 用于给出天数估算，否则只给单组样本量。

## 分析步骤

### 一、功效与 MDE

1. **先正算样本量**（`given_mde`）：给定 baseline、MDE、alpha、power、ratio（默认 1:1）算出每组样本量。
2. **再反算 MDE**（`given_sample_size`）：在已知样本量下，能检测到的最小效应。这是实验前的"现实检查"——若 N 不够，必须先估算。
3. **功效曲线**（`power_curve`）：每个 MDE 对应的样本量，必须单调（效应增大 → 样本量降低）。
4. **不要把功效估算当结论输出**：功效是事前设计参数，不写"实验功效 80%"——这等于重复声明输入。

### 三、SRM（Sample Ratio Mismatch）

1. **必须基于实验单位（`unit_field`）做唯一计数**。一个单位跨组是致命缺陷，状态 `block`。
2. 期望分流（`expected_ratio`）必须从分流服务配置中读取，不允许默认 50/50 后强行通过。
3. SRM p < 0.001 才报"检测到 SRM"；p < 0.05 只能作为 `warn`，原因：
   - 多实验同时跑会推高 SRM 报警的假阳率（假阳率按 m α 控制，未校正 p 值不可信）。
4. SRM 报警后建议动作：检查分流服务日志、曝光时间窗、bot 流量过滤——不写"实验失败"。

### 四、CUPED（Controlled-experiment Using Pre-Experiment Data）

1. CUPED 必须有同期协变量（`covariate_field`）。无协变量时本算子不可用，方法学上与普通 t-test 等价。
2. **处理前协变量均衡检查**（`pre_period_balance`）必须先过：
   - 处理组 vs 对照组的 covariate 分布 p > 0.01 才允许继续 CUPED；
   - 否则降级为差分中差分（DiD）或返回警告。
3. CUPED 给出：
   - `variance_reduction`：> 0.5 才有显著收益；
   - 调整后效应（`adjusted_effect`）和原始效应（`raw_effect`）必须分别报告；
   - 调整后 CI 必须更窄，否则是计算错误。
4. **CUPED 不是因果识别策略**，只是方差缩减。结论级别仍按识别策略走——随机化 → L2/L3；观测 → L1。

## 证据纪律

- "功效 80%"是输入，不是结论；
- "样本量充足"的反义是"能检测到 MDE"——MDE = 业务判定可接受的最小效应，不是统计上"显著"的最小效应；
- SRM 报警 + 跨组单位同时出现，**必须阻断**解读，不是"提示"；
- CUPED 调整后效应与原始效应方向不一致时，**默认相信原始效应**——调整可能因协变量偏差错位；
- 跑过 SRM + CUPED 不等于"实验合规"——还看曝光窗口、用户首次进入时间、独立性。

## 算子

```bash
python3 scripts/da_ops.py power_mde --config power.json --out evidence/power.json
python3 scripts/da_ops.py srm_check --data <file> --config srm.json --out evidence/srm.json
python3 scripts/da_ops.py cuped --data <file> --config cuped.json --out evidence/cuped.json
```

```json
{"metric_type": "binary", "baseline_rate": 0.05, "mde_absolute": 0.005, "alpha": 0.05, "power": 0.8, "daily_traffic_per_arm": 5000}
```

```json
{"variant_field": "variant", "unit_field": "user_id", "expected_ratio": {"A": 0.5, "B": 0.5}}
```

```json
{"variant_field": "variant", "metric_field": "post_metric", "covariate_field": "pre_metric", "control": "A", "treatment": "B", "confidence_level": 0.95}
```

## 输出 JSON（统一格式）

```json
{"method": "power_mde", "given_mde": {"n_control": 0, "n_treatment": 0, "days_needed": 0}, "given_sample_size": {"detectable_absolute_effect": 0}, "power_curve": [], "assumptions": {"two_sided": true, "alpha": 0.05, "power": 0.8}}

{"method": "srm_check", "status": "pass|block", "srm_detected": false, "p_value": null, "cross_assigned_units": 0, "expected_ratio": {}, "observed_ratio": {}}

{"method": "cuped", "pre_period_balance": {"balanced": true, "p_value": 0}, "raw_effect": {"effect": 0, "ci": [0, 0]}, "adjusted_effect": {"effect": 0, "ci": [0, 0]}, "variance_reduction": 0, "theta": 0}
```

## 降级

- 缺协变量：禁用 CUPED；
- 单元跨组 > 0：禁用所有分析，必须分流层修；
- SRM p 在 [0.001, 0.05)：返回 warn，不阻断；
- alpha 或 power 越界（α > 0.5、power < 0.5）：报错；
- baseline 为 0 或方差为 0：报错，不强行估算。